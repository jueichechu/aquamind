import unittest

import httpx

from aquamind_ml.benchmark import measure, percentiles


class BenchmarkTests(unittest.IsolatedAsyncioTestCase):
    def test_nearest_rank(self):
        self.assertEqual(percentiles(list(range(1, 101))), {"p50_ms": 50, "p95_ms": 95, "p99_ms": 99})
        self.assertIsNone(percentiles([]))

    async def test_counts_failures_without_retry_and_excludes_warmup(self):
        calls = 0

        def handler(request):
            nonlocal calls
            calls += 1
            if calls == 3:
                return httpx.Response(503)
            return httpx.Response(200, headers={"X-Request-ID": "test"}, json={
                "score": 1, "is_leak": False, "threshold": 2, "model_version": "v1", "request_id": "test"})

        async with httpx.AsyncClient(base_url="http://test", transport=httpx.MockTransport(handler)) as client:
            report = await measure(client, [{}], "v1", 5, 2, 1)
        self.assertEqual(calls, 6)
        self.assertEqual(report["successful_requests"], 4)
        self.assertEqual(report["failed_requests"], 1)
        self.assertEqual(len(report["samples"]), 5)

    async def test_warmup_failure_aborts(self):
        async with httpx.AsyncClient(base_url="http://test", transport=httpx.MockTransport(
                lambda request: httpx.Response(503))) as client:
            with self.assertRaises(RuntimeError):
                await measure(client, [{}], "v1", 5, 1, 1)
