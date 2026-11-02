import asyncio
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from aquamind_ml.admission import PublicAdmission, PublicAdmissionMiddleware
from aquamind_ml.api import create_app


class AdmissionTests(unittest.TestCase):
    def test_rolling_limits_are_atomic_and_recover_without_unbounded_keys(self):
        now = [0.0]
        policy = PublicAdmission(clock=lambda: now[0], requests=3, sessions=1, paid=1)
        policy.enter('POST', '/v1/sessions')
        policy.leave()
        with self.assertRaises(HTTPException) as denied:
            policy.enter('POST', '/v1/sessions')
        self.assertEqual(denied.exception.status_code, 429)
        self.assertEqual(denied.exception.headers['Retry-After'], '60')
        # The rejected session request did not consume the general request window.
        for _ in range(2):
            policy.enter('POST', '/v1/bills/normalize')
            policy.leave()
        with self.assertRaises(HTTPException):
            policy.enter('GET', '/v1/goals/current')
        now[0] = 60
        policy.enter('POST', '/v1/sessions')
        policy.leave()
        self.assertEqual(set(policy._recent), {'all', 'sessions', 'paid'})
        self.assertTrue(all(len(window) <= 1 for window in policy._recent.values()))

    def test_paid_routes_share_a_window_and_concurrency_is_released(self):
        policy = PublicAdmission(paid=1, concurrent=1)
        policy.enter('POST', '/v1/bills/import')
        with self.assertRaises(HTTPException):
            policy.enter('GET', '/v1/goals/current')
        policy.leave()
        for path in ('/v1/agent/turn', '/v1/agent/continue', '/v1/agent/bill'):
            with self.assertRaises(HTTPException):
                policy.enter('POST', path)
        policy.enter('GET', '/v1/goals/current')
        policy.leave()

    def test_public_session_limits_ignore_forged_forwarding_headers_and_health_stays_live(self):
        with patch.dict(os.environ, {'AQUAMIND_PUBLIC_MODE': '1', 'AQUAMIND_AGENT_ENABLED': '0'}):
            with TestClient(create_app()) as client:
                for index in range(6):
                    self.assertEqual(client.post('/v1/sessions', headers={
                        'X-Forwarded-For': f'198.51.100.{index}',
                        'CF-Connecting-IP': f'203.0.113.{index}',
                    }).status_code, 201)
                for path in ('/v1/sessions', '/v1/sessions/'):
                    denied = client.post(path, follow_redirects=False)
                    self.assertEqual(denied.status_code, 429)
                    self.assertGreater(int(denied.headers['Retry-After']), 0)
                    self.assertEqual(denied.headers['Cache-Control'], 'no-store')
                    self.assertIn('X-Request-ID', denied.headers)
                self.assertEqual(client.get('/health').status_code, 200)

    def test_public_limits_are_opt_in_and_invalid_configuration_fails_startup(self):
        with patch.dict(os.environ, {'AQUAMIND_PUBLIC_MODE': '0', 'AQUAMIND_AGENT_ENABLED': '0'}):
            with TestClient(create_app()) as client:
                for _ in range(7):
                    self.assertEqual(client.post('/v1/sessions').status_code, 201)
        with patch.dict(os.environ, {'AQUAMIND_PUBLIC_MODE': 'invalid'}):
            with self.assertRaisesRegex(ValueError, 'AQUAMIND_PUBLIC_MODE'):
                with TestClient(create_app()):
                    pass

    def test_public_calculation_preserves_auth_and_payload_validation(self):
        with patch.dict(os.environ, {'AQUAMIND_PUBLIC_MODE': '1', 'AQUAMIND_AGENT_ENABLED': '0'}):
            with TestClient(create_app()) as client:
                body = {'period_start': '2026-06-01', 'period_end_exclusive': '2026-07-01',
                        'usage': '8.5', 'usage_unit': 'ccf'}
                self.assertEqual(client.post('/v1/bills/normalize', json=body).status_code, 401)
                token = client.post('/v1/sessions').json()['session_token']
                headers = {'Authorization': 'Bearer ' + token}
                result = client.post('/v1/bills/normalize', json=body, headers=headers)
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json()['us_gallons_per_day'], '211.948052')
                self.assertEqual(client.post('/v1/bills/normalize', content=b'x' * 1025,
                                             headers=headers).status_code, 413)


class AdmissionStreamTests(unittest.IsolatedAsyncioTestCase):
    async def run_stream(self, receive, *, path='/v1/bills/normalize', handler=None, timeout=1):
        self.policy = PublicAdmission(body_timeout=timeout)
        state = SimpleNamespace(public_admission=self.policy)
        self.events, self.bodies = [], []

        async def downstream(scope, read, send):
            self.bodies.append((await read())['body'])
            await send({'type': 'http.response.start', 'status': 204, 'headers': []})
            await send({'type': 'http.response.body', 'body': b''})

        async def send(event):
            self.events.append(event)

        middleware = PublicAdmissionMiddleware(handler or downstream)
        scope = {'type': 'http', 'method': 'POST', 'path': path, 'app': SimpleNamespace(state=state),
                 'headers': [(b'content-length', b'1')]}
        await middleware(scope, receive, send)

    async def test_streamed_actual_bytes_are_bounded_despite_false_length(self):
        chunks = iter([{'type': 'http.request', 'body': b'x' * 1024, 'more_body': True},
                       {'type': 'http.request', 'body': b'x', 'more_body': False}])

        async def receive():
            return next(chunks)

        await self.run_stream(receive)
        self.assertEqual(self.events[0]['status'], 413)
        self.assertEqual(self.bodies, [])
        self.assertEqual(self.policy._active, 0)

    async def test_disconnect_timeout_cancellation_and_downstream_failure_release_slots(self):
        async def disconnected():
            return {'type': 'http.disconnect'}

        await self.run_stream(disconnected)
        self.assertEqual(self.events, [])
        self.assertEqual(self.policy._active, 0)

        async def slow():
            await asyncio.Event().wait()

        await self.run_stream(slow, timeout=0.01)
        self.assertEqual(self.events[0]['status'], 408)
        self.assertEqual(self.policy._active, 0)

        async def cancelled():
            raise asyncio.CancelledError()

        with self.assertRaises(asyncio.CancelledError):
            await self.run_stream(cancelled)
        self.assertEqual(self.policy._active, 0)

        async def complete():
            return {'type': 'http.request', 'body': b'{}', 'more_body': False}

        async def failed(*args):
            raise RuntimeError('downstream failure')

        with self.assertRaises(RuntimeError):
            await self.run_stream(complete, handler=failed)
        self.assertEqual(self.policy._active, 0)

    async def test_multichunk_body_is_replayed_without_change(self):
        chunks = iter([{'type': 'http.request', 'body': b'{', 'more_body': True},
                       {'type': 'http.request', 'body': b'}', 'more_body': False}])

        async def receive():
            return next(chunks)

        await self.run_stream(receive)
        self.assertEqual(self.bodies, [b'{}'])
        self.assertEqual(self.events[0]['status'], 204)
        self.assertEqual(self.policy._active, 0)
