from contextlib import AsyncExitStack
import json
import os
import unittest
from unittest.mock import patch

import httpx

from aquamind_ml.api import create_app
from aquamind_ml.approvals import GoalRequest
from aquamind_ml.bill_http import BILL_COMPARISON_BODY_LIMIT
from aquamind_ml.sessions import DemoSessions


class BillComparisonHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        env = patch.dict(os.environ, {'AQUAMIND_AGENT_ENABLED': '0', 'AQUAMIND_DETECTOR_PATH': ''})
        env.start()
        self.addCleanup(env.stop)
        self.now = [0.0]
        self.sessions = DemoSessions(clock=lambda: self.now[0])
        self.app = create_app(sessions=self.sessions)
        self.stack = AsyncExitStack()
        self.addAsyncCleanup(self.stack.aclose)
        await self.stack.enter_async_context(self.app.router.lifespan_context(self.app))
        self.http = await self.stack.enter_async_context(httpx.AsyncClient(
            transport=httpx.ASGITransport(self.app), base_url='http://test'))
        self.token = (await self.http.post('/v1/sessions')).json()['session_token']
        self.headers = {'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'}
        # Latest first deliberately; baseline covers leap-year January/February,
        # and March is a gap rather than 31 assumed zero-consumption days.
        self.body = {'bills': [
            {'period_start': '2024-04-01', 'period_end_exclusive': '2024-05-01',
             'usage': '6000', 'usage_unit': 'us_gallons',
             'water_charge': '0', 'sewer_charge': '0', 'currency': 'USD'},
            {'period_start': '2024-01-01', 'period_end_exclusive': '2024-02-01',
             'usage': '3100', 'usage_unit': 'us_gallons', 'water_charge': '12.34', 'currency': 'USD'},
            {'period_start': '2024-02-01', 'period_end_exclusive': '2024-03-01',
             'usage': '21955.388347', 'usage_unit': 'liters'},
        ]}

    async def post(self, **kwargs):
        return await self.http.post('/v1/bills/compare', headers=self.headers,
                                    **(kwargs or {'json': self.body}))

    async def test_weighted_comparison_preserves_entries_and_privacy_without_agent(self):
        self.assertIsNone(self.app.state.detector)
        self.assertIsNone(self.app.state.agent_host)
        with self.assertLogs('aquamind.api', level='INFO') as logs:
            response = await self.post()
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual((result['source'], result['evidence_level'], result['confidence']),
                         ('manual_entry', 'historical_bills', 'limited'))
        self.assertEqual(result['request_id'], response.headers['x-request-id'])
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
        for key, expected in {
            'covered_days': 90, 'gap_days': 31, 'baseline_bill_count': 2,
            'baseline_billing_days': 60, 'baseline_us_gallons_per_day': '148.333333',
            'latest_us_gallons_per_day_change': '51.666667', 'latest_percent_change': '34.83',
        }.items():
            self.assertEqual(result[key], expected)
        self.assertEqual([item['bill']['period_start'] for item in result['bills']],
                         ['2024-01-01', '2024-02-01', '2024-04-01'])
        self.assertEqual(result['bills'][1]['bill']['usage_unit'], 'liters')
        self.assertEqual(result['bills'][1]['bill']['usage'], '21955.388347')
        self.assertIsNone(result['bills'][0]['bill']['sewer_charge'])
        self.assertIsNone(result['bills'][0]['water_and_sewer_subtotal'])
        self.assertEqual(result['bills'][-1]['water_and_sewer_subtotal'], '0.00')
        self.assertIn('same household', ' '.join(result['limitations']))
        for private in (self.token, '2024-04-01', '21955.388347', '12.34'):
            self.assertNotIn(private, str(logs.output))
        store = self.sessions.approvals(self.token)
        self.assertIsNone(store.goal)
        self.assertEqual(store._entries, {})
        self.assertEqual((await self.http.get('/v1/bills', headers=self.headers)).status_code, 404)

    async def test_zero_baseline_stays_null_and_requests_do_not_retain_history(self):
        bills = self.body['bills'][1:]
        bills = [bills[0] | {'usage': '0'}, bills[1] | {'usage': '0'}]
        response = await self.post(json={'bills': bills})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()['latest_percent_change'])
        self.assertEqual(response.json()['latest_us_gallons_per_day_change'], '0.000000')
        other = (await self.http.post('/v1/sessions')).json()['session_token']
        response = await self.http.post('/v1/bills/compare',
            headers=self.headers | {'Authorization': 'Bearer ' + other}, json={'bills': bills[:1]})
        self.assertEqual(response.status_code, 422)
        self.assertEqual((await self.post()).json()['baseline_bill_count'], 2)

    async def test_comparison_preserves_existing_goal_and_pending_approval(self):
        store = self.sessions.approvals(self.token)
        goal = store.propose(GoalRequest(daily_gallons=150.0))
        store.decide(goal.approval_id, 'approve')
        pending = store.propose(GoalRequest(daily_gallons=125.0))
        response = await self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(store.goal.daily_gallons, 150.0)
        self.assertEqual(store.review(pending.approval_id), pending)
        self.assertEqual(len(store._entries), 2)

    async def test_authentication_precedes_body_read_and_calculation(self):
        with patch('aquamind_ml.bill_http._read_bill_json') as read, \
                patch('aquamind_ml.bill_http.compare_bills') as compare:
            for headers in ({}, {'Authorization': 'Bearer invalid'}, {'Cookie': 'session=' + self.token}):
                response = await self.http.post('/v1/bills/compare', headers=headers, content=b'not JSON')
                self.assertEqual(response.status_code, 401)
            read.assert_not_called()
            compare.assert_not_called()
        for ending in ('expire', 'revoke'):
            self.now[0] = 0
            token = self.sessions.create()
            if ending == 'expire':
                self.now[0] = 3600
            else:
                self.sessions.revoke(token)
            response = await self.http.post('/v1/bills/compare',
                headers=self.headers | {'Authorization': 'Bearer ' + token}, json=self.body)
            self.assertEqual(response.status_code, 401)

    async def test_streamed_body_limit_ignores_declared_length_and_accepts_boundary(self):
        bills = [{'period_start': f'2026-01-{day:02}',
                  'period_end_exclusive': f'2026-01-{day + 1:02}',
                  'usage': '1', 'usage_unit': 'us_gallons'} for day in range(1, 13)]
        response = await self.post(json={'bills': bills})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['bills']), 12)
        encoded = json.dumps(self.body).encode()
        response = await self.post(content=encoded + b' ' * (BILL_COMPARISON_BODY_LIMIT - len(encoded)))
        self.assertEqual(response.status_code, 200)

        async def oversized():
            yield b' ' * BILL_COMPARISON_BODY_LIMIT
            yield b' '

        with patch('aquamind_ml.bill_http.compare_bills') as compare:
            response = await self.http.post('/v1/bills/compare',
                headers=self.headers | {'Content-Length': '1'}, content=oversized())
            self.assertEqual(response.status_code, 413)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            compare.assert_not_called()

    async def test_invalid_input_is_rejected_without_echoing_or_logging_values(self):
        encoded = json.dumps(self.body)
        first = self.body['bills'][0]
        invalid = [b'\xff', b'', b'{', b'[]', b'null',
            (encoded[:-1] + ',"bills":[]}').encode(),
            encoded.replace('"usage": "6000"', '"usage":"6000","usage":"1"').encode(),
            encoded.replace('"6000"', 'NaN').encode(),
            encoded.replace('"6000"', 'Infinity').encode(),
            encoded.replace('"6000"', '1e9999999999999999999').encode(),
            b'[' * 1100 + b']' * 1100,
            *[json.dumps(value).encode() for value in (
                {'bills': []}, {'bills': [first]}, {'bills': [first] * 13},
                {'bills': [first, first]}, {'bills': [first, first | {'period_start': '2024-04-02'}]},
                self.body | {'baseline_us_gallons_per_day': 'private-marker'},
                {'bills': [first, first | {'account_number': 'private-marker'}]},
                {'bills': [first, first | {'usage': True}]},
                {'bills': [first, first | {'usage_unit': 'imperial_gallons'}]},
                {'bills': [first, first | {'period_start': 'private-marker'}]},
            )]]
        with patch('aquamind_ml.bill_http.compare_bills') as compare:
            for content in invalid:
                with self.subTest(content=content[:60]), self.assertLogs('aquamind.api', level='INFO') as logs:
                    response = await self.post(content=content)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json(), {'detail': 'Invalid bill comparison request'})
                self.assertNotIn('private-marker', response.text)
                self.assertNotIn('private-marker', str(logs.output))
            compare.assert_not_called()

    async def test_session_end_during_body_read_prevents_calculation(self):
        encoded = json.dumps(self.body).encode()
        for ending in ('expire', 'revoke'):
            self.now[0] = 0
            token = self.sessions.create()

            async def interrupted():
                yield encoded[:20]
                if ending == 'expire':
                    self.now[0] = 3600
                else:
                    self.sessions.revoke(token)
                yield encoded[20:]

            with patch('aquamind_ml.bill_http.compare_bills') as compare:
                response = await self.http.post('/v1/bills/compare',
                    headers=self.headers | {'Authorization': 'Bearer ' + token}, content=interrupted())
                self.assertEqual(response.status_code, 401)
                self.assertNotIn('21955.388347', response.text)
                compare.assert_not_called()

    async def test_session_end_during_calculation_prevents_data_release(self):
        from aquamind_ml.bills import compare_bills
        for ending in ('expire', 'revoke'):
            self.now[0] = 0
            token = self.sessions.create()

            def interrupted(entries):
                result = compare_bills(entries)
                if ending == 'expire':
                    self.now[0] = 3600
                else:
                    self.sessions.revoke(token)
                return result

            with patch('aquamind_ml.bill_http.compare_bills', side_effect=interrupted):
                response = await self.http.post('/v1/bills/compare',
                    headers=self.headers | {'Authorization': 'Bearer ' + token}, json=self.body)
            self.assertEqual(response.status_code, 401)
            self.assertNotIn('21955.388347', response.text)

    async def test_media_types_methods_openapi_and_cross_origin_boundaries(self):
        for content_type in ('text/plain', 'application/jsonp', 'multipart/form-data', ''):
            response = await self.http.post('/v1/bills/compare',
                headers=self.headers | {'Content-Type': content_type}, json=self.body)
            self.assertEqual(response.status_code, 415)
        response = await self.http.post('/v1/bills/compare',
            headers=self.headers | {'Content-Type': 'application/json; charset=utf-8'}, json=self.body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual((await self.http.get('/v1/bills/compare', headers=self.headers)).status_code, 405)
        response = await self.http.options('/v1/bills/compare', headers={
            'Origin': 'https://untrusted.example', 'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'authorization,content-type'})
        self.assertNotIn('access-control-allow-origin', response.headers)
        document = self.app.openapi()
        schema = document['paths']['/v1/bills/compare']['post']['requestBody']
        self.assertTrue(schema['required'])
        bills = schema['content']['application/json']['schema']['properties']['bills']
        self.assertEqual((bills['minItems'], bills['maxItems']), (2, 12))
        self.assertEqual(bills['items']['$ref'], '#/components/schemas/ManualBill')
        self.assertIn('usage_unit', document['components']['schemas']['ManualBill']['properties'])
        self.assertIn('BillComparisonResponse', document['components']['schemas'])
