import asyncio
import json
import unittest

import httpx2
from mcp import Client
from openai import AsyncOpenAI

from aquamind_ml.agent import AgentConfig, POLICY, run_agent
from aquamind_ml.agent_tools import McpAgentTools
from aquamind_ml.approvals import GoalApprovals
from aquamind_ml.mcp_server import create_server


def response(output, status='completed'):
    return {'id': 'resp_test', 'object': 'response', 'created_at': 1,
            'model': 'test-model', 'status': status, 'output': output,
            'usage': {'input_tokens': 20, 'output_tokens': 10, 'total_tokens': 30,
                      'input_tokens_details': {'cached_tokens': 0},
                      'output_tokens_details': {'reasoning_tokens': 0}}}


def call(identifier='call_cost', name='estimate_water_cost', arguments='{"request":{"gallons":1000}}'):
    return {'id': 'fc_' + identifier, 'type': 'function_call', 'status': 'completed',
            'call_id': identifier, 'name': name, 'arguments': arguments}


def message(text):
    return {'id': 'msg_test', 'type': 'message', 'role': 'assistant', 'status': 'completed',
            'content': [{'type': 'output_text', 'text': text, 'annotations': []}]}


class AgentTests(unittest.IsolatedAsyncioTestCase):
    async def run_script(self, replies, *, allowed=frozenset({'estimate_water_cost'}),
                         scopes=frozenset({'utility:read'}), config=None, store=None):
        requests = []

        async def handle(request):
            requests.append(json.loads(request.content))
            reply = replies[min(len(requests) - 1, len(replies) - 1)]
            if callable(reply):
                return await reply(request)
            return httpx2.Response(200, json=reply)

        async with AsyncOpenAI(api_key='test-placeholder',
                               http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle))) as provider:
            async with Client(create_server(None, scopes, goal_approvals=store)) as mcp:
                bridge = McpAgentTools(mcp, allowed)
                outcome = await run_agent('A private water question', provider, bridge,
                                          config or AgentConfig(model='test-model'))
        return outcome, requests

    async def test_real_mcp_result_and_reasoning_replayed_through_sdk(self):
        reasoning = {'id': 'rs_test', 'type': 'reasoning', 'summary': [],
                     'encrypted_content': 'opaque-test-only'}
        outcome, requests = await self.run_script([
            response([reasoning, call()]), response([message('Using the illustrative rate, $5.00.')])])
        self.assertEqual(outcome.status, 'answer')
        self.assertEqual(outcome.model_calls, 2)
        self.assertEqual(len(outcome.tool_trace), 1)
        for request in requests:
            self.assertFalse(request['store'])
            self.assertFalse(request['parallel_tool_calls'])
            self.assertEqual(request['instructions'], POLICY)
            self.assertEqual(request['include'], ['reasoning.encrypted_content'])
            self.assertEqual([tool['name'] for tool in request['tools']], ['estimate_water_cost'])
        history = requests[1]['input']
        self.assertEqual(history[1], reasoning)
        self.assertEqual(history[2]['call_id'], 'call_cost')
        self.assertEqual(history[3]['type'], 'function_call_output')
        self.assertEqual(history[3]['call_id'], 'call_cost')
        tool_result = json.loads(history[3]['output'])
        self.assertEqual(tool_result['result']['estimated_water_cost_usd'], '5.00')
        public = json.dumps(outcome.public_dict())
        for private in ('opaque-test-only', 'A private water question', 'test-placeholder', 'gallons'):
            self.assertNotIn(private, public)
        self.assertEqual(outcome.model_trace[0]['output_tokens'], 10)

    async def test_proposal_stops_loop_and_cannot_approve(self):
        store = GoalApprovals()
        outcome, requests = await self.run_script([
            response([message('Approved and executed!'), call('call_goal', 'set_conservation_goal',
                      '{"request":{"daily_gallons":150}}')])],
            allowed=frozenset({'set_conservation_goal'}), scopes=frozenset({'goals:write'}), store=store)
        self.assertEqual(outcome.status, 'approval_required')
        self.assertEqual(outcome.answer, '')
        self.assertEqual(outcome.pending_approval['status'], 'approval_required')
        self.assertIsNone(store.goal)
        self.assertEqual(len(requests), 1)

    async def test_call_budget_and_unexpected_parallel_calls(self):
        outcome, requests = await self.run_script([response([call('call_one')]), response([call('call_two')])],
                                                 config=AgentConfig(model='test-model', max_model_calls=2))
        self.assertEqual(outcome.status, 'limit_reached')
        self.assertEqual(outcome.error, 'model_call_budget_exhausted')
        self.assertEqual(len(requests), 2)
        self.assertEqual(len(outcome.tool_trace), 2)
        outcome, _ = await self.run_script([response([call('one'), call('two')])])
        self.assertEqual(outcome.error, 'unexpected_parallel_calls')
        self.assertEqual(outcome.tool_trace, [])

    async def test_provider_errors_and_timeouts_are_sanitized_without_retry(self):
        async def limited(request):
            return httpx2.Response(429, json={'error': {'message': 'private provider detail',
                                                       'type': 'rate_limit_error', 'code': 'rate_limit_exceeded'}})

        outcome, requests = await self.run_script([limited])
        self.assertEqual(outcome.error, 'provider_rate_limited')
        self.assertEqual(len(requests), 1)
        self.assertNotIn('private provider detail', json.dumps(outcome.public_dict()))

        async def slow(request):
            await asyncio.sleep(.1)
            return httpx2.Response(200, json=response([message('too late')]))

        outcome, requests = await self.run_script([slow], config=AgentConfig(
            model='test-model', request_timeout_seconds=.01))
        self.assertEqual(outcome.status, 'unconfirmed')
        self.assertEqual(outcome.error, 'run_or_request_timeout')
        self.assertEqual(len(requests), 1)

        async def transport_timeout(request):
            raise httpx2.ReadTimeout('private connection detail', request=request)

        outcome, requests = await self.run_script([transport_timeout])
        self.assertEqual(outcome.status, 'unconfirmed')
        self.assertEqual(len(requests), 1)
        self.assertNotIn('private connection detail', json.dumps(outcome.public_dict()))

    async def test_incomplete_empty_and_refused_outputs_do_not_execute_tools(self):
        refusal = message('')
        refusal['content'] = [{'type': 'refusal', 'refusal': 'Cannot answer'}]
        for reply, status, error in (
            (response([call()], 'incomplete'), 'unavailable', 'model_response_incomplete'),
            (response([]), 'unavailable', 'empty_model_response'),
            (response([refusal]), 'refused', 'model_refusal'),
        ):
            with self.subTest(error=error):
                outcome, _ = await self.run_script([reply])
                self.assertEqual((outcome.status, outcome.error), (status, error))
                self.assertEqual(outcome.tool_trace, [])

    def test_config_limits(self):
        for kwargs in ({'model': ''}, {'model': 'model name'}, {'max_model_calls': 9},
                       {'max_output_tokens': 99999}, {'request_timeout_seconds': float('nan')}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                AgentConfig(**({'model': 'test-model'} | kwargs))
