import asyncio
from contextlib import contextmanager
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import httpx

from aquamind_ml.web import create_web_app, readiness_response
from aquamind_ml.meter_import import METER_BODY_LIMIT
from test_meter_import import meter_body


ENV = {'AQUAMIND_INFERENCE_ENABLED': '0', 'AQUAMIND_DETECTOR_PATH': '',
       'AQUAMIND_AGENT_ENABLED': '0', 'AQUAMIND_PUBLIC_MODE': '1',
       'AQUAMIND_RELAY_REQUIRED': '1', 'AQUAMIND_RELAY_SECRET': 'web-test-server-only-key-' * 2}
PREFIX = '/api/aquamind/'
BILL = {'period_start': '2026-06-01', 'period_end_exclusive': '2026-07-01',
        'usage': '8.5', 'usage_unit': 'ccf'}


@contextmanager
def site():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for page in ('index', 'analyze', 'compare', 'demo', '404'):
            (root / (page + '.html')).write_text('<html>' + page + '</html>')
        (root / 'analyze.txt').write_text('static navigation payload')
        (root / 'asset.js').write_text('console.log("asset");')
        yield root


class WebsiteTests(unittest.TestCase):
    def test_opt_in_meter_import_through_actual_same_origin_relay(self):
        with site() as root, patch.dict(os.environ, ENV | {'AQUAMIND_METER_IMPORT_ENABLED': '1'}), TestClient(create_web_app(root)) as client:
            path = PREFIX + 'v1/meters/'
            self.assertEqual(client.post(path + 'import', json=meter_body()).status_code, 401)
            token = client.post(PREFIX + 'v1/sessions', json={}).json()['session_token']
            headers = {'Authorization': 'Bearer ' + token, 'X-AquaMind-Relay-Key': 'forged-browser-key'}
            response = client.post(path + 'import', json=meter_body(count=672), headers=headers)
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.json()['context']['reading_count'], 672)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertEqual(client.get(path + 'current', headers=headers).json(), response.json())
            self.assertEqual(client.get(path + 'import', headers=headers).status_code, 404)
            self.assertEqual(client.post(path + 'current', headers=headers).status_code, 404)
            self.assertEqual(client.post(path + 'import', content='x' * (METER_BODY_LIMIT + 1),
                headers=headers | {'Content-Length': '1'}).status_code, 413)
            self.assertEqual(client.delete(path + 'current', headers=headers).status_code, 204)
            self.assertIsNone(client.get(path + 'current', headers=headers).json())
            self.assertEqual(client.delete(PREFIX + 'v1/session', headers=headers).status_code, 204)

    def test_pages_assets_and_raw_api_isolation(self):
        with site() as root, patch.dict(os.environ, ENV), TestClient(create_web_app(root)) as client:
            for path, expected in (('/', 'index'), ('/analyze', 'analyze'),
                    ('/compare', 'compare'), ('/demo', 'demo'), ('/analyze.txt', 'navigation'),
                    ('/asset.js', 'asset')):
                result = client.get(path)
                self.assertEqual(result.status_code, 200, path)
                self.assertIn(expected, result.text)
            for path in ('/v1/sessions', '/ready', '/docs', '/openapi.json',
                         '/.env.local', '/%2e%2e/AGENTS.md', '/missing'):
                self.assertEqual(client.get(path).status_code, 404, path)
            health = client.get('/api/health')
            self.assertEqual(health.json(), {'status': 'ok'})
            self.assertEqual(health.headers['cache-control'], 'no-store')

    def test_existing_session_calculation_and_revocation_contracts(self):
        with site() as root, patch.dict(os.environ, ENV), TestClient(create_web_app(root)) as client:
            for forbidden in ('ready', 'v1/anomaly/predict', 'v1/bills/readiness/extra'):
                self.assertEqual(client.post(PREFIX + forbidden, json={}).status_code, 404)
            self.assertEqual(client.post(PREFIX + 'v1/bills/readiness').status_code, 404)
            self.assertEqual(client.post(PREFIX + 'v1/bills/normalize', json=BILL).status_code, 401)
            created = client.post(PREFIX + 'v1/sessions', json={}, headers={
                'X-AquaMind-Relay-Key': 'browser-key', 'cookie': 'private=value'})
            self.assertEqual(created.status_code, 201)
            self.assertNotIn(ENV['AQUAMIND_RELAY_SECRET'], created.text)
            headers = {'Authorization': 'Bearer ' + created.json()['session_token']}
            result = client.post(PREFIX + 'v1/bills/normalize', json=BILL, headers=headers)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()['us_gallons_per_day'], '211.948052')
            self.assertEqual(result.headers['x-content-type-options'], 'nosniff')
            duplicate = [('Authorization', headers['Authorization']), ('Authorization', 'Bearer invalid')]
            self.assertEqual(client.get(PREFIX + 'v1/goals/current', headers=duplicate).status_code, 401)
            self.assertEqual(client.get(PREFIX + 'v1/goals/current', headers=headers).json(), {'goal': None})
            self.assertEqual(client.delete(PREFIX + 'v1/session', headers=headers).status_code, 204)
            self.assertEqual(client.get(PREFIX + 'v1/goals/current', headers=headers).status_code, 401)

    def test_actual_bytes_and_comparison_body_allowance(self):
        with site() as root, patch.dict(os.environ, ENV), TestClient(create_web_app(root)) as client:
            token = client.post(PREFIX + 'v1/sessions', json={}).json()['session_token']
            headers = {'Authorization': 'Bearer ' + token}
            # This fits the relay, then the actual endpoint rejects its schema.
            self.assertEqual(client.post(PREFIX + 'v1/bills/compare',
                content=' ' * 2048, headers=headers).status_code, 422)
            for route, limit in (('v1/bills/normalize', 1024), ('v1/bills/compare', 12288),
                                 ('v1/agent/bill', 16384)):
                result = client.post(PREFIX + route, content=(' ' * (limit - 1) + 'é').encode(),
                    headers=headers | {'Content-Length': '1'})
                self.assertEqual(result.status_code, 413)
                self.assertEqual(result.json(), {'detail': 'Request too large'})

    def test_startup_fails_before_serving_if_enabled_feature_is_unavailable(self):
        upstream = FastAPI()

        @upstream.get('/health')
        async def health():
            return {'status': 'ok'}

        with site() as root, patch.dict(os.environ, ENV | {'AQUAMIND_INFERENCE_ENABLED': '1'}):
            with self.assertRaisesRegex(RuntimeError, 'Website backend startup unavailable'):
                with TestClient(create_web_app(root, api=upstream)):
                    self.fail('Unready website must not start')
        for key, value in (('AQUAMIND_PUBLIC_MODE', 'invalid'), ('AQUAMIND_RELAY_SECRET', 'short')):
            with site() as root, patch.dict(os.environ, ENV | {key: value}):
                with self.assertRaises(ValueError):
                    with TestClient(create_web_app(root)):
                        self.fail('Invalid configuration must not serve the page')

    def test_adapter_forwards_only_host_credentials_and_preserves_cooldowns(self):
        upstream = FastAPI()
        seen = []

        @upstream.get('/health')
        async def health():
            return {'status': 'ok'}

        @upstream.post('/v1/sessions')
        async def session(request: Request):
            seen.append(dict(request.headers))
            from fastapi.responses import JSONResponse
            return JSONResponse({'detail': 'Busy'}, status_code=429, headers={'Retry-After': '60'})

        with site() as root, patch.dict(os.environ, ENV), TestClient(create_web_app(root, api=upstream)) as client:
            result = client.post(PREFIX + 'v1/sessions', json={}, headers={
                'X-AquaMind-Relay-Key': 'browser-key', 'cookie': 'secret=value', 'X-Forwarded-For': 'untrusted'})
            self.assertEqual(result.status_code, 429)
            self.assertEqual(result.headers['retry-after'], '60')
            self.assertEqual(seen[0]['x-aquamind-relay-key'], ENV['AQUAMIND_RELAY_SECRET'])
            self.assertNotIn('cookie', seen[0])
            self.assertNotIn('x-forwarded-for', seen[0])

    def test_paid_failure_is_sanitized_without_retry(self):
        with site() as root, patch.dict(os.environ, ENV):
            app = create_web_app(root)
            with TestClient(app) as client:
                work = AsyncMock(side_effect=RuntimeError('private provider information'))
                with patch.object(app.state.backend, 'request', work):
                    result = client.post(PREFIX + 'v1/bills/import', json={})
                self.assertEqual(result.status_code, 503)
                self.assertEqual(result.json(), {'detail': 'Agent request could not be confirmed'})
                work.assert_awaited_once()

    def test_readiness_is_bounded_and_rejects_non_schema_responses(self):
        for status, body, media in ((200, '<private>', 'text/html'),
                (429, 'edge error', 'text/plain'), (200, '{"status":"ok"}', 'application/json'),
                (200, '{"status":"ready","private":true}', 'application/json'),
                (200, 'x' * 1025, 'application/json')):
            with self.subTest(body=body[:30]):
                result = readiness_response(httpx.Response(status, text=body,
                    headers={'content-type': media}), {})
                self.assertEqual(result.status_code, 503)
                self.assertNotIn(b'private', result.body)
        result = readiness_response(httpx.Response(200, json={'status': 'ready'}), {})
        self.assertEqual(result.status_code, 200)


class WebsiteConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_eight_slow_uploads_are_bounded_and_cancellation_releases_slots(self):
        with site() as root, patch.dict(os.environ, ENV):
            app = create_web_app(root)
            async with app.router.lifespan_context(app), httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url='http://website') as client:
                started = 0
                all_started = asyncio.Event()
                release = asyncio.Event()

                async def slow():
                    nonlocal started
                    started += 1
                    if started == 8:
                        all_started.set()
                    await release.wait()
                    yield b'{}'

                tasks = [asyncio.create_task(client.post(PREFIX + 'v1/bills/import', content=slow())) for _ in range(8)]
                try:
                    await asyncio.wait_for(all_started.wait(), timeout=2)
                    result = await client.post(PREFIX + 'v1/sessions', json={})
                    self.assertEqual(result.status_code, 429)
                    self.assertEqual(result.headers['retry-after'], '1')
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                self.assertEqual((await client.post(PREFIX + 'v1/sessions', json={})).status_code, 201)

    async def test_slow_body_times_out_before_backend_work(self):
        async def slow():
            await asyncio.sleep(1)
            yield b'{}'

        with site() as root, patch.dict(os.environ, ENV), patch('aquamind_ml.web.BODY_SECONDS', 0.01):
            app = create_web_app(root)
            async with app.router.lifespan_context(app), httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url='http://website') as client:
                work = AsyncMock()
                with patch.object(app.state.backend, 'request', work):
                    result = await client.post(PREFIX + 'v1/bills/import', content=slow())
                self.assertEqual(result.status_code, 408)
                work.assert_not_awaited()
