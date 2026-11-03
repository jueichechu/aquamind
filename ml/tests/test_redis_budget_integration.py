"""Optional real Redis checks; CI supplies a disposable loopback service.

No provider credentials or Python Redis dependency are needed. Setting the test
port requires redis-cli and a reachable server; connection errors fail the tests.
"""

from concurrent.futures import ThreadPoolExecutor
import json
import os
import shutil
import subprocess
import unittest
from uuid import uuid4

from aquamind_ml.remote_budget import RESERVE_STAGE_LUA


@unittest.skipUnless(os.environ.get('AQUAMIND_TEST_REDIS_PORT'),
                     'Set AQUAMIND_TEST_REDIS_PORT to a disposable local Redis service')
class RedisBudgetIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.port = int(os.environ['AQUAMIND_TEST_REDIS_PORT'])
        self.assertTrue(1024 <= self.port <= 65535, 'Use an unprivileged local test port')
        self.cli = shutil.which('redis-cli')
        self.assertIsNotNone(self.cli, 'Configured integration tests require redis-cli')
        self.key = 'aquamind:test:paid-stages:' + uuid4().hex
        self.assertEqual(self.command('PING'), 'PONG')
        # Delete only this test's unique key, never flush a shared database.
        self.addCleanup(self.command, 'DEL', self.key)

    def command(self, *args):
        result = subprocess.run([self.cli, '-h', '127.0.0.1', '-p', str(self.port), '--json',
                                 *map(str, args)], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def reserve(self, day=1000, limit=7):
        # Execute the exact production Lua. Each invocation opens a new connection.
        return self.command('EVAL', RESERVE_STAGE_LUA, 1, self.key, day, limit)

    def test_concurrent_connections_cannot_exceed_shared_cap(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.reserve(), range(40)))
        self.assertEqual(results.count(1), 7)
        self.assertEqual(results.count(0), 33)
        self.assertEqual(self.command('HGET', self.key, 'attempts'), '7')
        self.assertEqual(sorted(self.command('HKEYS', self.key)), ['attempts', 'day'])
        self.assertEqual(self.command('TTL', self.key), -1)

    def test_new_connections_preserve_quota_and_day_changes_are_monotonic(self):
        self.assertEqual(self.reserve(limit=2), 1)
        self.assertEqual(self.reserve(limit=2), 1)
        self.assertEqual(self.reserve(limit=2), 0)
        self.assertEqual(self.reserve(day=1001, limit=2), 1)
        self.assertEqual(self.reserve(day=1000, limit=2), -1)
        self.assertEqual(self.command('HGET', self.key, 'day'), '1001')
        self.assertEqual(self.command('HGET', self.key, 'attempts'), '1')

    def test_corrupt_or_future_state_is_rejected_without_resetting_it(self):
        for fields in ({'day': '1000'}, {'attempts': '1'},
                       {'day': '1000', 'attempts': 'invalid'},
                       {'day': '1000', 'attempts': '101'},
                       {'day': '1001', 'attempts': '1'}):
            with self.subTest(fields=fields):
                self.command('DEL', self.key)
                args = [value for pair in fields.items() for value in pair]
                self.command('HSET', self.key, *args)
                before = self.command('HGETALL', self.key)
                self.assertEqual(self.reserve(), -1)
                self.assertEqual(self.command('HGETALL', self.key), before)
