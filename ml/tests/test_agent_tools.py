import asyncio
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

from mcp import Client, StdioServerParameters

from aquamind_ml.agent_tools import McpAgentTools
from aquamind_ml.approvals import GoalApprovals
from aquamind_ml.mcp_server import create_server


class AgentToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_discovery_and_real_execution(self):
        params = StdioServerParameters(command=sys.executable, args=['-m', 'aquamind_ml.mcp_server'], env={
            'PYTHONPATH': str(Path(__file__).resolve().parents[1]), 'AQUAMIND_MCP_SCOPES': 'utility:read'})
        async with asyncio.timeout(30), Client(params) as client:
            bridge = McpAgentTools(client, frozenset({'estimate_water_cost'}))
            tools = await bridge.discover()
            self.assertEqual([t['name'] for t in tools], ['estimate_water_cost'])
            self.assertFalse(tools[0]['strict'])
            tools[0]['name'] = 'modified'
            self.assertEqual((await bridge.discover())[0]['name'], 'estimate_water_cost')
            result = await bridge.execute('call_cost', 'estimate_water_cost', '{"request":{"gallons":1000}}')
            self.assertEqual(result.status, 'success')
            self.assertEqual(result.data['result']['estimated_water_cost_usd'], '5.00')
            output = result.response_output()
            self.assertEqual(output['type'], 'function_call_output')
            self.assertEqual(output['call_id'], 'call_cost')
            self.assertEqual(json.loads(output['output'])['status'], 'success')
            self.assertEqual(set(bridge.trace[0]), {'call_id', 'tool_name', 'status', 'elapsed_ms'})

    async def test_goal_is_pending_and_agent_has_no_approval_tool(self):
        store = GoalApprovals()
        async with Client(create_server(None, frozenset({'goals:write'}), goal_approvals=store)) as client:
            bridge = McpAgentTools(client, frozenset({'set_conservation_goal'}))
            await bridge.discover()
            result = await bridge.execute('call_goal', 'set_conservation_goal', '{"request":{"daily_gallons":150}}')
            self.assertEqual(result.status, 'approval_required')
            self.assertIsNone(store.goal)
            duplicate = await bridge.execute('call_goal', 'set_conservation_goal', '{"request":{"daily_gallons":150}}')
            self.assertEqual(duplicate.data['error'], 'duplicate_call_id')
            denied = await bridge.execute('call_approve', 'approve_goal', '{}')
            self.assertEqual(denied.data['error'], 'tool_not_allowed')
            self.assertIsNone(store.goal)
        with self.assertRaises(ValueError):
            McpAgentTools(AsyncMock(), frozenset({'approve_goal'}))

    async def test_concurrent_duplicate_calls_create_one_proposal(self):
        store = GoalApprovals()
        async with Client(create_server(None, frozenset({'goals:write'}), goal_approvals=store)) as client:
            bridge = McpAgentTools(client, frozenset({'set_conservation_goal'}))
            await bridge.discover()
            with patch.object(store, 'propose', wraps=store.propose) as propose:
                results = await asyncio.gather(*(
                    bridge.execute('same_call', 'set_conservation_goal', '{"request":{"daily_gallons":150}}')
                    for _ in range(2)))
                self.assertEqual(propose.call_count, 1)
            self.assertEqual(sorted(r.status for r in results), ['approval_required', 'error'])
            self.assertIsNone(store.goal)

    async def test_malformed_arguments_and_budgets(self):
        async with Client(create_server(None, frozenset({'utility:read'}))) as client:
            bridge = McpAgentTools(client, frozenset({'estimate_water_cost'}), max_calls=6)
            await bridge.discover()
            for index, arguments in enumerate(('[]', '{bad', '{"request":{"gallons":NaN}}',
                    '{"request":{"gallons":1,"gallons":2}}', '{"secret":"sensitive"}', 'x' * 32769)):
                result = await bridge.execute(f'bad_{index}', 'estimate_water_cost', arguments)
                self.assertEqual(result.data['error'], 'invalid_arguments')
            exhausted = await bridge.execute('final', 'estimate_water_cost', '{"request":{"gallons":1}}')
            self.assertEqual(exhausted.data['error'], 'tool_budget_exhausted')
            self.assertNotIn('sensitive', json.dumps(bridge.trace))

    async def test_mcp_scope_remains_authoritative(self):
        async with Client(create_server(None)) as client:
            bridge = McpAgentTools(client, frozenset({'get_utility_rate'}))
            await bridge.discover()
            result = await bridge.execute('denied', 'get_utility_rate', '{}')
            self.assertEqual(result.status, 'error')
            self.assertEqual(result.data['error'], 'mcp_tool_error')

    async def test_timeout_and_failure_never_retry_or_leak_exception_details(self):
        client = AsyncMock()
        async with Client(create_server(None, frozenset({'utility:read'}))) as discovery_client:
            bridge = McpAgentTools(discovery_client, frozenset({'get_utility_rate'}), timeout_seconds=.02)
            await bridge.discover()
        bridge.client = client
        async def slow(*args, **kwargs):
            await asyncio.sleep(.1)
        client.call_tool.side_effect = slow
        result = await bridge.execute('timeout', 'get_utility_rate', '{}')
        self.assertEqual(result.status, 'unconfirmed')
        self.assertFalse(result.data['retry_automatically'])
        self.assertEqual(client.call_tool.await_count, 1)
        client.call_tool.side_effect = RuntimeError('secret internal connection detail')
        result = await bridge.execute('failure', 'get_utility_rate', '{}')
        self.assertEqual(result.status, 'unconfirmed')
        self.assertNotIn('secret', json.dumps(result.response_output()))
        self.assertEqual(client.call_tool.await_count, 2)
