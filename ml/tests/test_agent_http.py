import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
import json
import os
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import httpx
import httpx2
from openai import AsyncOpenAI

from aquamind_ml.agent import AgentConfig
from aquamind_ml.agent_http import AgentHost
from aquamind_ml.api import create_app
from aquamind_ml.sessions import DemoSessions
from aquamind_ml.demo_meter import DemoMeterStore, SCENARIOS
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

    async def test_selected_scenarios_supply_matching_summary_series_and_weather(self):
        meter = DemoMeterStore()
        for scenario in sorted(SCENARIOS):
            _, headers = await self.session()
            before = len(self.requests)
            names = ['get_meter_summary', 'get_meter_series', 'get_weather_context']
            self.reply = lambda index: response([call('meter_' + str(index), names[index - before - 1], '{}')]) \
                if index - before <= 3 else response([message('Synthetic meter evidence retrieved.')])
            result = await self.http.post('/v1/agent/turn', headers=headers,
                json={'text': 'Explain the selected synthetic day.', 'scenario_id': scenario})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()['status'], 'answer')
            self.assertEqual([item['status'] for item in result.json()['tool_trace']], ['success'] * 3)
            requests = self.requests[before:]
            for name in names:
                definition = next(tool for tool in requests[0]['tools'] if tool['name'] == name)
                self.assertEqual(definition['parameters'].get('properties', {}), {})
            self.assertNotIn('detect_water_anomaly', [tool['name'] for tool in requests[0]['tools']])
            for index, name in enumerate(names):
                evidence = json.loads(requests[index + 1]['input'][-1]['output'])['result']
                self.assertEqual(evidence['source'], 'synthetic')
                self.assertEqual(evidence['scenario_id'], scenario)
                if name == 'get_meter_summary':
                    self.assertEqual(evidence, meter.summary(scenario).model_dump())
                elif name == 'get_meter_series':
                    self.assertEqual(evidence, meter.series(scenario).model_dump())
                for label in ('hasLeak', 'isAnomaly', 'fixtures', 'excessGallons'):
                    self.assertNotIn(label, evidence)

    async def test_meter_selection_requires_valid_request_and_cannot_be_overridden_by_model(self):
        _, headers = await self.session()
        for extra in ({'scenario_id': 'unknown'}, {'scenario_id': True}, {'scenario_id': {}},
                      {'scenario_id': 'normal', 'seed': 7}, {'meter_path': '/private/meter.json'},
                      {'flow_rates_gpm': [999] * 96}):
            result = await self.http.post('/v1/agent/turn', headers=headers,
                json={'text': 'Water use?', **extra})
            self.assertEqual(result.status_code, 422)
        self.assertEqual(self.requests, [])
        for selected in (False, True):
            before = len(self.requests)
            args = '{"request":{"scenario_id":"normal","seed":0}}' if selected else '{}'
            self.reply = lambda index: response([call('meter_call', 'get_meter_summary', args)]) \
                if index == before + 1 else response([message('Meter read denied.')])
            payload = {'text': 'Water use?'}
            if selected:
                payload['scenario_id'] = 'overnight-leak'
            result = await self.http.post('/v1/agent/turn', headers=headers, json=payload)
            self.assertEqual(result.json()['tool_trace'][0]['status'], 'error')
            error = json.loads(self.requests[-1]['input'][-1]['output'])
            self.assertEqual(error['error'], 'invalid_arguments' if selected else 'tool_not_allowed')

    async def test_missing_demo_snapshot_fails_selected_turn_without_provider_work(self):
        self.app.state.agent_host = AgentHost(self.provider, AgentConfig(model='test-model'),
            demo_meter_path=Path('/nonexistent/aquamind-demo-meter.json'))
        _, headers = await self.session()
        result = await self.http.post('/v1/agent/turn', headers=headers,
            json={'text': 'Water use?', 'scenario_id': 'normal'})
        self.assertEqual(result.status_code, 503)
        self.assertNotIn('/nonexistent', result.text)
        self.assertEqual(self.requests, [])
        self.assertEqual((await self.turn(headers)).status_code, 200)

    async def test_continuation_keeps_selected_context_and_new_questions_choose_independently(self):
        token, headers = await self.session()
        self.reply = lambda index: response([call('goal_call', 'set_conservation_goal',
            '{"request":{"daily_gallons":150}}')])
        original = await self.http.post('/v1/agent/turn', headers=headers,
            json={'text': 'Propose a daily goal.', 'scenario_id': 'running-toilet'})
        pending = original.json()['pending_approval']
        self.sessions.approvals(token).decide(pending['approval_id'], 'approve')
        self.reply = lambda index: response([call('followup_meter', 'get_meter_summary', '{}')]) \
            if index == 2 else response([message('Approved. Synthetic usage explained.')])
        result = await self.continue_goal(headers, pending['approval_id'])
        self.assertEqual(result.json()['status'], 'answer')
        evidence = json.loads(self.requests[-1]['input'][-1]['output'])['result']
        self.assertEqual(evidence['scenario_id'], 'running-toilet')
        self.assertNotIn('set_conservation_goal', [tool['name'] for tool in self.requests[-1]['tools']])
        self.assertEqual(self.sessions.approvals(token).goal.daily_gallons, 150)
        self.reply = lambda index: response([call('new_meter', 'get_meter_summary', '{}')]) \
            if index == 4 else response([message('New independent context.')])
        fresh = await self.http.post('/v1/agent/turn', headers=headers,
            json={'text': 'Explain usage.', 'scenario_id': 'normal'})
        self.assertEqual(fresh.json()['status'], 'answer')
        evidence = json.loads(self.requests[-1]['input'][-1]['output'])['result']
        self.assertEqual(evidence['scenario_id'], 'normal')
        self.assertEqual((await self.continue_goal(headers, pending['approval_id'])).status_code, 404)

    async def test_configured_anomaly_tool_binds_snapshot_and_continuation_without_new_writes(self):
        detector = SimpleNamespace(manifest={'threshold': 2.0}, predict=Mock(return_value=[{
            'score': 3.0, 'is_leak': True, 'model_version': 'test-frozen-detector'}]))
        self.app.state.agent_host = AgentHost(self.provider, AgentConfig(model='test-model'), detector=detector)
        token, headers = await self.session()
        self.reply = lambda index: response([call('anomaly', 'detect_water_anomaly', '{}')]) \
            if index == 1 else response([call('goal', 'set_conservation_goal', '{"request":{"daily_gallons":150}}')])
        proposed = await self.http.post('/v1/agent/turn', headers=headers,
            json={'text': 'Check the selected day and propose a goal.', 'scenario_id': 'overnight-leak'})
        self.assertEqual(proposed.json()['status'], 'approval_required')
        evidence = json.loads(self.requests[1]['input'][-1]['output'])['result']
        self.assertEqual(evidence['scenario_id'], 'overnight-leak')
        self.assertEqual(evidence['model_version'], 'test-frozen-detector')
        self.assertIn('not proof of a physical leak', evidence['interpretation'])
        window = detector.predict.call_args.args[0][0]
        self.assertEqual(list(window.flow_rates_gpm), DemoMeterStore().series('overnight-leak').flow_rates_gpm)
        self.assertEqual((window.seed, window.scenario_id, window.has_leak, window.has_anomaly),
                         (0, 'normal', False, False))
        pending = proposed.json()['pending_approval']
        store = self.sessions.approvals(token)
        self.assertIsNone(store.goal)
        store.decide(pending['approval_id'], 'reject')
        self.reply = lambda index: response([call('followup_anomaly', 'detect_water_anomaly', '{}')]) \
            if index == 3 else response([message('Rejected. Experimental anomaly evidence only.')])
        result = await self.continue_goal(headers, pending['approval_id'])
        self.assertEqual(result.json()['status'], 'answer')
        followup = json.loads(self.requests[-1]['input'][-1]['output'])['result']
        self.assertEqual(followup['scenario_id'], 'overnight-leak')
        self.assertEqual(detector.predict.call_count, 2)
        self.assertNotIn('set_conservation_goal', [tool['name'] for tool in self.requests[-1]['tools']])
        self.assertIsNone(store.goal)

    async def test_anomaly_args_cannot_override_selection_and_absent_selection_cannot_enable_tool(self):
        detector = SimpleNamespace(predict=Mock())
        self.app.state.agent_host = AgentHost(self.provider, AgentConfig(model='test-model'), detector=detector)
        _, headers = await self.session()
        for selection, args, expected in (({}, '{}', 'tool_not_allowed'),
                ({'scenario_id': 'normal'}, '{"request":{"flow_rates_gpm":[999]}}', 'invalid_arguments'),
                ({'scenario_id': 'normal'}, '{"threshold":0,"scopes":["anomaly:read"]}', 'invalid_arguments')):
            before = len(self.requests)
            self.reply = lambda index: response([call('override', 'detect_water_anomaly', args)]) \
                if index == before + 1 else response([message('No prediction confirmed.')])
            result = await self.http.post('/v1/agent/turn', headers=headers,
                json={'text': 'Check usage.', **selection})
            self.assertEqual(result.json()['tool_trace'][0]['status'], 'error')
            evidence = json.loads(self.requests[-1]['input'][-1]['output'])
            self.assertEqual(evidence['error'], expected)
        detector.predict.assert_not_called()

    async def test_model_failure_reaches_agent_as_error_without_a_prediction(self):
        detector = SimpleNamespace(predict=Mock(side_effect=RuntimeError('private detector detail')))
        self.app.state.agent_host = AgentHost(self.provider, AgentConfig(model='test-model'), detector=detector)
        _, headers = await self.session()
        self.reply = lambda index: response([call('anomaly', 'detect_water_anomaly', '{}')]) \
            if index == 1 else response([message('The anomaly check failed; no prediction was confirmed.')])
        result = await self.http.post('/v1/agent/turn', headers=headers,
            json={'text': 'Check usage.', 'scenario_id': 'normal'})
        self.assertEqual(result.json()['tool_trace'][0]['status'], 'error')
        evidence = json.loads(self.requests[-1]['input'][-1]['output'])
        self.assertEqual(evidence, {'status': 'error', 'error': 'mcp_tool_error'})
        self.assertNotIn('private detector detail', result.text)

    async def test_app_lifespan_shares_loaded_detector_and_lock_with_agent(self):
        detector, lock = object(), Lock()

        @asynccontextmanager
        async def provider_context(**kwargs):
            yield self.provider

        with patch.dict(os.environ, {'AQUAMIND_AGENT_ENABLED': '1', 'OPENAI_API_KEY': 'test-placeholder',
                                     'OPENAI_MODEL': 'test-model'}), \
                patch('aquamind_ml.api.FrozenDetector', return_value=detector) as load, \
                patch('aquamind_ml.api.Lock', return_value=lock), \
                patch('openai.AsyncOpenAI', side_effect=provider_context):
            app = create_app(Path('host-selected-detector'))
            async with app.router.lifespan_context(app):
                self.assertIs(app.state.agent_host._detector, app.state.detector)
                self.assertIs(app.state.agent_host._detector_lock, lock)
                load.assert_called_once_with(Path('host-selected-detector'))
        self.assertIsNone(app.state.agent_host)
        self.assertIsNone(app.state.detector)

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
