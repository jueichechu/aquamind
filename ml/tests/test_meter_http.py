from contextlib import AsyncExitStack
import json
import os
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from aquamind_ml.api import create_app
from aquamind_ml.approvals import ApprovalSessionUnavailable
from aquamind_ml.meter_import import METER_BODY_LIMIT, MeterImportRequest, parse_meter_csv
from aquamind_ml.sessions import DemoSessions
from test_meter_import import meter_body


ENV = {'AQUAMIND_METER_IMPORT_ENABLED': '1', 'AQUAMIND_INFERENCE_ENABLED': '0',
       'AQUAMIND_AGENT_ENABLED': '0', 'AQUAMIND_DETECTOR_PATH': '',
       'AQUAMIND_PUBLIC_MODE': '0', 'AQUAMIND_RELAY_REQUIRED': '0'}


class MeterHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        env = patch.dict(os.environ, ENV)
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
        self.body = meter_body()

    async def post(self, body=None, **kwargs):
        return await self.http.post('/v1/meters/import', headers=self.headers,
            **(kwargs or {'json': body or self.body}))

    async def test_import_resolve_replace_clear_and_no_provider_or_goal_changes(self):
        self.assertIsNone((await self.http.get('/v1/meters/current', headers=self.headers)).json())
        result = await self.post()
        self.assertEqual(result.status_code, 201)
        value = result.json()
        context = value['context']
        self.assertEqual(context['origin'], 'user_provided')
        self.assertEqual(context['reading_count'], 96)
        self.assertEqual(value['total_us_gallons'], '96.000000')
        self.assertEqual(value['inference_status'], 'not_enabled_for_imported_data')
        self.assertNotIn('csv_text', value)
        self.assertNotIn('gallons', value)
        self.assertEqual(result.headers['cache-control'], 'no-store')
        self.assertEqual(result.headers['x-content-type-options'], 'nosniff')
        store = self.sessions.meters(self.token)
        self.assertEqual(len(store.resolve(context['evidence_id']).gallons), 96)
        self.assertEqual((await self.http.get('/v1/meters/current', headers=self.headers)).json(), value)
        second = (await self.post(meter_body(count=2, volume='2'))).json()
        self.assertNotEqual(second['context']['evidence_id'], context['evidence_id'])
        self.assertEqual(second['context']['household_id'], context['household_id'])
        with self.assertRaises(LookupError):
            store.resolve(context['evidence_id'])
        self.assertIsNone(self.app.state.agent_host)
        self.assertIsNone(self.app.state.detector)
        self.assertIsNone(self.sessions.approvals(self.token).goal)
        self.assertEqual(self.sessions.approvals(self.token)._entries, {})
        self.assertEqual((await self.http.delete('/v1/meters/current', headers=self.headers)).status_code, 204)
        self.assertIsNone(store.current())
        with self.assertRaises(LookupError):
            store.resolve(second['context']['evidence_id'])

    async def test_cross_session_references_and_checksums_do_not_authorize_access(self):
        imported = (await self.post()).json()['context']
        stranger_token = (await self.http.post('/v1/sessions')).json()['session_token']
        stranger = {'Authorization': 'Bearer ' + stranger_token}
        self.assertIsNone((await self.http.get('/v1/meters/current', headers=stranger)).json())
        other_store = self.sessions.meters(stranger_token)
        with self.assertRaises(LookupError):
            other_store.resolve(imported['evidence_id'])
        other = await self.http.post('/v1/meters/import', headers=stranger, json=self.body)
        self.assertEqual(other.json()['context']['dataset_sha256'], imported['dataset_sha256'])
        self.assertNotEqual(other.json()['context']['evidence_id'], imported['evidence_id'])
        self.assertNotEqual(other.json()['context']['household_id'], imported['household_id'])
        self.assertEqual((await self.http.get('/v1/meters/' + imported['evidence_id'], headers=stranger)).status_code, 404)

    async def test_authentication_before_body_or_parser_and_cached_expiry(self):
        for headers in ({}, {'Authorization': 'Bearer invalid'}, {'Cookie': 'session=' + self.token}):
            with patch('aquamind_ml.meter_http.parse_meter_csv') as parser:
                response = await self.http.post('/v1/meters/import', headers=headers, content='not-json')
                self.assertEqual(response.status_code, 401)
                parser.assert_not_called()
        for ending in ('revoke', 'expire'):
            token = (await self.http.post('/v1/sessions')).json()['session_token']
            store = self.sessions.meters(token)
            ref = store.replace(parse_meter_csv(MeterImportRequest.model_validate(self.body))).context.evidence_id
            if ending == 'revoke':
                self.sessions.revoke(token)
            else:
                self.now[0] += 3600
            for operation in (store.current, lambda: store.resolve(ref), store.clear,
                              lambda: store.replace(parse_meter_csv(MeterImportRequest.model_validate(self.body)))):
                with self.assertRaises(ApprovalSessionUnavailable):
                    operation()
            self.assertIsNone(store._entry)
            auth = {'Authorization': 'Bearer ' + token}
            self.assertEqual((await self.http.get('/v1/meters/current', headers=auth)).status_code, 401)

    async def test_ending_session_during_stream_does_not_store_or_release_data(self):
        store = self.sessions.meters(self.token)
        async def streamed():
            yield b'{'
            self.sessions.revoke(self.token)
            yield json.dumps(self.body).encode()[1:]
        result = await self.post(content=streamed())
        self.assertEqual(result.status_code, 401)
        self.assertIsNone(store._entry)
        self.assertNotIn('interval_start', result.text)

    async def test_failed_replacement_preserves_previous_data_and_invalid_requests_are_private(self):
        existing = (await self.post()).json()
        for changes in ({'consent_to_process': False}, {'volume_unit': 'kgal'},
                        {'csv_text': 'PRIVATE_METER_INPUT'}, {'household_id': 'house_forged'},
                        {'file_path': '/private/input.csv'}, {'origin': 'synthetic'},
                        {'interval_minutes': True}, {'consent_to_process': 1}):
            result = await self.post(self.body | changes)
            self.assertEqual(result.status_code, 422)
            self.assertNotIn('PRIVATE_METER_INPUT', result.text)
            self.assertEqual((await self.http.get('/v1/meters/current', headers=self.headers)).json(), existing)
        for raw in ('{"csv_text":"PRIVATE_METER_INPUT","csv_text":"second"}',
                    '{"interval_minutes": NaN}', '[' * 2000):
            result = await self.post(content=raw)
            self.assertEqual(result.status_code, 422)
            self.assertNotIn('PRIVATE_METER_INPUT', result.text)
        self.assertEqual((await self.http.post('/v1/meters/import', json=self.body,
            headers=self.headers | {'Content-Type': 'text/csv'})).status_code, 415)

    async def test_actual_streamed_byte_limit_despite_false_length(self):
        encoded = json.dumps(self.body).encode()
        self.assertEqual((await self.post(content=encoded + b' ' * (METER_BODY_LIMIT - len(encoded)))).status_code, 201)
        async def oversized():
            yield b' ' * METER_BODY_LIMIT
            yield b'x'
        result = await self.http.post('/v1/meters/import', content=oversized(),
            headers=self.headers | {'Content-Length': '1'})
        self.assertEqual(result.status_code, 413)

    async def test_logs_exclude_readings_references_and_session_tokens(self):
        with self.assertLogs('aquamind.api', level='INFO') as captured:
            result = await self.post()
        text = str(captured.output)
        for value in (self.token, 'interval_start', '2026-06-01', result.json()['context']['evidence_id'],
                      result.json()['context']['dataset_sha256'], 'csv_text'):
            self.assertNotIn(value, text)

    async def test_shutdown_clears_cached_repository_and_registry(self):
        await self.post()
        store = self.sessions.meters(self.token)
        await self.stack.aclose()
        self.assertEqual(self.sessions._sessions, {})
        self.assertIsNone(store._entry)
        with self.assertRaises(ApprovalSessionUnavailable):
            store.current()


