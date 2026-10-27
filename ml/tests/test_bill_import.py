import asyncio
import base64
from contextlib import AsyncExitStack
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx
import httpx2
from openai import AsyncOpenAI

from aquamind_ml.agent import AgentConfig
from aquamind_ml.agent_http import AgentHost
from aquamind_ml.api import create_app
from aquamind_ml.bill_import import IMPORT_BODY_LIMIT, MAX_DOCUMENT_BYTES, IMPORT_POLICY
from aquamind_ml.sessions import DemoSessions
from test_agent import message, response


class BillImportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        env = patch.dict(os.environ, {'AQUAMIND_AGENT_ENABLED': '0', 'AQUAMIND_DETECTOR_PATH': ''})
        env.start(); self.addCleanup(env.stop)
        self.requests = []
        self.fields = dict(period_start='2026-06-01', period_end_exclusive='2026-07-01',
            usage='8.5', usage_unit='ccf', water_charge='45.12', sewer_charge=None, currency='USD')
        self.payload = {'fields': self.fields, 'warnings': []}
        self.reply = lambda: httpx2.Response(200, json=response([message(json.dumps(self.payload))]))

        async def handle(request):
            self.requests.append(json.loads(request.content))
            reply = self.reply()
            return await reply if asyncio.iscoroutine(reply) else reply

        self.stack = AsyncExitStack(); self.addAsyncCleanup(self.stack.aclose)
        provider = await self.stack.enter_async_context(AsyncOpenAI(api_key='test-placeholder',
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle))))
        self.host = AgentHost(provider, AgentConfig(model='test-model'), demo_meter_path=Path('/missing'))
        self.now = [0.0]
        self.sessions = DemoSessions(clock=lambda: self.now[0])
        self.app = create_app(sessions=self.sessions, agent_host=self.host)
        await self.stack.enter_async_context(self.app.router.lifespan_context(self.app))
        self.http = await self.stack.enter_async_context(httpx.AsyncClient(
            transport=httpx.ASGITransport(self.app), base_url='http://test'))
        self.body = dict(media_type='application/pdf',
            data_base64=base64.b64encode(b'%PDF-1.7\nprivate document content').decode(), share_with_ai=True)

    async def headers(self):
        token = (await self.http.post('/v1/sessions')).json()['session_token']
        return {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}

    async def post(self, body=None, headers=None):
        return await self.http.post('/v1/bills/import', headers=headers or await self.headers(),
                                    json=self.body if body is None else body)

    async def test_pdf_inline_no_files_api_no_tools_no_storage_no_private_logs(self):
        headers = await self.headers()
        with self.assertLogs('aquamind.api', level='INFO') as logs:
            result = await self.post(headers=headers)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['fields'], self.fields)
        self.assertTrue(result.json()['needs_review'])
        self.assertEqual(result.headers['cache-control'], 'no-store')
        self.assertEqual(result.json()['request_id'], result.headers['x-request-id'])
        request, = self.requests
        self.assertFalse(request['store'])
        self.assertEqual(request['tools'], [])
        self.assertEqual(request['instructions'], IMPORT_POLICY)
        self.assertTrue(request['text']['format']['strict'])
        document = request['input'][0]['content'][1]
        self.assertEqual(document['type'], 'input_file')
        self.assertEqual(document['filename'], 'water-report.pdf')
        self.assertEqual(document['file_data'], 'data:application/pdf;base64,' + self.body['data_base64'])
        self.assertNotIn(headers['Authorization'], json.dumps(request))
        for private in ('private document', self.body['data_base64'], '45.12', '2026-06-01'):
            self.assertNotIn(private, str(logs.output))
        self.assertEqual(self.host._continuations, {})
        self.assertFalse(self.host._active)

    async def test_image_formats_and_null_fields_remain_editable_candidates(self):
        for media, content in [('image/png', b'\x89PNG\r\n\x1a\nbytes'),
                               ('image/jpeg', b'\xff\xd8\xffbytes'),
                               ('image/webp', b'RIFF\x00\x00\x00\x00WEBPbytes')]:
            self.payload = {'fields': dict.fromkeys(self.fields), 'warnings': ['unclear_document']}
            result = await self.post(self.body | {'media_type': media,
                'data_base64': base64.b64encode(content).decode()})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()['fields'], dict.fromkeys(self.fields))
            document = self.requests[-1]['input'][0]['content'][1]
            self.assertEqual(document['type'], 'input_image')
            self.assertEqual(document['detail'], 'high')

    async def test_auth_consent_format_spoofing_and_unknown_fields_fail_before_provider(self):
        self.assertEqual((await self.post(headers={'Authorization': 'Bearer invalid'})).status_code, 401)
        for changes in [{'share_with_ai': False}, {'share_with_ai': 'true'}, {'share_with_ai': 1},
                        {'media_type': 'text/html'}, {'data_base64': 'not base64!'},
                        {'media_type': 'image/png'}, {'filename': 'private-address.pdf'},
                        {'data_base64': ''}]:
            self.assertEqual((await self.post(self.body | changes)).status_code, 422)
        missing = dict(self.body); missing.pop('share_with_ai')
        self.assertEqual((await self.post(missing)).status_code, 422)
        self.assertEqual(self.requests, [])

    async def test_stream_limits_content_type_and_duplicate_consent_fail_closed(self):
        headers = await self.headers()
        async def oversized():
            yield b' ' * IMPORT_BODY_LIMIT
            yield b'x'
        result = await self.http.post('/v1/bills/import', headers=headers, content=oversized())
        self.assertEqual(result.status_code, 413)
        body = self.body | {'data_base64': base64.b64encode(b'%PDF-' + b'x' * MAX_DOCUMENT_BYTES).decode()}
        self.assertIn((await self.post(body)).status_code, (413, 422))
        duplicate = json.dumps(self.body)[:-1] + ',"share_with_ai":false}'
        self.assertEqual((await self.http.post('/v1/bills/import', headers=headers, content=duplicate)).status_code, 422)
        self.assertEqual((await self.http.post('/v1/bills/import', headers=headers | {
            'Content-Type': 'text/plain'}, json=self.body)).status_code, 415)
        self.assertEqual(self.requests, [])

    async def test_provider_error_refusal_and_private_output_never_leak_or_retry(self):
        for reply in [httpx2.Response(500, json={'error': {'message': 'private provider data'}}),
                      httpx2.Response(200, json=response([message('private invalid document text')]))]:
            self.reply = lambda: reply
            before = len(self.requests)
            result = await self.post()
            self.assertIn(result.status_code, (502, 503))
            self.assertNotIn('private', result.text)
            self.assertEqual(len(self.requests), before + 1)
        self.payload = {'fields': self.fields | {'account': 'private'}, 'warnings': []}
        self.reply = lambda: httpx2.Response(200, json=response([message(json.dumps(self.payload))]))
        self.assertEqual((await self.post()).status_code, 502)

    async def test_revoked_session_drops_extraction_and_overlapping_requests_are_rejected(self):
        headers = await self.headers()
        entered, release = asyncio.Event(), asyncio.Event()
        async def delayed():
            entered.set(); await release.wait()
            return httpx2.Response(200, json=response([message(json.dumps(self.payload))]))
        self.reply = delayed
        pending = asyncio.create_task(self.post(headers=headers))
        await entered.wait()
        self.assertEqual((await self.post(headers=headers)).status_code, 409)
        await self.http.delete('/v1/session', headers=headers)
        release.set()
        result = await pending
        self.assertEqual(result.status_code, 401)
        self.assertNotIn('45.12', result.text)
        self.assertEqual(len(self.requests), 1)

    async def test_no_water_or_multiple_bill_and_unclear_currency_cannot_fill_charges(self):
        for warning in ['not_water_bill', 'multiple_bills']:
            self.payload = {'fields': self.fields, 'warnings': [warning]}
            result = await self.post()
            self.assertEqual(result.json()['fields'], dict.fromkeys(self.fields))
        self.payload = {'fields': self.fields | {'currency': None}, 'warnings': ['unsupported_currency']}
        result = await self.post()
        self.assertIsNone(result.json()['fields']['water_charge'])
        self.assertIsNone(result.json()['fields']['currency'])

    async def test_import_shares_paid_budget_and_exposes_explicit_consent_schema(self):
        headers = await self.headers()
        store = self.sessions.approvals(headers['Authorization'][7:])
        self.host._counts[store] = 8
        self.assertEqual((await self.post(headers=headers)).status_code, 429)
        self.assertEqual(self.requests, [])
        schema = self.app.openapi()['paths']['/v1/bills/import']['post']['requestBody']
        self.assertTrue(schema['content']['application/json']['schema']['properties']['share_with_ai']['const'])


if __name__ == '__main__':
    unittest.main()
