import asyncio
from contextlib import AsyncExitStack
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx
import httpx2
from openai import AsyncOpenAI

from aquamind_ml.agent import AgentConfig, BILL_POLICY, POLICY
from aquamind_ml.agent_http import AgentHost
from aquamind_ml.api import create_app
from aquamind_ml.sessions import DemoSessions
from test_agent import call, message, response


class BillAgentHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        env = patch.dict(os.environ, {'AQUAMIND_AGENT_ENABLED': '0', 'AQUAMIND_DETECTOR_PATH': ''})
        env.start(); self.addCleanup(env.stop)
        self.requests = []
        self.reply = lambda index: response([message('One unverified bill; more evidence is needed.')])

        async def handle(request):
            self.requests.append(json.loads(request.content))
            answer = self.reply(len(self.requests))
            if asyncio.iscoroutine(answer):
                answer = await answer
            return httpx2.Response(200, json=answer)

        self.stack = AsyncExitStack(); self.addAsyncCleanup(self.stack.aclose)
        provider = await self.stack.enter_async_context(AsyncOpenAI(api_key='test-placeholder',
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle))))
        self.host = AgentHost(provider, AgentConfig(model='test-model'), demo_meter_path=Path('/unavailable'))
        self.now = [0.0]
        self.sessions = DemoSessions(clock=lambda: self.now[0])
        self.app = create_app(sessions=self.sessions, agent_host=self.host)
        await self.stack.enter_async_context(self.app.router.lifespan_context(self.app))
        self.http = await self.stack.enter_async_context(httpx.AsyncClient(
            transport=httpx.ASGITransport(self.app), base_url='http://test'))
        self.bill = {'period_start': '2026-06-01', 'period_end_exclusive': '2026-07-01',
                     'usage': '8.5', 'usage_unit': 'ccf', 'water_charge': '45.12', 'currency': 'USD'}
        self.body = {'text': 'A private bill question', 'bill': self.bill,
                     'is_example': False, 'share_with_ai': True}

    async def session(self):
        token = (await self.http.post('/v1/sessions')).json()['session_token']
        return token, {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}

    async def post(self, headers, body=None):
        return await self.http.post('/v1/agent/bill', headers=headers, json=self.body if body is None else body)

    async def test_consent_recomputed_evidence_no_tools_or_retained_bill_and_private_logs(self):
        token, headers = await self.session()
        with self.assertLogs('aquamind.api', level='INFO') as logs:
            result = await self.post(headers)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['status'], 'answer')
        self.assertEqual(result.json()['model_calls'], 1)
        self.assertEqual(result.json()['tool_trace'], [])
        self.assertIsNone(result.json()['pending_approval'])
        self.assertEqual(result.headers['cache-control'], 'no-store')
        self.assertEqual(result.json()['request_id'], result.headers['x-request-id'])
        request = self.requests[0]
        self.assertEqual(request['instructions'], POLICY + BILL_POLICY)
        self.assertEqual(request['tools'], [])
        self.assertFalse(request['store'])
        self.assertEqual(request['input'][0]['role'], 'user')
        context = json.loads(request['input'][0]['content'])
        evidence = context['bill_evidence']
        self.assertFalse(context['is_example'])
        self.assertEqual(evidence['billing_days'], 30)
        self.assertEqual(evidence['total_us_gallons'], '6358.441558')
        self.assertEqual(evidence['us_gallons_per_day'], '211.948052')
        self.assertIsNone(evidence['bill']['sewer_charge'])
        self.assertIsNone(evidence['water_and_sewer_subtotal'])
        self.assertEqual((evidence['source'], evidence['evidence_level'], evidence['confidence']),
                         ('manual_entry', 'bill_only', 'limited'))
        for private in (token, self.body['text'], self.bill['period_start'], '45.12', '6358.441558'):
            self.assertNotIn(private, str(logs.output))
            self.assertNotIn(private, request['instructions'])
            self.assertNotIn(private, json.dumps(result.json()))
        self.assertNotIn(token, json.dumps(request))
        store = self.sessions.approvals(token)
        self.assertIsNone(store.goal)
        self.assertEqual(store._entries, {})
        self.assertNotIn(store, self.host._continuations)
        schema = self.app.openapi()['paths']['/v1/agent/bill']['post']['requestBody']
        self.assertTrue(schema['required'])
        properties = schema['content']['application/json']['schema']['properties']
        self.assertTrue(properties['share_with_ai']['const'])
        self.assertEqual(properties['bill']['properties']['usage_unit']['enum'],
                         ['us_gallons', 'ccf', 'cubic_meters', 'liters'])
        self.assertNotIn('$ref', json.dumps(schema))

    async def test_example_zero_charges_and_new_independent_context(self):
        _, headers = await self.session()
        body = self.body | {'is_example': True, 'bill': self.bill | {
            'usage': '0', 'water_charge': '0', 'sewer_charge': '0'}}
        self.assertEqual((await self.post(headers, body)).status_code, 200)
        context = json.loads(self.requests[0]['input'][0]['content'])
        self.assertTrue(context['is_example'])
        self.assertEqual(context['bill_evidence']['water_and_sewer_subtotal'], '0.00')
        self.assertEqual(context['bill_evidence']['us_gallons_per_day'], '0.000000')
        self.assertEqual((await self.http.post('/v1/agent/turn', headers=headers,
            json={'text': 'Explain available utility assumptions.'})).status_code, 200)
        self.assertNotIn('bill_evidence', json.dumps(self.requests[-1]))
        self.assertEqual(self.requests[-1]['instructions'], POLICY)
        self.assertIn('get_utility_rate', [tool['name'] for tool in self.requests[-1]['tools']])

    async def test_auth_consent_schema_and_mixed_context_fail_before_provider_work(self):
        self.assertEqual((await self.post({})).status_code, 401)
        token, headers = await self.session()
        self.assertEqual((await self.post({'Cookie': 'session=' + token})).status_code, 401)
        invalid = [self.body | {'share_with_ai': value} for value in (False, None, 'true', 1)]
        invalid += [{key: value for key, value in self.body.items() if key != 'share_with_ai'},
                    self.body | {'is_example': 'false'}, self.body | {'scenario_id': 'normal'},
                    self.body | {'tools': []}, self.body | {'bill': self.bill | {'total_us_gallons': '1'}},
                    self.body | {'bill': self.bill | {'account_number': 'private account'}},
                    self.body | {'bill': self.bill | {'usage_unit': 'gallons'}},
                    self.body | {'bill': self.bill | {'period_end_exclusive': '2026-06-01'}},
                    self.body | {'text': 'é' * 4097}]
        for body in invalid:
            result = await self.post(headers, body)
            self.assertEqual(result.status_code, 422)
            self.assertEqual(result.json(), {'detail': 'Invalid agent request'})
        duplicate = json.dumps(self.body)[:-1] + ',"share_with_ai":false,"share_with_ai":true}'
        self.assertEqual((await self.http.post('/v1/agent/bill', headers=headers, content=duplicate)).status_code, 422)
        self.assertEqual((await self.http.post('/v1/agent/bill', headers=headers,
            content=json.dumps(self.body).replace('"8.5"', '1e9999999999999999999'))).status_code, 422)
        self.assertEqual((await self.http.post('/v1/agent/bill', headers=headers, content=' ' * 16385)).status_code, 413)
        self.assertEqual((await self.http.post('/v1/agent/bill', headers=headers | {'Content-Type': 'text/plain'},
            content=json.dumps(self.body))).status_code, 415)
        self.assertEqual(self.requests, [])
        # The shared parser also rejects ambiguous duplicate keys on ordinary turns.
        self.assertEqual((await self.http.post('/v1/agent/turn', headers=headers,
            content='{"text":"first","text":"second"}')).status_code, 422)

    async def test_numeric_json_precision_is_preserved(self):
        _, headers = await self.session()
        body = self.body | {'bill': self.bill | {'usage': '900000.123456', 'usage_unit': 'us_gallons'}}
        result = await self.http.post('/v1/agent/bill', headers=headers,
            content=json.dumps(body).replace('"900000.123456"', '900000.123456'))
        self.assertEqual(result.status_code, 200)
        evidence = json.loads(self.requests[0]['input'][0]['content'])['bill_evidence']
        self.assertEqual(evidence['bill']['usage'], '900000.123456')
        self.assertEqual(evidence['total_us_gallons'], '900000.123456')

    async def test_forged_tool_calls_cannot_read_demo_data_or_create_goals(self):
        for name in ('get_meter_summary', 'get_weather_context', 'estimate_water_cost',
                     'detect_water_anomaly', 'set_conservation_goal'):
            token, headers = await self.session()
            before = len(self.requests)
            self.reply = lambda index: response([call('forged', name, '{}')])
            result = await self.post(headers)
            self.assertEqual(result.json()['status'], 'limit_reached')
            self.assertEqual(result.json()['answer'], '')
            self.assertEqual(result.json()['tool_trace'][0]['status'], 'error')
            self.assertEqual(len(self.requests), before + 1)
            self.assertIsNone(self.sessions.approvals(token).goal)
            self.assertEqual(self.sessions.approvals(token)._entries, {})

    async def test_session_end_during_provider_work_prevents_answer_release(self):
        for ending in ('expire', 'revoke'):
            self.now[0] = 0
            token, headers = await self.session()
            started, finish = asyncio.Event(), asyncio.Event()

            async def delayed(index):
                started.set(); await finish.wait()
                return response([message('Private completed bill answer')])

            self.reply = delayed
            task = asyncio.create_task(self.post(headers))
            await asyncio.wait_for(started.wait(), 2)
            self.assertEqual((await self.post(headers)).status_code, 409)
            if ending == 'expire': self.now[0] = 3600
            else: self.sessions.revoke(token)
            finish.set()
            result = await task
            self.assertEqual(result.status_code, 401)
            self.assertNotIn('Private completed', result.text)

    async def test_shared_attempt_budget_and_no_cross_origin_access(self):
        _, headers = await self.session()
        for _ in range(8):
            self.assertEqual((await self.post(headers)).status_code, 200)
        self.assertEqual((await self.post(headers)).status_code, 429)
        self.assertEqual(len(self.requests), 8)
        result = await self.http.options('/v1/agent/bill', headers={'Origin': 'https://untrusted.example',
            'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'authorization,content-type'})
        self.assertNotIn('access-control-allow-origin', result.headers)

    async def test_bill_question_preserves_pending_goal_checkpoint(self):
        token, headers = await self.session()
        self.reply = lambda index: response([call('goal', 'set_conservation_goal',
            '{"request":{"daily_gallons":150}}')])
        result = await self.http.post('/v1/agent/turn', headers=headers, json={'text': 'Propose a goal.'})
        pending = result.json()['pending_approval']
        self.assertEqual((await self.post(headers)).status_code, 409)
        store = self.sessions.approvals(token)
        self.assertEqual(self.host._continuations[store].approval_id, pending['approval_id'])
        self.assertEqual(store.review(pending['approval_id']).status, 'approval_required')
        self.assertEqual(len(self.requests), 1)

    async def test_disabled_agent_keeps_stateless_bill_calculation_available(self):
        _, headers = await self.session()
        self.app.state.agent_host = None
        self.assertEqual((await self.post(headers)).status_code, 503)
        calculated = await self.http.post('/v1/bills/normalize', headers=headers, json=self.bill)
        self.assertEqual(calculated.status_code, 200)
        self.assertEqual(calculated.json()['us_gallons_per_day'], '211.948052')
        self.assertEqual(self.requests, [])