class MeterConfigurationTests(unittest.TestCase):
    def test_default_disabled_and_invalid_flag_rejected(self):
        with patch.dict(os.environ, ENV | {'AQUAMIND_METER_IMPORT_ENABLED': '0'}), TestClient(create_app()) as client:
            self.assertEqual(client.post('/v1/meters/import', json=meter_body()).status_code, 404)
            self.assertEqual(client.get('/v1/meters/current').status_code, 404)
        with patch.dict(os.environ, ENV | {'AQUAMIND_METER_IMPORT_ENABLED': 'invalid'}):
            with self.assertRaisesRegex(ValueError, 'AQUAMIND_METER_IMPORT_ENABLED'):
                with TestClient(create_app()):
                    pass

    def test_public_admission_accepts_large_import_with_relay_and_preserves_limits(self):
        secret = 'meter-server-only-placeholder-key-' * 2
        with patch.dict(os.environ, ENV | {'AQUAMIND_PUBLIC_MODE': '1', 'AQUAMIND_RELAY_REQUIRED': '1',
                'AQUAMIND_RELAY_SECRET': secret}), TestClient(create_app()) as client:
            self.assertEqual(client.post('/v1/meters/import', json=meter_body()).status_code, 401)
            relay = {'X-AquaMind-Relay-Key': secret}
            token = client.post('/v1/sessions', headers=relay).json()['session_token']
            headers = relay | {'Authorization': 'Bearer ' + token}
            self.assertEqual(client.post('/v1/meters/import', json=meter_body(count=672), headers=headers).status_code, 201)
            self.assertEqual(client.post('/v1/meters/import', content='x' * (METER_BODY_LIMIT + 1),
                headers=headers | {'Content-Length': '1'}).status_code, 413)
            self.assertEqual(client.get('/v1/goals/current', headers=headers).json(), {'goal': None})


if __name__ == '__main__':
    unittest.main()
