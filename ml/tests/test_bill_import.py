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
from aquamind_ml.bill_import import IMPORT_BODY_LIMIT, MAX_DOCUMENT_BYTES, IMPORT_POLICY, ExtractedReport
from aquamind_ml.sessions import DemoSessions
from test_agent import message, response

FIXTURES = Path(__file__).resolve().parents[2] / 'evals/fixtures/bill-import-review-v1.json'


def report_payload(fields, warnings=()):
    return {'fields': fields, 'warnings': list(warnings), 'evidence': {
        'schema_version': 1, 'reading_type': 'unknown', 'reading_type_page': None,
        'fields': {name: {'kind': 'printed' if value is not None else 'missing',
                          'page': 1 if value is not None else None} for name, value in fields.items()}}}


class BillImportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        env = patch.dict(os.environ, {'AQUAMIND_AGENT_ENABLED': '0', 'AQUAMIND_DETECTOR_PATH': ''})
        env.start(); self.addCleanup(env.stop)
        self.requests = []
        self.fields = dict(period_start='2026-06-01', period_end_exclusive='2026-07-01',
            usage='8.5', usage_unit='ccf', water_charge='45.12', sewer_charge=None, currency='USD')
        self.payload = report_payload(self.fields)
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
        self.assertEqual(result.json()['evidence'], self.payload['evidence'])
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
            self.payload = report_payload(dict.fromkeys(self.fields), ['unclear_document'])
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
        self.payload = report_payload(self.fields | {'account': 'private'})
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
            self.payload = report_payload(self.fields, [warning])
            self.payload['evidence'].update(reading_type='estimated', reading_type_page=1)
            result = await self.post()
            self.assertEqual(result.json()['fields'], dict.fromkeys(self.fields))
            self.assertEqual(result.json()['evidence']['reading_type'], 'unknown')
            self.assertTrue(all(source == {'kind': 'missing', 'page': None}
                                for source in result.json()['evidence']['fields'].values()))
        self.payload = report_payload(self.fields | {'currency': None}, ['unsupported_currency'])
        result = await self.post()
        self.assertIsNone(result.json()['fields']['water_charge'])
        self.assertIsNone(result.json()['fields']['currency'])
        self.assertEqual(result.json()['evidence']['fields']['water_charge'], {'kind': 'missing', 'page': None})

    async def test_reading_types_and_inclusive_end_sources_remain_unverified_candidates(self):
        for reading_type in ['actual', 'estimated', 'mixed', 'unknown']:
            self.payload = report_payload(self.fields)
            self.payload['evidence'].update(reading_type=reading_type,
                reading_type_page=None if reading_type == 'unknown' else 2)
            self.payload['evidence']['fields']['period_end_exclusive'] = {'kind': 'derived', 'page': 2}
            result = await self.post()
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()['evidence'], self.payload['evidence'])
            self.assertTrue(result.json()['needs_review'])

    async def test_invalid_sources_fail_closed_without_echoing_provider_data(self):
        for source in [{'kind': 'printed', 'page': 0}, {'kind': 'printed', 'page': 1001},
                       {'kind': 'printed', 'page': True}, {'kind': 'printed', 'page': '1'},
                       {'kind': 'printed', 'page': None}, {'kind': 'missing', 'page': 1},
                       {'kind': 'missing', 'page': None}, {'kind': 'derived', 'page': 1},
                       {'kind': 'verified', 'page': 1},
                       {'kind': 'printed', 'page': 1, 'quote': 'private account information'}]:
            self.payload = report_payload(self.fields)
            self.payload['evidence']['fields']['usage'] = source
            before = len(self.requests)
            result = await self.post()
            self.assertEqual(result.status_code, 502)
            self.assertNotIn('private', result.text)
            self.assertEqual(len(self.requests), before + 1)

    async def test_unknown_reading_type_and_missing_values_cannot_claim_source_evidence(self):
        for kind, page in [('actual', None), ('unknown', 1), ('verified', 1)]:
            self.payload = report_payload(self.fields)
            self.payload['evidence'].update(reading_type=kind, reading_type_page=page)
            self.assertEqual((await self.post()).status_code, 502)
        self.payload = report_payload(self.fields)
        self.payload['evidence']['fields']['sewer_charge'] = {'kind': 'printed', 'page': 1}
        self.assertEqual((await self.post()).status_code, 502)
        self.payload = report_payload(self.fields)
        self.payload['evidence']['fields']['usage'] = {'kind': 'unclear', 'page': None}
        self.assertEqual((await self.post()).status_code, 200)

    async def test_image_evidence_cannot_cite_a_second_page(self):
        self.payload = report_payload(self.fields)
        self.payload['evidence']['fields']['usage']['page'] = 2
        image = self.body | {'media_type': 'image/png',
                            'data_base64': base64.b64encode(b'\x89PNG\r\n\x1a\nbytes').decode()}
        self.assertEqual((await self.post(image)).status_code, 502)

    async def test_evidence_version_is_strict_and_missing_provider_evidence_is_rejected(self):
        for version in [True, 1.0, '1', 2]:
            self.payload = report_payload(self.fields)
            self.payload['evidence']['schema_version'] = version
            self.assertEqual((await self.post()).status_code, 502)
        self.payload = report_payload(self.fields)
        self.payload.pop('evidence')
        self.assertEqual((await self.post()).status_code, 502)

    def test_structured_output_schema_requires_every_property_and_forbids_extra_text(self):
        schema = ExtractedReport.model_json_schema()
        def inspect(node):
            if isinstance(node, dict):
                if node.get('type') == 'object':
                    self.assertFalse(node['additionalProperties'])
                    self.assertEqual(set(node['required']), set(node['properties']))
                for value in node.values():
                    inspect(value)
            elif isinstance(node, list):
                for value in node:
                    inspect(value)
        inspect(schema)

    async def test_import_shares_paid_budget_and_exposes_explicit_consent_schema(self):
        headers = await self.headers()
        store = self.sessions.approvals(headers['Authorization'][7:])
        self.host._counts[store] = 8
        self.assertEqual((await self.post(headers=headers)).status_code, 429)
        self.assertEqual(self.requests, [])
        schema = self.app.openapi()['paths']['/v1/bills/import']['post']['requestBody']
        self.assertTrue(schema['content']['application/json']['schema']['properties']['share_with_ai']['const'])

    def test_shared_review_fixtures_cover_units_formats_and_reading_types(self):
        corpus = json.loads(FIXTURES.read_text())
        self.assertEqual(corpus['schema_version'], 1)
        self.assertIs(corpus['synthetic'], True)
        cases = corpus['cases']
        self.assertEqual(len({case['id'] for case in cases}), len(cases))
        self.assertEqual({case['media_type'] for case in cases},
                         {'application/pdf', 'image/png', 'image/jpeg', 'image/webp'})
        self.assertEqual({case['extraction']['evidence']['reading_type'] for case in cases},
                         {'actual', 'estimated', 'mixed', 'unknown'})
        self.assertEqual({case['extraction']['fields']['usage_unit'] for case in cases} - {None},
                         {'ccf', 'cubic_meters', 'liters', 'us_gallons'})
        for case in cases:
            with self.subTest(case=case['id']):
                ExtractedReport.model_validate(case['extraction'])
                if 'provider_output' in case:
                    ExtractedReport.model_validate(case['provider_output'])

    async def test_shared_review_fixtures_cross_import_and_normalization_endpoints(self):
        # Signature probes exercise transport/validation, not real PDF/image decoding.
        probes = {'application/pdf': b'%PDF-1.7\nSYNTHETIC_PRIVATE_SOURCE_CONTENT',
                  'image/png': b'\x89PNG\r\n\x1a\nSYNTHETIC_PRIVATE_SOURCE_CONTENT',
                  'image/jpeg': b'\xff\xd8\xffSYNTHETIC_PRIVATE_SOURCE_CONTENT',
                  'image/webp': b'RIFF\x00\x00\x00\x00WEBPSYNTHETIC_PRIVATE_SOURCE_CONTENT'}
        for case in json.loads(FIXTURES.read_text())['cases']:
            with self.subTest(case=case['id']):
                headers = await self.headers()
                body = {'media_type': case['media_type'], 'share_with_ai': True,
                        'data_base64': base64.b64encode(probes[case['media_type']]).decode()}
                self.payload = case.get('provider_output', case['extraction'])
                before = len(self.requests)
                with self.assertLogs('aquamind.api', level='INFO') as logs:
                    imported = await self.post(body, headers)
                    self.assertEqual(imported.status_code, 200)
                    expected = case['extraction'] | {'source': 'document_import', 'needs_review': True,
                                                     'request_id': imported.headers['x-request-id']}
                    self.assertEqual(imported.json(), expected)
                    fields = imported.json()['fields']
                    if case['review_edits'] or case['normalized'] is None:
                        rejected = await self.http.post('/v1/bills/normalize', headers=headers, json=fields)
                        self.assertEqual(rejected.status_code, 422)
                    if case['normalized'] is not None:
                        reviewed = fields | case['review_edits']
                        normalized = await self.http.post('/v1/bills/normalize', headers=headers, json=reviewed)
                        self.assertEqual(normalized.status_code, 200)
                        self.assertEqual({key: normalized.json()[key] for key in case['normalized']},
                                         case['normalized'])
                        self.assertEqual(normalized.json()['source'], 'manual_entry')
                        self.assertEqual(normalized.json()['evidence_level'], 'bill_only')
                for private in ('SYNTHETIC_PRIVATE_SOURCE_CONTENT', body['data_base64'], headers['Authorization']):
                    self.assertNotIn(private, str(logs.output))
                # Normalization never makes another provider request.
                self.assertEqual(len(self.requests), before + 1)


if __name__ == '__main__':
    unittest.main()
