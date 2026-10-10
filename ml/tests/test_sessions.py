import unittest

from fastapi.testclient import TestClient
from mcp import Client

from aquamind_ml.api import create_app
from aquamind_ml.approvals import GoalRequest
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

    def test_session_capacity_recovers_after_expiry(self):
        for _ in range(100):
            self.sessions.create()
        self.assertEqual(self.client.post('/v1/sessions').status_code, 503)
        self.now[0] = 3600
        self.assertEqual(self.client.post('/v1/sessions').status_code, 201)
