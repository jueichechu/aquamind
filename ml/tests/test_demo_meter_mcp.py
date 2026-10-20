from pathlib import Path
import unittest

from mcp import Client

from aquamind_ml.demo_meter import DemoMeterStore
from aquamind_ml.mcp_server import create_server


class DemoMeterMcpTests(unittest.IsolatedAsyncioTestCase):
    async def test_bound_mcp_reads_selected_meter_and_weather_and_enforces_scope(self):
        store = DemoMeterStore()
        for scopes in (frozenset(), frozenset({'meter:read', 'weather:read'})):
            server = create_server(None, scopes, demo_meter=store, demo_scenario='irrigation-after-rain')
            async with Client(server) as client:
                tools = {tool.name: tool for tool in (await client.list_tools()).tools}
                for name in ('get_meter_summary', 'get_meter_series', 'get_weather_context'):
                    self.assertEqual(tools[name].input_schema.get('properties', {}), {})
                    self.assertTrue(tools[name].annotations.read_only_hint)
                    result = await client.call_tool(name, {})
                    self.assertEqual(result.is_error, not bool(scopes))
                    if scopes:
                        self.assertEqual(result.structured_content['scenario_id'], 'irrigation-after-rain')
                        self.assertEqual(result.structured_content['source'], 'synthetic')
                denied = await client.call_tool('detect_water_anomaly', {'request': {
                    'start_timestamp': '2026-06-21T00:00:00Z', 'flow_rates_gpm': [0] * 96}})
                self.assertTrue(denied.is_error)

    def test_invalid_or_ambiguous_host_binding_is_rejected(self):
        for kwargs in ({'demo_scenario': 'normal'},
                       {'demo_scenario': 'unknown', 'demo_meter': DemoMeterStore()},
                       {'demo_scenario': 'normal', 'demo_meter': DemoMeterStore(), 'meter_path': Path('unused-experiment.json')}):
            with self.assertRaises(ValueError):
                create_server(None, **kwargs)
