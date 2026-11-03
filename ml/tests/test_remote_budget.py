import asyncio
from contextlib import AsyncExitStack
from datetime import date
import json
import os
import shutil
import subprocess
import unittest
from unittest.mock import patch

import httpx
import httpx2
from fastapi import HTTPException
from fastapi.testclient import TestClient
from openai import AsyncOpenAI

from aquamind_ml.agent import AgentConfig
from aquamind_ml.agent_http import AgentHost
from aquamind_ml.api import create_app
from aquamind_ml.remote_budget import RESERVE_STAGE_LUA, UpstashStageBudget
from aquamind_ml.sessions import DemoSessions
from test_agent import message, response, is_topic_request, topic_response


class RemoteBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_sdk_http_flow_stops_before_provider_after_remote_exhaustion(self):
        ledger_calls, provider_calls = [], []

        def ledger(request):
            ledger_calls.append(request)
            return httpx.Response(200, json={'result': 1 if len(ledger_calls) == 1 else 0})

        def provider(request):
            provider_calls.append(request)
            reply = topic_response() if is_topic_request(json.loads(request.content)) else response([
                message('Synthetic test answer.')])
            return httpx2.Response(200, json=reply)

        with patch.dict(os.environ, {'AQUAMIND_PUBLIC_MODE': '0', 'AQUAMIND_AGENT_ENABLED': '0',
                                    'AQUAMIND_INFERENCE_ENABLED': '0', 'AQUAMIND_RELAY_REQUIRED': '0'}):
            async with AsyncExitStack() as stack:
                counter = await stack.enter_async_context(httpx.AsyncClient(transport=httpx.MockTransport(ledger)))
                sdk = await stack.enter_async_context(AsyncOpenAI(api_key='test-only-placeholder',
                    http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(provider))))
                host = AgentHost(sdk, AgentConfig(model='test-model'), daily_budget=UpstashStageBudget(
                    counter, 'https://example.upstash.io', 'test-only-ledger-token', 1))
                app = create_app(agent_host=host)
                await stack.enter_async_context(app.router.lifespan_context(app))
                client = await stack.enter_async_context(httpx.AsyncClient(
                    transport=httpx.ASGITransport(app), base_url='http://test'))
                for expected in (200, 429):
                    token = (await client.post('/v1/sessions')).json()['session_token']
                    result = await client.post('/v1/agent/turn', json={'text': 'A fictional water question'},
                                               headers={'Authorization': 'Bearer ' + token})
                    self.assertEqual(result.status_code, expected)
                    if expected == 200:
                        self.assertEqual((result.json()['status'], result.json()['model_calls']), ('answer', 2))
                self.assertEqual(len(provider_calls), 2)
                self.assertEqual(len(ledger_calls), 2)

    def test_public_upstash_configuration_is_required_and_lifespan_owned(self):
        from types import SimpleNamespace
        env = {'AQUAMIND_PUBLIC_MODE': '1', 'AQUAMIND_INFERENCE_ENABLED': '0',
               'AQUAMIND_AGENT_ENABLED': '0', 'AQUAMIND_RELAY_REQUIRED': '0',
               'AQUAMIND_USAGE_STORE': 'upstash', 'UPSTASH_REDIS_REST_URL': 'https://example.upstash.io',
               'UPSTASH_REDIS_REST_TOKEN': 'test-only-token', 'AQUAMIND_AI_DAILY_STAGE_LIMIT': '20'}
        host = SimpleNamespace()
        with patch.dict(os.environ, env), TestClient(create_app(agent_host=host)) as client:
            self.assertEqual(client.get('/health').status_code, 200)
            self.assertIsInstance(host._daily_budget, UpstashStageBudget)
            counter_client = host._daily_budget._client
            self.assertFalse(counter_client.is_closed)
        self.assertTrue(counter_client.is_closed)
        for changes in ({'UPSTASH_REDIS_REST_URL': ''}, {'UPSTASH_REDIS_REST_TOKEN': ''},
                        {'AQUAMIND_USAGE_STORE': 'invalid'}):
            with patch.dict(os.environ, env | changes), self.assertRaises(ValueError):
                with TestClient(create_app(agent_host=SimpleNamespace())):
                    pass

    async def test_metadata_only_request_and_strict_admission_without_retries(self):
        requests = []
        replies = iter([{'result': 1}, {'result': 0}, {'result': -1}, {'result': True},
                        {'result': 1, 'error': 'private details'}, {'error': 'private details'}])

        def handle(request):
            requests.append(request)
            return httpx.Response(200, json=next(replies))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            budget = UpstashStageBudget(client, 'https://example.upstash.io/', 'private-test-token', 2,
                                        clock=lambda: date(2026, 11, 1))
            await budget.reserve_async()
            for expected in (429, 503, 503, 503, 503):
                with self.assertRaises(HTTPException) as denied:
                    await budget.reserve_async()
                self.assertEqual(denied.exception.status_code, expected)
                self.assertNotIn('private', str(denied.exception))
        self.assertEqual(len(requests), 6)
        command = json.loads(requests[0].content)
        self.assertEqual(command, ['EVAL', RESERVE_STAGE_LUA, 1, 'aquamind:paid-stages:v1',
                                   date(2026, 11, 1).toordinal(), 2])
        self.assertEqual(requests[0].headers['authorization'], 'Bearer private-test-token')
        self.assertEqual(str(requests[0].url), 'https://example.upstash.io')
        self.assertNotIn('private-test-token', requests[0].content.decode())

    async def test_failures_timeouts_redirects_and_oversized_responses_fail_closed(self):
        for kind in ('timeout', 'redirect', 'server', 'invalid', 'oversized', 'disconnect'):
            requests = []

            async def handle(request):
                requests.append(request)
                if kind == 'timeout':
                    await asyncio.Event().wait()
                if kind == 'disconnect':
                    raise httpx.ReadError('private connection details')
                if kind == 'redirect':
                    return httpx.Response(307, headers={'Location': 'https://untrusted.example'})
                if kind == 'server':
                    return httpx.Response(500)
                return httpx.Response(200, content=b'x' * 4097 if kind == 'oversized' else b'not json')

            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
                budget = UpstashStageBudget(client, 'https://example.upstash.io', 'test-token', 2, deadline=0.02)
                with self.assertRaises(HTTPException) as denied:
                    await budget.reserve_async()
                self.assertEqual(denied.exception.status_code, 503)
                self.assertEqual(len(requests), 1)

    async def test_pending_ledger_reservation_preserves_host_capacity_and_rolls_back_on_failure(self):
        entered, release = asyncio.Event(), asyncio.Event()
        requests = []

        async def handle(request):
            requests.append(request)
            entered.set()
            await release.wait()
            return httpx.Response(503)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            budget = UpstashStageBudget(client, 'https://example.upstash.io', 'test-token', 2)
            host = AgentHost(None, AgentConfig(model='test-model'), daily_budget=budget)
            sessions = DemoSessions()
            store = sessions.approvals(sessions.create())

            async def run():
                with self.assertRaises(HTTPException) as error:
                    async with host._slot(store):
                        self.fail('No work may start after ledger failure')
                self.assertEqual(error.exception.status_code, 503)

            pending = asyncio.create_task(run())
            await entered.wait()
            try:
                with self.assertRaises(HTTPException) as busy:
                    async with host._slot(store):
                        self.fail('Duplicate session stage may not enter')
                self.assertEqual(busy.exception.status_code, 409)
                self.assertEqual(len(requests), 1)
            finally:
                release.set()
                await pending
            self.assertEqual(host._active, set())
            self.assertEqual(host._total, 0)
            self.assertEqual(host._counts[store], 0)

    def test_only_official_https_endpoints_and_valid_credentials_are_accepted(self):
        for url in ('http://example.upstash.io', 'https://upstash.io.evil.example',
                    'https://example.upstash.io/?token=secret', 'https://user@example.upstash.io',
                    'https://example.upstash.io:8443', 'https://example.upstash.io/path'):
            with self.assertRaises(ValueError):
                UpstashStageBudget(None, url, 'token', 2)
        for token, limit in (('', 2), ('two words', 2), ('token', True), ('token', 0), ('token', 101)):
            with self.assertRaises(ValueError):
                UpstashStageBudget(None, 'https://example.upstash.io', token, limit)


class LuaBudgetTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('lua'), 'Lua interpreter unavailable; REST and host tests still run')
    def test_actual_lua_admission_logic_against_redis_compatible_hash_primitives(self):
        # Execute the shipped Lua, rather than a Python copy of its quota logic.
        harness = '''
            local state = {}
            redis = {call = function(command, key, ...)
                local args = {...}
                if command == 'HMGET' then return {state[args[1]] or false, state[args[2]] or false} end
                if command == 'HSET' then
                    for i=1,#args,2 do state[args[i]] = tostring(args[i+1]) end
                    return 1
                end
                error('Unexpected Redis primitive')
            end}
            local function reserve(day, limit)
                ARGV = {tostring(day), tostring(limit)}
                KEYS = {'aquamind:paid-stages:v1'}
                return (function()
        ''' + RESERVE_STAGE_LUA + '''
                end)()
            end
            assert(reserve(1000, 2) == 1)
            assert(reserve(1000, 2) == 1)
            assert(reserve(1000, 2) == 0)
            assert(state.attempts == '2')
            assert(reserve(1001, 2) == 1)
            assert(reserve(1000, 2) == -1)
            state.attempts = 'invalid'
            assert(reserve(1001, 2) == -1)
            state.attempts = false
            assert(reserve(1001, 2) == -1)
            print('Lua quota logic passed')
        '''
        result = subprocess.run([shutil.which('lua'), '-'], input=harness, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
