import unittest

from fastapi.testclient import TestClient
from mcp import Client

from aquamind_ml.api import create_app
from aquamind_ml.approvals import ApprovalSessionUnavailable, GoalRequest
from aquamind_ml.mcp_server import create_server
from aquamind_ml.sessions import DemoSessions


class SessionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = [0.0]
        self.sessions = DemoSessions(clock=lambda: self.now[0])
        self.client = TestClient(create_app(sessions=self.sessions))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def new_session(self):
        response = self.client.post("/v1/sessions")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.headers["cache-control"], "no-store")
        token = response.json()["session_token"]
        self.assertGreaterEqual(len(token), 40)
        return token, {"Authorization": "Bearer " + token}

    async def test_mcp_proposal_review_and_http_decision(self):
        token, headers = self.new_session()
        store = self.sessions.approvals(token)
        async with Client(create_server(None, frozenset({"goals:write"}), goal_approvals=store)) as mcp:
            result = await mcp.call_tool("set_conservation_goal", {"request": {"daily_gallons": 150}})
            self.assertFalse(result.is_error)
            proposal = result.structured_content
        path = '/v1/approvals/' + proposal['approval_id']
        self.assertEqual(self.client.get('/v1/goals/current', headers=headers).json(), {"goal": None})
        self.now[0] = 10
        review = self.client.get(path, headers=headers)
        self.assertEqual(review.status_code, 200)
        self.assertEqual(review.json()['arguments'], {'daily_gallons': 150})
        self.assertEqual(review.json()['expires_in_seconds'], 590)
        approved = self.client.post(path + '/decision', headers=headers, json={'decision': 'approve'})
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()['status'], 'approved')
        self.assertEqual(self.client.get('/v1/goals/current', headers=headers).json()['goal'], {'daily_gallons': 150})
        self.assertEqual(self.client.post(path + '/decision', headers=headers, json={'decision': 'approve'}).json(), approved.json())

    async def test_manual_proposal_still_requires_separate_decision(self):
        token, headers = self.new_session()
        self.assertEqual(self.client.post('/v1/goals/proposals', json={'daily_gallons': 150}).status_code, 401)
        response = self.client.post('/v1/goals/proposals', headers=headers, json={'daily_gallons': 150})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['status'], 'approval_required')
        self.assertIsNone(self.sessions.approvals(token).goal)
        self.assertEqual(self.client.post('/v1/goals/proposals', headers=headers,
                         json={'daily_gallons': 150, 'approved': True}).status_code, 422)
        path = '/v1/approvals/' + response.json()['approval_id'] + '/decision'
        self.assertEqual(self.client.post(path, headers=headers, json={'decision': 'approve'}).json()['status'], 'approved')
        self.assertEqual(self.sessions.approvals(token).goal.daily_gallons, 150)

    async def test_other_session_cannot_read_or_decide(self):
        token, headers = self.new_session()
        _, stranger = self.new_session()
        proposal = self.sessions.approvals(token).propose(GoalRequest(daily_gallons=100))
        path = '/v1/approvals/' + proposal.approval_id
        for auth, expected in (({}, 401), ({'Authorization': 'Bearer invalid'}, 401), (stranger, 404)):
            self.assertEqual(self.client.get(path, headers=auth).status_code, expected)
            self.assertEqual(self.client.post(path + '/decision', headers=auth, json={'decision': 'approve'}).status_code, expected)
        for body in ({'decision': 'yes'}, {'decision': 'approve', 'daily_gallons': 1}, {'approved': True}):
            self.assertEqual(self.client.post(path + '/decision', headers=headers, json=body).status_code, 422)
        self.assertIsNone(self.sessions.approvals(token).goal)
        rejected = self.client.post(path + '/decision', headers=headers, json={'decision': 'reject'})
        self.assertEqual(rejected.json()['status'], 'rejected')
        self.assertEqual(self.client.post(path + '/decision', headers=headers, json={'decision': 'approve'}).json()['status'], 'rejected')

    async def test_expiry_revocation_and_no_cross_origin_access(self):
        token, headers = self.new_session()
        proposal = self.sessions.approvals(token).propose(GoalRequest(daily_gallons=100))
        path = '/v1/approvals/' + proposal.approval_id
        self.now[0] = 600
        self.assertEqual(self.client.get(path, headers=headers).json()['status'], 'expired')
        self.assertEqual(self.client.post(path + '/decision', headers=headers, json={'decision': 'approve'}).json()['status'], 'expired')
        self.assertIsNone(self.sessions.approvals(token).goal)
        self.now[0] = 3600
        self.assertEqual(self.client.get('/v1/goals/current', headers=headers).status_code, 401)
        _, new_headers = self.new_session()
        self.assertEqual(self.client.delete('/v1/session', headers=new_headers).status_code, 204)
        self.assertEqual(self.client.get('/v1/goals/current', headers=new_headers).status_code, 401)
        preflight = self.client.options('/v1/approvals/id/decision', headers={
            'Origin': 'https://untrusted.example', 'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'authorization,content-type'})
        self.assertNotIn('access-control-allow-origin', preflight.headers)

    async def test_cached_mcp_store_loses_access_on_revoke_and_expiry(self):
        for ending in ("revoke", "expire", "evict"):
            with self.subTest(ending=ending):
                self.now[0] = 0
                token, headers = self.new_session()
                store = self.sessions.approvals(token)
                proposal = store.propose(GoalRequest(daily_gallons=150))
                async with Client(create_server(None, frozenset({"goals:write"}), goal_approvals=store)) as mcp:
                    if ending == "revoke":
                        self.assertEqual(self.client.delete('/v1/session', headers=headers).status_code, 204)
                    else:
                        self.now[0] = 3600
                        if ending == "evict":
                            self.sessions.create()
                    result = await mcp.call_tool("set_conservation_goal", {"request": {"daily_gallons": 100}})
                    self.assertTrue(result.is_error)
                    self.assertIn("Session unavailable", str(result.content))
                    for operation in (lambda: store.goal, lambda: store.review(proposal.approval_id),
                                      lambda: store.decide(proposal.approval_id, "approve"),
                                      lambda: store.decide(proposal.approval_id, "reject")):
                        with self.assertRaises(ApprovalSessionUnavailable):
                            operation()
                    # A replacement session never reactivates the cached store.
                    replacement = self.sessions.create()
                    self.assertIsNone(self.sessions.approvals(replacement).goal)
                    with self.assertRaises(ApprovalSessionUnavailable):
                        store.propose(GoalRequest(daily_gallons=100))

    def test_proposal_expiry_is_capped_by_session_lifetime(self):
        token, headers = self.new_session()
        self.now[0] = 3590
        proposal = self.sessions.approvals(token).propose(GoalRequest(daily_gallons=100))
        self.assertEqual(proposal.expires_in_seconds, 10)
        self.now[0] = 3595
        response = self.client.get('/v1/approvals/' + proposal.approval_id, headers=headers)
        self.assertEqual(response.json()['expires_in_seconds'], 5)

    def test_revoke_between_lookup_and_decision_returns_401(self):
        token, headers = self.new_session()
        store = self.sessions.approvals(token)
        proposal = store.propose(GoalRequest(daily_gallons=150))
        original = self.sessions.approvals
        def revoke_after_lookup(value):
            result = original(value)
            self.sessions.revoke(value)
            return result
        self.sessions.approvals = revoke_after_lookup
        response = self.client.post('/v1/approvals/' + proposal.approval_id + '/decision',
                                    headers=headers, json={'decision': 'approve'})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['detail'], 'Session unavailable')

    def test_session_capacity_recovers_after_expiry(self):
        for _ in range(100):
            self.sessions.create()
        self.assertEqual(self.client.post('/v1/sessions').status_code, 503)
        self.now[0] = 3600
        self.assertEqual(self.client.post('/v1/sessions').status_code, 201)
