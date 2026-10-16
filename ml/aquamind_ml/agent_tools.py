"""Bounded MCP execution for an agent host; contains no LLM or approval authority."""

import asyncio
from copy import deepcopy
from dataclasses import dataclass
import json
import math
import re
from time import perf_counter

from mcp import Client

AGENT_TOOLS = frozenset({'get_meter_summary', 'get_meter_series', 'detect_water_anomaly',
                         'get_weather_context', 'get_utility_rate', 'estimate_water_cost',
                         'estimate_conservation_savings', 'set_conservation_goal'})


def _reject_constant(value):
    raise ValueError('Non-finite JSON number')


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


@dataclass(frozen=True)
class ToolOutcome:
    call_id: str
    status: str
    data: dict

    def response_output(self) -> dict:
        return {'type': 'function_call_output', 'call_id': self.call_id,
                'output': json.dumps({'status': self.status, **self.data}, allow_nan=False)}


class McpAgentTools:
    """One instance per host-owned agent run; allowed tools cannot expand mid-run."""

    def __init__(self, client: Client, allowed_tools: frozenset[str] = frozenset(), *,
                 max_calls: int = 8, timeout_seconds: float = 10):
        if (type(max_calls) is not int or not 1 <= max_calls <= 16 or
                not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 30):
            raise ValueError('Invalid tool execution limits')
        self.allowed_tools = frozenset(allowed_tools)
        if self.allowed_tools - AGENT_TOOLS:
            raise ValueError('Unsupported agent tools')
        self.client = client
        self.max_calls, self.timeout_seconds = max_calls, timeout_seconds
        self._catalog = None
        self._calls = 0
        self._seen = set()
        self._lock = asyncio.Lock()
        self._trace = []

    @property
    def trace(self) -> list[dict]:
        # No raw tool arguments, outputs, headers, tokens or model reasoning.
        return deepcopy(self._trace)

    async def discover(self) -> list[dict]:
        if self._catalog is None:
            catalog = {}
            cursor = None
            async with asyncio.timeout(self.timeout_seconds):
                for _ in range(4):
                    listing = await self.client.list_tools(cursor=cursor)
                    for tool in listing.tools:
                        if tool.name in self.allowed_tools:
                            if tool.name in catalog:
                                raise ValueError('Duplicate MCP tool')
                            catalog[tool.name] = {'type': 'function', 'name': tool.name,
                                'description': tool.description or '',
                                'parameters': deepcopy(tool.input_schema), 'strict': False}
                    cursor = listing.next_cursor
                    if cursor is None:
                        break
                else:
                    raise ValueError('MCP discovery page limit exceeded')
            if self.allowed_tools - catalog.keys():
                raise ValueError('Allowed MCP tool missing from discovery')
            self._catalog = catalog
        return deepcopy(list(self._catalog.values()))

    async def execute(self, call_id: str, name: str, arguments_json: str) -> ToolOutcome:
        if not isinstance(call_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', call_id):
            raise ValueError('Invalid call ID')
        async with self._lock:
            started = perf_counter()

            def outcome(status, data):
                event = {'call_id': call_id,
                    'tool_name': name if name in self.allowed_tools else 'unrecognized_tool',
                    'status': status, 'elapsed_ms': round((perf_counter() - started) * 1000, 3)}
                if len(self._trace) < 2 * self.max_calls + 4:
                    self._trace.append(event)
                return ToolOutcome(call_id, status, data)

            if call_id in self._seen:
                return outcome('error', {'error': 'duplicate_call_id'})
            if self._calls >= self.max_calls:
                return outcome('error', {'error': 'tool_budget_exhausted'})
            self._seen.add(call_id)
            self._calls += 1
            if self._catalog is None:
                return outcome('error', {'error': 'tools_not_discovered'})
            if name not in self._catalog:
                return outcome('error', {'error': 'tool_not_allowed'})
            try:
                if not isinstance(arguments_json, str) or len(arguments_json.encode()) > 32768:
                    raise ValueError('Argument size limit')
                arguments = json.loads(arguments_json, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
                if not isinstance(arguments, dict):
                    raise ValueError('Expected argument object')
                # Reject extra root arguments before the server's Pydantic validation.
                if arguments.keys() - self._catalog[name]['parameters'].get('properties', {}).keys():
                    raise ValueError('Unknown argument')
            except (ValueError, TypeError, RecursionError):
                return outcome('error', {'error': 'invalid_arguments'})
            try:
                async with asyncio.timeout(self.timeout_seconds):
                    result = await self.client.call_tool(name, arguments, read_timeout_seconds=self.timeout_seconds)
                if result.is_error:
                    return outcome('error', {'error': 'mcp_tool_error'})
                data = result.structured_content
                if not isinstance(data, dict):
                    return outcome('error', {'error': 'invalid_tool_result'})
                if len(json.dumps(data, allow_nan=False).encode()) > 65536:
                    return outcome('error', {'error': 'tool_result_too_large'})
                if name == 'set_conservation_goal':
                    if data.get('status') != 'approval_required' or not isinstance(data.get('approval_id'), str):
                        return outcome('unconfirmed', {'error': 'unexpected_approval_result'})
                    return outcome('approval_required', {'result': data})
                return outcome('success', {'result': data})
            except TimeoutError:
                return outcome('unconfirmed', {'error': 'tool_timeout', 'retry_automatically': False})
            except Exception:
                return outcome('unconfirmed', {'error': 'tool_unavailable', 'retry_automatically': False})
