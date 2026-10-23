from contextlib import AsyncExitStack
import json
import os
import unittest
from unittest.mock import patch

import httpx

from aquamind_ml.api import create_app
from aquamind_ml.bills import ManualBill, normalize_bill
from aquamind_ml.sessions import DemoSessions


class BillHttpTests(unittest.IsolatedAsyncioTestCase):
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
        self.body = {'period_start': '2026-06-01', 'period_end_exclusive': '2026-07-01',
                     'usage': '4321.123456', 'usage_unit': 'us_gallons',
                     'water_charge': '87.65', 'currency': 'USD'}

    async def post(self, **kwargs):
        return await self.http.post('/v1/bills/normalize', headers=self.headers,
                                    **(kwargs or {'json': self.body}))

    async def test_normalizes_all_units_without_model_or_storage_and_omits_sensitive_logs(self):
        self.assertIsNone(self.app.state.detector)
        self.assertIsNone(self.app.state.agent_host)
        for unit in ('us_gallons', 'ccf', 'cubic_meters', 'liters'):
            body = self.body | {'usage_unit': unit, 'usage': '1'}
            with self.assertLogs('aquamind.api', level='INFO') as logs:
                response = await self.post(json=body)
            self.assertEqual(response.status_code, 200)
            data = response.json()
            expected = normalize_bill(ManualBill.model_validate(body)).model_dump(mode='json')
            self.assertEqual(data, expected | {'request_id': response.headers['x-request-id']})
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
            for private in (self.token, body['period_start'], body['period_end_exclusive'], '87.65'):
                self.assertNotIn(private, str(logs.output))
            self.assertIsNone(data['bill']['sewer_charge'])
            self.assertIsNone(data['water_and_sewer_subtotal'])
        store = self.sessions.approvals(self.token)
        self.assertIsNone(store.goal)
        self.assertEqual(store._entries, {})
        self.assertEqual((await self.http.get('/v1/bills', headers=self.headers)).status_code, 404)
        self.assertEqual((await self.http.get('/v1/bills/normalize', headers=self.headers)).status_code, 405)
        schema = self.app.openapi()['paths']['/v1/bills/normalize']['post']['requestBody']
        self.assertTrue(schema['required'])
        self.assertIn('usage_unit', schema['content']['application/json']['schema']['properties'])

    async def test_authentication_precedes_parsing_and_normalization(self):
        for headers in ({}, {'Authorization': 'Bearer invalid'}, {'Cookie': 'session=' + self.token}):
            with patch('aquamind_ml.bill_http.normalize_bill') as normalize:
                response = await self.http.post('/v1/bills/normalize', headers=headers,
                                                content=b'private invalid JSON')
                self.assertEqual(response.status_code, 401)
                normalize.assert_not_called()
        for ending in ('expire', 'revoke'):
            token = (await self.http.post('/v1/sessions')).json()['session_token']
            if ending == 'expire':
                self.now[0] += 3600
            else:
                self.sessions.revoke(token)
            response = await self.http.post('/v1/bills/normalize',
                headers={'Authorization': 'Bearer ' + token}, json=self.body)
            self.assertEqual(response.status_code, 401)

    async def test_streamed_size_limit_uses_actual_bytes_and_accepts_boundary(self):
        encoded = json.dumps(self.body).encode()
        response = await self.post(content=encoded + b' ' * (1024 - len(encoded)))
        self.assertEqual(response.status_code, 200)

        async def oversized():
            yield b' ' * 600
            yield b' ' * 425

        with patch('aquamind_ml.bill_http.normalize_bill') as normalize:
            response = await self.http.post('/v1/bills/normalize',
                headers=self.headers | {'Content-Length': '1'}, content=oversized())
            self.assertEqual(response.status_code, 413)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            normalize.assert_not_called()

    async def test_invalid_json_fields_and_media_types_do_not_echo_inputs(self):
        for content_type in ('text/plain', 'application/jsonp', 'multipart/form-data', ''):
            response = await self.http.post('/v1/bills/normalize',
                headers=self.headers | {'Content-Type': content_type}, json=self.body)
            self.assertEqual(response.status_code, 415)
        marker = 'private-account-marker'
        duplicate = json.dumps(self.body)[:-1] + ',"usage_unit":"ccf"}'
        invalid = [b'\xff', b'', b'{', b'[]', b'null', duplicate.encode(),
                   json.dumps(self.body).replace('"4321.123456"', '1e9999999999999999999').encode(),
                   json.dumps(self.body | {'account_number': marker}).encode(),
                   json.dumps(self.body | {'period_start': marker}).encode(),
                   json.dumps(self.body | {'usage': marker}).encode(),
                   json.dumps(self.body | {'usage': True}).encode(),
                   json.dumps(self.body | {'usage_unit': 'imperial_gallons'}).encode(),
                   json.dumps(self.body | {'usage': float('nan')}).encode(),
                   json.dumps(self.body | {'period_end_exclusive': '2026-06-01'}).encode(),
                   json.dumps(self.body | {'currency': None}).encode()]
        with patch('aquamind_ml.bill_http.normalize_bill') as normalize:
            for content in invalid:
                with self.subTest(content_type=type(content)), self.assertLogs('aquamind.api', level='INFO') as logs:
                    response = await self.post(content=content)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json(), {'detail': 'Invalid bill request'})
                self.assertNotIn(marker, response.text)
                self.assertNotIn(marker, str(logs.output))
            normalize.assert_not_called()
        response = await self.http.post('/v1/bills/normalize',
            headers=self.headers | {'Content-Type': 'application/json; charset=utf-8'}, json=self.body)
        self.assertEqual(response.status_code, 200)

    async def test_session_end_while_reading_body_prevents_bill_response(self):
        encoded = json.dumps(self.body).encode()
        for ending in ('expire', 'revoke'):
            self.now[0] = 0
            token = (await self.http.post('/v1/sessions')).json()['session_token']

            async def interrupted():
                yield encoded[:20]
                if ending == 'expire':
                    self.now[0] = 3600
                else:
                    self.sessions.revoke(token)
                yield encoded[20:]

            response = await self.http.post('/v1/bills/normalize',
                headers=self.headers | {'Authorization': 'Bearer ' + token}, content=interrupted())
            self.assertEqual(response.status_code, 401)
            self.assertNotIn('4321.123456', response.text)

    async def test_no_cross_origin_access(self):
        response = await self.http.options('/v1/bills/normalize', headers={
            'Origin': 'https://untrusted.example', 'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'authorization,content-type'})
        self.assertNotIn('access-control-allow-origin', response.headers)
