import asyncio
from contextlib import AsyncExitStack
import json
import os
import unittest
from unittest.mock import patch

import httpx
import httpx2
from openai import AsyncOpenAI

from aquamind_ml.agent import AgentConfig, EVIDENCE_POLICY, POLICY
from aquamind_ml.agent_http import AgentHost
from aquamind_ml.api import create_app
from aquamind_ml.meter_import import MeterImportRequest, parse_meter_csv
from aquamind_ml.sessions import DemoSessions
from test_agent import call, is_topic_request, message, response, topic_response
from test_meter_import import meter_body


class EvidenceAgentHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        env = patch.dict(os.environ, {'AQUAMIND_AGENT_ENABLED': '0', 'AQUAMIND_INFERENCE_ENABLED': '0',
            'AQUAMIND_DETECTOR_PATH': '', 'AQUAMIND_PUBLIC_MODE': '0', 'AQUAMIND_RELAY_REQUIRED': '0',
            'AQUAMIND_METER_IMPORT_ENABLED': '1'})
        env.start(); self.addCleanup(env.stop)
        self.now = [0.0]
        self.sessions = DemoSessions(clock=lambda: self.now[0])
        self.requests, self.topics = [], []
        self.intent = 'household_usage'
        self.reply = lambda body: response([call(name='get_meter_summary', arguments='{}')]) if body.get('tool_choice') else response([message('The meter covers only part of the unverified bill; their totals cannot be compared.')])

        async def handle(request):
            body = json.loads(request.content)
            if is_topic_request(body):
                self.topics.append(body)
                return httpx2.Response(200, json=topic_response(self.intent))
            self.requests.append(body)
            value = self.reply(body)
            if asyncio.iscoroutine(value):
                value = await value
            return httpx2.Response(200, json=value)
        self.stack = AsyncExitStack(); self.addAsyncCleanup(self.stack.aclose)
        provider = await self.stack.enter_async_context(AsyncOpenAI(api_key='test-placeholder', max_retries=0,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle))))
        self.host = AgentHost(provider, AgentConfig(model='test-model'))
        self.app = create_app(sessions=self.sessions, agent_host=self.host)
        await self.stack.enter_async_context(self.app.router.lifespan_context(self.app))
        self.http = await self.stack.enter_async_context(httpx.AsyncClient(transport=httpx.ASGITransport(self.app), base_url='http://test'))
        self.token = self.sessions.create()
        self.auth = {'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'}
        self.meters = self.sessions.meters(self.token)
        self.dataset = parse_meter_csv(MeterImportRequest.model_validate(meter_body()))
        self.selected = self.meters.replace(self.dataset)
        self.body = {'text': 'Explain this household water bill and its imported meter coverage.',
            'bill': {'period_start': '2026-06-01', 'period_end_exclusive': '2026-07-01', 'usage': '810', 'usage_unit': 'us_gallons'},
            'bill_timezone': 'UTC', 'bill_input_method': 'document_import',
            'bill_reading_type': 'estimated',
            'meter_evidence_id': self.selected.context.evidence_id, 'bill_reviewed': True,
            'meter_reviewed': True, 'same_household': True, 'share_with_ai': True}

    async def post(self, body=None, **kwargs):
        return await self.http.post('/v1/agent/evidence', headers=self.auth,
            **(kwargs or {'json': self.body if body is None else body}))

    async def test_real_sdk_mcp_grounding_partial_coverage_and_minimized_provider_context(self):
        with self.assertLogs('aquamind.api', level='INFO') as logs:
            result = await self.post()
        self.assertEqual(result.status_code, 200)
        value = result.json()
        self.assertEqual(value['status'], 'answer')
        self.assertEqual(value['model_calls'], 3)
        self.assertIsNone(value['pending_approval'])
        self.assertEqual([(t['tool_name'], t['status']) for t in value['tool_trace']], [('get_meter_summary', 'success')])
        facts = json.loads(self.requests[0]['input'][0]['content'])['combined_evidence']
        self.assertEqual(facts['bill']['us_gallons_per_day'], '27.000000')
        self.assertEqual(facts['assessment']['coverage'], 'partial_period')
        self.assertIsNone(facts['totals_comparison'])
        self.assertEqual(facts['bill_input_method_user_reported'], 'document_import')
        self.assertEqual(facts['bill_reading_type_user_reported'], 'estimated')
        self.assertEqual(self.requests[0]['instructions'], POLICY + EVIDENCE_POLICY)
        self.assertEqual(self.requests[0]['tool_choice'], {'type': 'function', 'name': 'get_meter_summary'})
        self.assertEqual({tool['name'] for tool in self.requests[0]['tools']}, {'get_meter_summary', 'get_meter_series'})
        self.assertEqual(json.loads(self.topics[0]['input'][0]['content'])['mode'], 'bill_meter_water')
        for request in self.requests + self.topics:
            self.assertFalse(request['store']); self.assertFalse(request['parallel_tool_calls'])
        for private in (self.token, self.selected.context.evidence_id, self.selected.context.household_id, self.dataset.dataset_sha256):
            self.assertNotIn(private, json.dumps(self.requests + self.topics))
            self.assertNotIn(private, str(logs.output))
        self.assertNotIn('810', str(logs.output))
        self.assertIsNone(self.sessions.approvals(self.token).goal)
        self.assertEqual(self.sessions.approvals(self.token)._entries, {})

    async def test_equal_periods_have_host_calculated_total_difference(self):
        body = self.body | {'bill': self.body['bill'] | {'period_end_exclusive': '2026-06-02', 'usage': '90'}}
        result = await self.post(body)
        self.assertEqual(result.json()['status'], 'answer')
        facts = json.loads(self.requests[0]['input'][0]['content'])['combined_evidence']
        self.assertEqual(facts['assessment']['coverage'], 'same_period')
        self.assertEqual(facts['totals_comparison']['meter_minus_bill_us_gallons'], '6.000000')

    async def test_all_confirmations_are_strict_required_and_admitted_before_paid_work(self):
        for key in ('bill_reviewed', 'meter_reviewed', 'same_household', 'share_with_ai'):
            for value in (False, 1, 'true', None):
                self.assertEqual((await self.post(self.body | {key: value})).status_code, 422)
            missing = dict(self.body); missing.pop(key)
            self.assertEqual((await self.post(missing)).status_code, 422)
        for changes in ({'household_id': 'house_forged'}, {'is_example': True}, {'tools': ['set_conservation_goal']},
                        {'bill_timezone': 'Unknown/Zone'}, {'normalized_bill': {'usage': '0'}}):
            self.assertEqual((await self.post(self.body | changes)).status_code, 422)
        self.assertEqual(self.requests + self.topics, [])
        self.assertEqual(self.host._total, 0)

    async def test_foreign_replaced_missing_and_disjoint_refs_do_not_consume_budget(self):
        stranger = self.sessions.create()
        result = await self.http.post('/v1/agent/evidence', headers={'Authorization': 'Bearer ' + stranger}, json=self.body)
        self.assertEqual(result.status_code, 404)
        for bill in (self.body['bill'] | {'period_start': '2024-06-01', 'period_end_exclusive': '2024-07-01'},
                     self.body['bill'] | {'period_end_exclusive': '2026-06-02'}):
            # The second case is valid; make its local midnight start cross the meter.
            timezone = 'America/New_York' if bill['period_start'].startswith('2026') else 'UTC'
            self.assertEqual((await self.post(self.body | {'bill': bill, 'bill_timezone': timezone})).status_code, 422)
        self.meters.replace(self.dataset)
        self.assertEqual((await self.post()).status_code, 404)
        self.assertEqual(self.requests + self.topics, [])
        self.assertEqual(self.host._total, 0)

    async def test_replacement_and_revocation_during_provider_work_do_not_release_answer(self):
        for ending in ('replace', 'revoke', 'expire'):
            if ending != 'replace':
                self.token = self.sessions.create(); self.auth = {'Authorization': 'Bearer ' + self.token}
                self.meters = self.sessions.meters(self.token)
            self.body['meter_evidence_id'] = self.meters.replace(self.dataset).context.evidence_id
            async def change(_):
                if ending == 'replace': self.meters.replace(self.dataset)
                elif ending == 'revoke': self.sessions.revoke(self.token)
                else: self.now[0] += 3600
                return response([message('PRIVATE_STALE_ANSWER')])
            self.reply = change
            result = await self.post()
            self.assertEqual(result.status_code, 409 if ending == 'replace' else 401)
            self.assertNotIn('PRIVATE_STALE_ANSWER', result.text)

    async def test_unsupported_topics_and_ignored_forced_tools_cannot_produce_answers(self):
        self.intent = 'unsupported'
        self.assertEqual((await self.post()).json()['status'], 'refused')
        self.assertEqual(self.requests, [])
        self.intent = 'household_usage'
        for output in (message('An unsupported ungrounded answer'), call(name='set_conservation_goal', arguments='{"request":{"daily_gallons":150}}')):
            self.reply = lambda _: response([output])
            result = await self.post()
            self.assertEqual(result.json()['status'], 'unavailable')
            self.assertEqual(result.json()['answer'], '')
        self.assertEqual(self.sessions.approvals(self.token)._entries, {})

    async def test_write_attempt_after_read_is_rejected_by_actual_tool_adapter(self):
        self.reply = lambda body: response([call(name='get_meter_summary', arguments='{}')]) if body.get('tool_choice') else response([call(identifier='write_2', name='set_conservation_goal', arguments='{"request":{"daily_gallons":150}}')])
        result = await self.post()
        self.assertEqual(result.json()['status'], 'unavailable')
        self.assertEqual(result.json()['tool_trace'][-1]['status'], 'error')
        self.assertEqual(self.sessions.approvals(self.token)._entries, {})

    async def test_bounded_json_authentication_and_session_expiry(self):
        self.assertEqual((await self.http.post('/v1/agent/evidence', content='invalid')).status_code, 401)
        self.assertEqual((await self.post(content=b'x' * 16385)).status_code, 413)
        self.assertEqual((await self.post(content='{"text":"PRIVATE","text":"duplicate"}')).status_code, 422)
        self.assertEqual((await self.http.post('/v1/agent/evidence', headers=self.auth | {'Content-Type': 'text/plain'}, content='{}')).status_code, 415)
        self.now[0] += 3600
        self.assertEqual((await self.post()).status_code, 401)
        self.assertEqual(self.requests + self.topics, [])

    async def test_existing_paid_stage_and_session_limits_apply_without_retries(self):
        from fastapi import HTTPException
        class DeniedBudget:
            def __init__(self): self.calls=0
            def reserve(self):
                self.calls+=1
                raise HTTPException(429, 'Daily AI request limit reached')
        budget=DeniedBudget();self.host._daily_budget=budget
        result=await self.post()
        self.assertEqual(result.status_code,429)
        self.assertEqual(budget.calls,1)
        self.assertEqual(self.requests+self.topics,[])
        self.assertEqual(self.host._total,0)
        self.host._daily_budget=None
        self.host._counts[self.sessions.approvals(self.token)]=8
        self.assertEqual((await self.post()).status_code,429)
        self.assertEqual(self.requests+self.topics,[])


if __name__ == '__main__':
    unittest.main()
