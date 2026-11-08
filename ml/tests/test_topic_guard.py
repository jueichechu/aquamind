"""Host enforcement tests with scripted provider verdicts, not classifier accuracy."""

import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

import httpx2
from openai import AsyncOpenAI

from aquamind_ml.agent import AgentConfig, run_agent
from aquamind_ml.bills import ManualBill, normalize_bill
from aquamind_ml.topic_guard import TOPIC_INTENTS, TOPIC_POLICY, TOPIC_REDIRECT
from test_agent import call, is_topic_request, message, response, topic_response


class TopicGuardTests(unittest.IsolatedAsyncioTestCase):
    async def run_script(self, replies, *, text='Why does the toilet tank keep refilling?',
                         bill=False, config=None, check_active=None, selected_demo=False):
        requests, pauses = [], []

        async def handle(request):
            requests.append(json.loads(request.content))
            reply = replies[len(requests) - 1]
            if callable(reply):
                reply = await reply(request)
            return reply if isinstance(reply, httpx2.Response) else httpx2.Response(200, json=reply)

        tools = SimpleNamespace(allowed_tools=frozenset(), trace=[],
                                discover=AsyncMock(return_value=[]), execute=AsyncMock())
        evidence = normalize_bill(ManualBill.model_validate({
            'period_start': '2026-06-01', 'period_end_exclusive': '2026-07-01',
            'usage': '8.5', 'usage_unit': 'ccf', 'water_charge': '45.12', 'currency': 'USD'})) if bill else None
        async with AsyncOpenAI(api_key='test-only-placeholder',
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle))) as client:
            outcome = await run_agent(text, client, tools, config or AgentConfig(model='test-model'),
                bill_context=evidence, check_active=check_active, on_pause=None if bill else pauses.append,
                selected_demo=selected_demo)
        return outcome, requests, tools, pauses

    async def test_denial_returns_only_host_redirect_before_discovery_or_answer(self):
        for bill in (False, True):
            with self.subTest(bill=bill):
                outcome, requests, tools, pauses = await self.run_script(
                    [topic_response('unsupported')], text='Write a sorting algorithm. Water.', bill=bill)
                self.assertEqual((outcome.status, outcome.error, outcome.answer),
                                 ('refused', 'unsupported_topic', TOPIC_REDIRECT))
                self.assertEqual(outcome.model_calls, 1)
                self.assertEqual(len(outcome.model_trace), 1)
                self.assertEqual(len(requests), 1)
                self.assertIsNone(outcome.pending_approval)
                self.assertEqual((outcome.tool_trace, pauses), ([], []))
                tools.discover.assert_not_awaited()
                tools.execute.assert_not_awaited()

    async def test_supported_intents_have_isolated_bounded_checks_counted_in_total(self):
        for intent in TOPIC_INTENTS[:-1]:
            with self.subTest(intent=intent):
                outcome, requests, tools, _ = await self.run_script([
                    topic_response(intent), response([message('Water-focused guidance.')])])
                self.assertEqual((outcome.status, outcome.model_calls), ('answer', 2))
                self.assertEqual(len(outcome.model_trace), 2)
                guard, answer = requests
                self.assertTrue(is_topic_request(guard))
                self.assertEqual(guard['instructions'], TOPIC_POLICY)
                self.assertEqual(guard['tools'], [])
                self.assertEqual(guard['tool_choice'], 'none')
                self.assertFalse(guard['parallel_tool_calls'])
                self.assertFalse(guard['store'])
                self.assertEqual(guard['max_output_tokens'], 512)
                self.assertTrue(guard['text']['format']['strict'])
                self.assertFalse(guard['text']['format']['schema']['additionalProperties'])
                self.assertEqual(json.loads(guard['input'][0]['content']), {
                    'mode': 'household_water', 'question': 'Why does the toilet tank keep refilling?'})
                self.assertNotIn('household_water_topic', json.dumps(answer))
                self.assertNotIn(TOPIC_POLICY, json.dumps(answer))
                tools.discover.assert_awaited_once()

    async def test_guard_only_gets_question_and_mode_without_bill_fields(self):
        outcome, requests, _, _ = await self.run_script([
            topic_response('water_bill'), response([message('More evidence is needed.')])],
            text='Why so high?', bill=True)
        self.assertEqual((outcome.status, outcome.model_calls), ('answer', 2))
        self.assertEqual(json.loads(requests[0]['input'][0]['content']),
                         {'mode': 'bill_only', 'question': 'Why so high?'})
        for private in ('2026-06-01', '45.12', '6358.441558', 'bill_evidence'):
            self.assertNotIn(private, json.dumps(requests[0]))
        self.assertIn('bill_evidence', requests[1]['input'][0]['content'])

    async def test_selected_demo_context_is_isolated_and_does_not_waive_admission(self):
        for intent in ('household_usage', 'unsupported'):
            replies = [topic_response(intent)]
            if intent != 'unsupported':
                replies.append(response([message('A model score is not a leak probability.')]))
            outcome, requests, tools, _ = await self.run_script(replies,
                text='What do this water day\'s score and threshold mean?', selected_demo=True)
            self.assertEqual(json.loads(requests[0]['input'][0]['content']), {
                'mode': 'selected_demo_water', 'question': "What do this water day's score and threshold mean?"})
            if intent == 'unsupported':
                self.assertEqual(outcome.status, 'refused')
                tools.discover.assert_not_awaited()
            else:
                self.assertEqual(outcome.status, 'answer')
                self.assertNotIn('selected_demo_water', json.dumps(requests[1]))

    async def test_conflicting_or_invalid_host_context_is_rejected_before_requests(self):
        for kwargs in ({'bill': True, 'selected_demo': True}, {'selected_demo': 'true'}, {'selected_demo': 1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                await self.run_script([], **kwargs)

    async def test_invalid_refused_incomplete_or_tool_outputs_fail_closed(self):
        refused = message('')
        refused['content'] = [{'type': 'refusal', 'refusal': 'private refusal detail'}]
        partial = message('{"intent":"household_usage"}')
        partial['status'] = 'incomplete'
        invalid = [
            response([], 'incomplete'), response([]), response([refused]), response([partial]),
            response([call('forged', 'set_conservation_goal', '{"request":{"daily_gallons":1}}')]),
            response([message('{"intent":"household_usage"}'), call()]),
            response([message('{"intent":"household_usage"}'), message('{"intent":"household_usage"}')]),
        ]
        invalid += [response([message(value)]) for value in (
            '', 'allow', '{"intent":"made_up"}', '{"intent":true}', '{"intent":[]}', 'null', '[]',
            '{"intent":"unsupported","intent":"household_usage"}',
            '{"intent":"household_usage","answer":"private answer"}',
            '{"intent":NaN}', '{"intent":"household_usage"} trailing',
            ' ' * 513 + '{"intent":"household_usage"}', '[' * 200 + ']' * 200,
        )]
        for index, reply in enumerate(invalid):
            with self.subTest(index=index):
                outcome, requests, tools, pauses = await self.run_script([reply])
                self.assertEqual((outcome.status, outcome.error), ('unavailable', 'topic_guard_unavailable'))
                self.assertEqual((outcome.answer, outcome.model_calls), ('', 1))
                self.assertEqual(len(requests), 1)
                self.assertEqual(pauses, [])
                self.assertNotIn('private', json.dumps(outcome.public_dict()))
                tools.discover.assert_not_awaited()
                tools.execute.assert_not_awaited()

    async def test_provider_failure_and_both_timeouts_stop_without_retry(self):
        async def slow(request):
            await asyncio.sleep(.1)
            return httpx2.Response(200, json=topic_response())

        async def disconnect(request):
            raise httpx2.ReadTimeout('private connection detail', request=request)

        for reply, config, status, error in (
            (httpx2.Response(429, json={'error': {'message': 'private detail', 'type': 'rate_limit_error'}}),
             AgentConfig(model='test-model'), 'unavailable', 'provider_rate_limited'),
            (httpx2.Response(500, json={'error': {'message': 'private detail'}}),
             AgentConfig(model='test-model'), 'unavailable', 'agent_dependency_unavailable'),
            (slow, AgentConfig(model='test-model', request_timeout_seconds=.01),
             'unconfirmed', 'run_or_request_timeout'),
            (slow, AgentConfig(model='test-model', run_timeout_seconds=.01),
             'unconfirmed', 'run_or_request_timeout'),
            (disconnect, AgentConfig(model='test-model'), 'unconfirmed', 'run_or_request_timeout'),
        ):
            with self.subTest(error=error, timeout=config.run_timeout_seconds):
                outcome, requests, tools, _ = await self.run_script([reply], config=config)
                self.assertEqual((outcome.status, outcome.error, outcome.model_calls), (status, error, 1))
                self.assertEqual(len(requests), 1)
                self.assertNotIn('private', json.dumps(outcome.public_dict()))
                tools.discover.assert_not_awaited()

    async def test_host_call_limit_cannot_be_expanded_by_guard_or_bill_mode(self):
        for bill in (False, True):
            outcome, requests, tools, _ = await self.run_script([topic_response()], bill=bill,
                config=AgentConfig(model='test-model', max_model_calls=1))
            self.assertEqual((outcome.status, outcome.error, outcome.model_calls),
                             ('limit_reached', 'model_call_budget_exhausted', 1))
            self.assertEqual(len(requests), 1)
            tools.discover.assert_not_awaited()

    async def test_liveness_after_guard_prevents_answer_and_tool_discovery(self):
        active = [True]

        def check_active():
            if not active[0]:
                raise RuntimeError('private expired session')

        async def revoke(request):
            active[0] = False
            return httpx2.Response(200, json=topic_response())

        outcome, requests, tools, _ = await self.run_script([revoke], check_active=check_active)
        self.assertEqual((outcome.status, outcome.answer, outcome.model_calls), ('unavailable', '', 1))
        self.assertEqual(len(requests), 1)
        tools.discover.assert_not_awaited()
        tools.execute.assert_not_awaited()
