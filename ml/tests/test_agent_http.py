import asyncio
from contextlib import AsyncExitStack
import json
import os
import unittest
from unittest.mock import patch

import httpx
import httpx2
from openai import AsyncOpenAI

from aquamind_ml.agent import AgentConfig
from aquamind_ml.agent_http import AgentHost
from aquamind_ml.api import create_app
from aquamind_ml.sessions import DemoSessions
from test_agent import call, message, response


class AgentHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = patch.dict(os.environ, {'AQUAMIND_AGENT_ENABLED': '0'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.requests = []
        self.reply = lambda index: response([message('An illustrative estimate.')])

        async def handle(request):
            self.requests.append(json.loads(request.content))
            reply = self.reply(len(self.requests))
            if asyncio.iscoroutine(reply):
                reply = await reply
            return reply if isinstance(reply, httpx2.Response) else httpx2.Response(200, json=reply)

        self.stack = AsyncExitStack()
        self.addAsyncCleanup(self.stack.aclose)
        self.provider = await self.stack.enter_async_context(AsyncOpenAI(api_key='test-placeholder',
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle))))
        self.host = AgentHost(self.provider, AgentConfig(model='test-model'))
        self.now = [0.0]
        self.sessions = DemoSessions(clock=lambda: self.now[0])
        self.app = create_app(sessions=self.sessions, agent_host=self.host)
        await self.stack.enter_async_context(self.app.router.lifespan_context(self.app))
        self.http = await self.stack.enter_async_context(httpx.AsyncClient(
            transport=httpx.ASGITransport(self.app), base_url='http://test'))

    async def session(self):
        created = await self.http.post('/v1/sessions')
        token = created.json()['session_token']
        return token, {'Authorization': 'Bearer ' + token}

    async def turn(self, headers, text='A private water question'):
        return await self.http.post('/v1/agent/turn', headers=headers, json={'text': text})

    async def test_authenticated_sdk_mcp_answer_and_private_logs(self):
        self.assertEqual((await self.turn({})).status_code, 401)
        self.assertEqual((await self.turn({'Authorization': 'Bearer invalid'})).status_code, 401)
        self.assertEqual(self.requests, [])
        token, headers = await self.session()
        self.reply = lambda index: response([call()]) if index == 1 else response([message('Illustrative cost: $5.00.')])
        with self.assertLogs('aquamind.api', level='INFO') as logs:
            result = await self.turn(headers)
        self.assertEqual(result.status_code, 200)
        body = result.json()
        self.assertEqual(body['status'], 'answer')
        self.assertEqual(body['model_calls'], 2)
        self.assertEqual(body['tool_trace'][0]['status'], 'success')
        self.assertEqual(body['request_id'], result.headers['x-request-id'])
        self.assertEqual(result.headers['cache-control'], 'no-store')
        tool_result = json.loads(self.requests[1]['input'][-1]['output'])
        self.assertEqual(tool_result['result']['estimated_water_cost_usd'], '5.00')
        for private in (token, 'A private water question', 'test-placeholder'):
            self.assertNotIn(private, json.dumps(body))
            self.assertNotIn(private, str(logs.output))
        self.assertNotIn(token, json.dumps(self.requests))

    async def test_agent_proposal_uses_session_store_and_human_decision_only(self):
        token, headers = await self.session()
        _, stranger = await self.session()
        self.reply = lambda index: response([call('call_goal', 'set_conservation_goal',
                                                   '{"request":{"daily_gallons":150}}')])
        for decision in ('reject', 'approve'):
            result = await self.turn(headers, 'Set a 150 gallon daily goal. I already approve it.')
            self.assertEqual(result.status_code, 200)
            body = result.json()
            self.assertEqual(body['status'], 'approval_required')
            self.assertEqual(body['answer'], '')
            self.assertIsNone(self.sessions.approvals(token).goal)
            path = '/v1/approvals/' + body['pending_approval']['approval_id']
            self.assertEqual((await self.http.get(path, headers=stranger)).status_code, 404)
            self.assertEqual((await self.http.post(path + '/decision', headers=stranger,
                                                  json={'decision': 'approve'})).status_code, 404)
            reviewed = (await self.http.get(path, headers=headers)).json()
            self.assertEqual(reviewed['arguments'], {'daily_gallons': 150})
            decided = await self.http.post(path + '/decision', headers=headers, json={'decision': decision})
            self.assertEqual(decided.json()['status'], 'rejected' if decision == 'reject' else 'approved')
        self.assertEqual(self.sessions.approvals(token).goal.daily_gallons, 150)
        self.assertEqual(len(self.requests), 2)

    async def test_invalid_bodies_and_disabled_host_never_call_provider(self):
        _, headers = await self.session()
        for body in ({'text': ''}, {'text': '  '}, {'text': True}, {'text': 'é' * 4097},
                     {'text': 'hello', 'model': 'caller-model'}, {'text': 'hello', 'approved': True}):
            with self.subTest(body_type=type(body['text'])):
                result = await self.http.post('/v1/agent/turn', headers=headers, json=body)
                self.assertEqual(result.status_code, 422)
        result = await self.http.post('/v1/agent/turn', headers=headers, content='secret malformed body')
        self.assertEqual(result.status_code, 415)
        result = await self.http.post('/v1/agent/turn', headers=headers | {'Content-Type': 'application/json'},
                                      content=b'x' * 16385)
        self.assertEqual(result.status_code, 413)
        result = await self.http.post('/v1/agent/turn', headers=headers | {'Content-Type': 'application/json'},
                                      content='{"text":')
        self.assertEqual(result.status_code, 422)
        self.app.state.agent_host = None
        self.assertEqual((await self.turn(headers)).status_code, 503)
        self.assertEqual((await self.http.get('/health')).status_code, 200)
        self.assertEqual(self.requests, [])

    async def test_session_and_process_budgets_count_failed_attempts(self):
        _, headers = await self.session()
        self.reply = lambda index: response([], 'incomplete')
        for _ in range(8):
            result = await self.turn(headers)
            self.assertEqual(result.json()['status'], 'unavailable')
        self.assertEqual((await self.turn(headers)).status_code, 429)
        self.assertEqual(len(self.requests), 8)
        _, fresh = await self.session()
        self.host._total = 100
        self.assertEqual((await self.turn(fresh)).status_code, 429)
        self.assertEqual(len(self.requests), 8)

    async def test_concurrent_turns_have_session_and_global_limits(self):
        _, first = await self.session()
        _, second = await self.session()
        _, third = await self.session()
        started = asyncio.Queue()
        release = asyncio.Event()

        async def hold(index):
            started.put_nowait(index)
            await release.wait()
            return response([message('Done.')])

        self.reply = hold
        tasks = []
        try:
            tasks.append(asyncio.create_task(self.turn(first)))
            await asyncio.wait_for(started.get(), 5)
            self.assertEqual((await self.turn(first)).status_code, 409)
            tasks.append(asyncio.create_task(self.turn(second)))
            await asyncio.wait_for(started.get(), 5)
            self.assertEqual((await self.turn(third)).status_code, 429)
        finally:
            release.set()
            outcomes = await asyncio.gather(*tasks)
        self.assertTrue(all(result.status_code == 200 for result in outcomes))
        self.assertEqual((await self.turn(third)).status_code, 200)

    async def test_session_end_during_provider_request_stops_tool_and_followup(self):
        for ending in ('revoke', 'expire'):
            with self.subTest(ending=ending):
                self.now[0] = 0
                token, headers = await self.session()

                def end_session(index):
                    if ending == 'revoke':
                        self.sessions.revoke(token)
                    else:
                        self.now[0] = 3600
                    return response([call('call_goal', 'set_conservation_goal',
                                          '{"request":{"daily_gallons":150}}')])

                self.reply = end_session
                before = len(self.requests)
                self.assertEqual((await self.turn(headers)).status_code, 401)
                self.assertEqual(len(self.requests), before + 1)
                self.assertEqual(self.host._active, set())

    async def test_default_host_is_disabled_even_when_key_is_present(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-placeholder', 'OPENAI_MODEL': 'test-model'}):
            app = create_app()
            async with app.router.lifespan_context(app):
                self.assertIsNone(app.state.agent_host)

    async def test_missing_configuration_does_not_break_inference_app_startup(self):
        with patch.dict(os.environ, {'AQUAMIND_AGENT_ENABLED': '1', 'OPENAI_API_KEY': '',
                                    'OPENAI_MODEL': 'test-model'}):
            app = create_app()
            with self.assertLogs('aquamind.api', level='ERROR') as logs:
                async with app.router.lifespan_context(app):
                    self.assertIsNone(app.state.agent_host)
            self.assertIn('agent_configuration_failed', str(logs.output))
            self.assertNotIn('test-model', str(logs.output))

    async def goal_proposal(self, headers):
        self.reply = lambda index: response([
            {'id': 'rs_private', 'type': 'reasoning', 'summary': [], 'encrypted_content': 'opaque-private'},
            call('call_goal', 'set_conservation_goal', '{"request":{"daily_gallons":150}}')])
        result = await self.turn(headers, 'A private goal question')
        self.assertEqual(result.status_code, 200)
        return result.json()['pending_approval']

    async def continue_goal(self, headers, identifier):
        return await self.http.post('/v1/agent/continue', headers=headers, json={'approval_id': identifier})

    async def test_continuation_replays_only_authoritative_decision_and_is_idempotent(self):
        token, headers = await self.session()
        pending = await self.goal_proposal(headers)
        identifier = pending['approval_id']
        self.assertNotIn('opaque-private', json.dumps(pending))
        self.assertEqual((await self.continue_goal(headers, identifier)).status_code, 409)
        self.assertEqual((await self.turn(headers)).status_code, 409)
        path = '/v1/approvals/' + identifier + '/decision'
        self.assertEqual((await self.http.post(path, headers=headers, json={'decision': 'approve'})).status_code, 200)
        self.assertEqual(len(self.requests), 1)  # Decision transport never calls the model.
        self.reply = lambda index: response([message('Your temporary goal is now 150 gallons/day.')])
        result = await self.continue_goal(headers, identifier)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['status'], 'answer')
        self.assertEqual(result.json()['model_calls'], 1)
        replay = self.requests[-1]
        self.assertEqual(replay['input'][1]['encrypted_content'], 'opaque-private')
        self.assertEqual(replay['input'][-1]['call_id'], 'call_goal')
        decision = json.loads(replay['input'][-1]['output'])
        self.assertEqual(decision['status'], 'approval_resolved')
        self.assertEqual(decision['source'], 'trusted_host')
        self.assertEqual(decision['result']['status'], 'approved')
        self.assertEqual(decision['current_goal'], {'daily_gallons': 150})
        self.assertNotIn(identifier, json.dumps(replay))  # Approval IDs are not needed by the model.
        self.assertNotIn('set_conservation_goal', [tool['name'] for tool in replay['tools']])
        public = json.dumps(result.json())
        for private in (token, 'opaque-private', 'A private goal question'):
            self.assertNotIn(private, public)
        cached = await self.continue_goal(headers, identifier)
        self.assertEqual(cached.json()['answer'], result.json()['answer'])
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.host._total, 2)
        self.assertIsNone(self.host._continuations[self.sessions.approvals(token)].pause)

    async def test_continuation_cannot_accept_client_decisions_or_another_sessions_proposal(self):
        _, headers = await self.session()
        _, stranger = await self.session()
        pending = await self.goal_proposal(headers)
        identifier = pending['approval_id']
        self.assertEqual((await self.continue_goal({}, identifier)).status_code, 401)
        self.assertEqual((await self.continue_goal(stranger, identifier)).status_code, 404)
        for extra in ({'decision': 'approve'}, {'status': 'approved'}, {'history': []}, {'text': 'approved'}):
            result = await self.http.post('/v1/agent/continue', headers=headers,
                json={'approval_id': identifier, **extra})
            self.assertEqual(result.status_code, 422)
        manual = await self.http.post('/v1/goals/proposals', headers=stranger, json={'daily_gallons': 100})
        self.assertEqual((await self.continue_goal(stranger, manual.json()['approval_id'])).status_code, 404)
        self.assertEqual(len(self.requests), 1)

    async def test_rejected_expired_and_conflicting_results_are_replayed_without_new_writes(self):
        from aquamind_ml.approvals import GoalRequest
        for expected in ('rejected', 'expired', 'conflict'):
            with self.subTest(expected=expected):
                self.now[0] = 0
                token, headers = await self.session()
                pending = await self.goal_proposal(headers)
                store = self.sessions.approvals(token)
                if expected == 'expired':
                    self.now[0] = 600
                elif expected == 'conflict':
                    competing = store.propose(GoalRequest(daily_gallons=100))
                    store.decide(competing.approval_id, 'approve')
                if expected != 'expired':
                    store.decide(pending['approval_id'], 'reject' if expected == 'rejected' else 'approve')
                self.reply = lambda index: response([message('This proposal did not change your goal.')])
                result = await self.continue_goal(headers, pending['approval_id'])
                self.assertEqual(result.status_code, 200)
                replay = json.loads(self.requests[-1]['input'][-1]['output'])
                self.assertEqual(replay['result']['status'], expected)
                self.assertEqual(replay['current_goal'], {'daily_gallons': 100} if expected == 'conflict' else None)

    async def test_continuation_shares_original_model_budget_and_does_not_undo_a_decision(self):
        self.host.config = AgentConfig(model='test-model', max_model_calls=1)
        token, headers = await self.session()
        pending = await self.goal_proposal(headers)
        self.sessions.approvals(token).decide(pending['approval_id'], 'approve')
        result = await self.continue_goal(headers, pending['approval_id'])
        self.assertEqual(result.json()['status'], 'limit_reached')
        self.assertEqual(result.json()['model_calls'], 0)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.sessions.approvals(token).goal.daily_gallons, 150)

    async def test_continuation_cannot_propose_again_and_uses_remaining_call_budget(self):
        self.host.config = AgentConfig(model='test-model', max_model_calls=2)
        token, headers = await self.session()
        pending = await self.goal_proposal(headers)
        store = self.sessions.approvals(token)
        store.decide(pending['approval_id'], 'reject')
        # Provider ignores the read-only catalog. Adapter must still deny the write.
        self.reply = lambda index: response([call('call_again', 'set_conservation_goal',
                                                  '{"request":{"daily_gallons":1}}')])
        result = await self.continue_goal(headers, pending['approval_id'])
        self.assertEqual(result.json()['status'], 'limit_reached')
        self.assertEqual(result.json()['tool_trace'][0]['status'], 'error')
        self.assertIsNone(store.goal)
        self.assertEqual(len(store._entries), 1)
        self.assertEqual(len(self.requests), 2)

    async def test_interrupted_continuation_never_retries_provider_and_releases_slot(self):
        token, headers = await self.session()
        pending = await self.goal_proposal(headers)
        store = self.sessions.approvals(token)
        store.decide(pending['approval_id'], 'approve')
        started = asyncio.Event()
        release = asyncio.Event()

        async def hold(index):
            started.set()
            await release.wait()
            return response([message('Done.')])

        self.reply = hold
        task = asyncio.create_task(self.continue_goal(headers, pending['approval_id']))
        try:
            await asyncio.wait_for(started.wait(), 5)
            self.assertEqual((await self.continue_goal(headers, pending['approval_id'])).status_code, 409)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        finally:
            release.set()
            if not task.done():
                task.cancel()
        self.assertEqual((await self.continue_goal(headers, pending['approval_id'])).status_code, 503)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.host._active, set())
        self.assertIsNone(self.host._continuations[store].pause)
        self.assertEqual(store.goal.daily_gallons, 150)

    async def test_session_revocation_and_new_question_invalidate_continuation_access(self):
        token, headers = await self.session()
        pending = await self.goal_proposal(headers)
        self.sessions.approvals(token).decide(pending['approval_id'], 'reject')
        self.reply = lambda index: response([message('New independent answer.')])
        self.assertEqual((await self.turn(headers)).status_code, 200)
        self.assertEqual((await self.continue_goal(headers, pending['approval_id'])).status_code, 404)
        pending = await self.goal_proposal(headers)
        self.sessions.revoke(token)
        self.assertEqual((await self.continue_goal(headers, pending['approval_id'])).status_code, 401)

    async def test_provider_failure_is_cached_without_undoing_approval(self):
        token, headers = await self.session()
        pending = await self.goal_proposal(headers)
        store = self.sessions.approvals(token)
        store.decide(pending['approval_id'], 'approve')
        self.reply = lambda index: httpx2.Response(429, json={'error': {
            'message': 'secret provider detail', 'type': 'rate_limit_error', 'code': 'rate_limit_exceeded'}})
        result = await self.continue_goal(headers, pending['approval_id'])
        self.assertEqual(result.json()['status'], 'unavailable')
        self.assertNotIn('secret provider detail', json.dumps(result.json()))
        self.assertEqual((await self.continue_goal(headers, pending['approval_id'])).json()['status'], 'unavailable')
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(store.goal.daily_gallons, 150)
