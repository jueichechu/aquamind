from concurrent.futures import ThreadPoolExecutor
import unittest

from mcp import Client
from pydantic import ValidationError

from aquamind_ml.approvals import GoalApprovals, GoalRequest
from aquamind_ml.mcp_server import create_server


class ApprovalTests(unittest.IsolatedAsyncioTestCase):
    def test_no_write_before_approval_and_retries_do_not_execute_again(self):
        store = GoalApprovals()
        proposal = store.propose(GoalRequest(daily_gallons=150))
        self.assertIsNone(store.goal)
        self.assertEqual(proposal.status, "approval_required")
        self.assertIn("150.0 gallons", proposal.summary)
        outcome = store.decide(proposal.approval_id, "approve")
        self.assertEqual(outcome.status, "approved")
        self.assertEqual(store.goal.daily_gallons, 150)
        newer = store.propose(GoalRequest(daily_gallons=125))
        store.decide(newer.approval_id, "approve")
        self.assertEqual(store.decide(proposal.approval_id, "approve"), outcome)
        self.assertEqual(store.decide(proposal.approval_id, "reject"), outcome)
        self.assertEqual(store.goal.daily_gallons, 125)
        with self.assertRaises(ValidationError):
            proposal.arguments.daily_gallons = 1

    def test_rejection_expiry_and_cross_session_ids(self):
        now = [0.0]
        store = GoalApprovals(clock=lambda: now[0])
        rejected = store.propose(GoalRequest(daily_gallons=150))
        self.assertEqual(store.decide(rejected.approval_id, "reject").status, "rejected")
        self.assertEqual(store.decide(rejected.approval_id, "approve").status, "rejected")
        expired = store.propose(GoalRequest(daily_gallons=100))
        now[0] = 600
        self.assertEqual(store.decide(expired.approval_id, "approve").status, "expired")
        self.assertIsNone(store.goal)
        with self.assertRaises(LookupError):
            GoalApprovals().decide(expired.approval_id, "approve")
        with self.assertRaises(ValueError):
            store.decide(expired.approval_id, True)

    def test_concurrent_approvals_cannot_overwrite_a_newer_goal(self):
        store = GoalApprovals()
        proposals = [store.propose(GoalRequest(daily_gallons=value)) for value in (100, 150)]
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda p: store.decide(p.approval_id, "approve"), proposals))
        self.assertEqual(sorted(p.status for p in outcomes), ["approved", "conflict"])
        winner = next(p for p in outcomes if p.status == "approved")
        self.assertEqual(store.goal, winner.arguments)

    def test_capacity_and_invalid_requests(self):
        store = GoalApprovals()
        for _ in range(100):
            store.propose(GoalRequest(daily_gallons=100))
        with self.assertRaises(ValueError):
            store.propose(GoalRequest(daily_gallons=100))
        for value in (0, -1, True, "100", float("nan"), float("inf"), 10_001):
            with self.assertRaises(ValidationError):
                GoalRequest(daily_gallons=value)

    async def test_mcp_proposes_host_decides_and_agent_cannot_approve(self):
        store = GoalApprovals()
        async with Client(create_server(None, frozenset({"goals:write"}), goal_approvals=store)) as client:
            result = await client.call_tool("set_conservation_goal", {"request": {"daily_gallons": 150}})
            self.assertFalse(result.is_error)
            self.assertEqual(result.structured_content["status"], "approval_required")
            self.assertIsNone(store.goal)
            tools = await client.list_tools()
            self.assertFalse(any("approve" in tool.name or "decide" in tool.name for tool in tools.tools))
            for extra in ({"approved": True}, {"decision": "approve"}, {"approval_id": "forged"}):
                result_invalid = await client.call_tool("set_conservation_goal", {
                    "request": {"daily_gallons": 150} | extra})
                self.assertTrue(result_invalid.is_error)
            self.assertIsNone(store.goal)
            outcome = store.decide(result.structured_content["approval_id"], "approve")
            self.assertEqual(outcome.status, "approved")
            self.assertEqual(store.goal.daily_gallons, 150)

    async def test_scope_denial_cannot_create_proposal(self):
        store = GoalApprovals()
        async with Client(create_server(None, frozenset({"meter:read"}), goal_approvals=store)) as client:
            result = await client.call_tool("set_conservation_goal", {"request": {"daily_gallons": 150}})
            self.assertTrue(result.is_error)
            self.assertIn("goals:write required", str(result.content))
            self.assertIsNone(store.goal)
