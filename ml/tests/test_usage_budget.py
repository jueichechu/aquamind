import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from aquamind_ml.agent import AgentConfig
from aquamind_ml.agent_http import AgentHost
from aquamind_ml.approvals import ApprovalSessionUnavailable
from aquamind_ml.api import create_app
from aquamind_ml.sessions import DemoSessions
from aquamind_ml.usage_budget import DailyStageBudget


class UsageBudgetTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'usage.sqlite3'
        self.day = [date(2026, 11, 1)]

    def budget(self, limit=2):
        return DailyStageBudget(self.path, limit, clock=lambda: self.day[0])

    def test_cap_survives_new_instances_and_advances_only_on_next_utc_day(self):
        self.budget().reserve()
        self.budget().reserve()
        with self.assertRaises(HTTPException) as exhausted:
            self.budget().reserve()
        self.assertEqual(exhausted.exception.status_code, 429)
        self.day[0] = date(2026, 11, 2)
        self.budget().reserve()
        self.day[0] = date(2026, 11, 1)
        with self.assertRaises(HTTPException) as backwards:
            self.budget().reserve()
        self.assertEqual(backwards.exception.status_code, 503)
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute('SELECT * FROM daily_usage').fetchall(), [(1, '2026-11-02', 1)])

    def test_locked_missing_or_corrupt_state_fails_closed_without_reset(self):
        budget = self.budget()
        budget.reserve()
        with closing(sqlite3.connect(self.path)) as locked:
            locked.execute('BEGIN IMMEDIATE')
            with self.assertRaises(HTTPException) as busy:
                budget.reserve()
            self.assertEqual(busy.exception.status_code, 503)
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute('SELECT attempts FROM daily_usage').fetchone(), (1,))
            connection.execute("UPDATE daily_usage SET day='invalid'")
            connection.commit()
        with self.assertRaises(HTTPException):
            budget.reserve()
        self.path.unlink()
        with self.assertRaises(HTTPException):
            budget.reserve()
        self.path.write_bytes(b'not a sqlite database')
        with self.assertRaises(ValueError):
            self.budget()

    def test_independent_connections_cannot_over_reserve_the_last_stage(self):
        budgets = [self.budget(limit=1) for _ in range(6)]

        def attempt(budget):
            try:
                budget.reserve()
                return 200
            except HTTPException as error:
                return error.status_code

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(attempt, budgets))
        # Nonblocking SQLite locks can reject every contender, including a writer
        # whose commit races another connection's shared lock. Safety guarantees
        # at most one admission, not progress while the database is contended.
        admitted = results.count(200)
        self.assertLessEqual(admitted, 1)
        self.assertTrue(all(status in {200, 429, 503} for status in results))
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute('SELECT attempts FROM daily_usage').fetchone(),
                             (1,) if admitted else None)
        # Once all competing connections close, any unclaimed slot is usable.
        if not admitted:
            budgets[0].reserve()
        with self.assertRaises(HTTPException) as exhausted:
            budgets[-1].reserve()
        self.assertEqual(exhausted.exception.status_code, 429)
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute('SELECT attempts FROM daily_usage').fetchone(), (1,))

    def test_rejects_relative_paths_and_unsafe_limits(self):
        for path, limit in ((Path('usage.sqlite3'), 1), (self.path, True),
                            (self.path, 0), (self.path, 101)):
            with self.assertRaises(ValueError):
                DailyStageBudget(path, limit)

    def test_public_ai_requires_usable_persistent_budget_before_startup(self):
        host = SimpleNamespace()
        with patch.dict(os.environ, {'AQUAMIND_PUBLIC_MODE': '1', 'AQUAMIND_AGENT_ENABLED': '0',
                                    'AQUAMIND_USAGE_DB': str(self.path), 'AQUAMIND_AI_DAILY_STAGE_LIMIT': '2'}):
            with TestClient(create_app(agent_host=host)) as client:
                self.assertEqual(client.get('/health').status_code, 200)
                self.assertIsInstance(host._daily_budget, DailyStageBudget)
                self.assertEqual(host._daily_budget.limit, 2)
        with patch.dict(os.environ, {'AQUAMIND_PUBLIC_MODE': '1', 'AQUAMIND_AGENT_ENABLED': '1',
                                    'AQUAMIND_USAGE_DB': '', 'AQUAMIND_AI_DAILY_STAGE_LIMIT': '20'}):
            with self.assertRaises(ValueError):
                with TestClient(create_app()):
                    pass
        for limit in ('0', '101', 'invalid', '１'):
            with patch.dict(os.environ, {'AQUAMIND_PUBLIC_MODE': '1', 'AQUAMIND_AGENT_ENABLED': '1',
                                        'AQUAMIND_USAGE_DB': str(self.path), 'AQUAMIND_AI_DAILY_STAGE_LIMIT': limit}):
                with self.assertRaises(ValueError):
                    with TestClient(create_app()):
                        pass


class HostBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_and_failed_stages_consume_budget_across_hosts_and_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'usage.sqlite3'
            sessions = DemoSessions()
            store = sessions.approvals(sessions.create())
            host = AgentHost(None, AgentConfig(model='test-model'), daily_budget=DailyStageBudget(path, 2))
            with self.assertRaises(HTTPException) as failed:
                async with host._slot(store):
                    raise RuntimeError('failed attempt')
            self.assertEqual(failed.exception.status_code, 503)
            self.assertEqual(host._active, set())
            with self.assertRaises(asyncio.CancelledError):
                async with host._slot(store):
                    raise asyncio.CancelledError()
            self.assertEqual(host._active, set())
            replacement = AgentHost(None, AgentConfig(model='test-model'), daily_budget=DailyStageBudget(path, 2))
            stranger = sessions.approvals(sessions.create())
            with self.assertRaises(HTTPException) as exhausted:
                async with replacement._slot(stranger):
                    self.fail('No work may run after the durable cap')
            self.assertEqual(exhausted.exception.status_code, 429)
            self.assertEqual(replacement._active, set())
            self.assertEqual(replacement._total, 0)

    async def test_busy_or_invalid_session_does_not_reserve_a_paid_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'usage.sqlite3'
            sessions = DemoSessions()
            token = sessions.create()
            store = sessions.approvals(token)
            host = AgentHost(None, AgentConfig(model='test-model'), daily_budget=DailyStageBudget(path, 2))
            async with host._slot(store):
                with self.assertRaises(HTTPException) as busy:
                    async with host._slot(store):
                        self.fail('Busy stage may not run')
                self.assertEqual(busy.exception.status_code, 409)
            sessions.revoke(token)
            with self.assertRaises(ApprovalSessionUnavailable):
                async with host._slot(store):
                    self.fail('Revoked stage may not run')
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute('SELECT attempts FROM daily_usage').fetchone(), (1,))
