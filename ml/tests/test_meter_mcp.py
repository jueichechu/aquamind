import json
import unittest

from mcp import Client

from aquamind_ml.agent_tools import McpAgentTools
from aquamind_ml.meter_import import MeterImportRequest, parse_meter_csv
from aquamind_ml.meter_mcp import create_imported_meter_server
from aquamind_ml.sessions import DemoSessions
from test_meter_import import meter_body


class ImportedMeterMcpTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = [0.0]
        self.sessions = DemoSessions(clock=lambda: self.now[0])
        self.token = self.sessions.create()
        self.store = self.sessions.meters(self.token)
        self.data = parse_meter_csv(MeterImportRequest.model_validate(meter_body(count=672, volume_unit='liters')))
        self.ref = self.store.replace(self.data).context.evidence_id
        self.addCleanup(self.sessions.close)

    async def test_actual_mcp_and_agent_adapter_are_bounded_and_source_aware(self):
        async with Client(create_imported_meter_server(self.store, self.ref, frozenset({'meter:read'}))) as client:
            catalog = (await client.list_tools()).tools
            self.assertEqual({tool.name for tool in catalog}, {'get_meter_summary', 'get_meter_series'})
            for tool in catalog:
                self.assertEqual(tool.input_schema.get('properties', {}), {})
                self.assertTrue(tool.annotations.read_only_hint)
            adapter = McpAgentTools(client, frozenset({'get_meter_summary', 'get_meter_series'}))
            await adapter.discover()
            for index, tool in enumerate(('get_meter_summary', 'get_meter_series')):
                result = await adapter.execute(f'call_{index}', tool, '{}')
                self.assertEqual(result.status, 'success')
                data = result.data['result']
                self.assertEqual(data['context']['origin'], 'user_provided')
                self.assertEqual(data['context']['volume_unit'], 'liters')
                self.assertEqual(data['inference_status'], 'not_enabled_for_imported_data')
                self.assertLess(len(json.dumps(data).encode()), 65536)
                if tool == 'get_meter_series':
                    self.assertEqual(len(data['interval_volumes_us_gallons']), 672)
                    self.assertEqual(data['interval_volumes_us_gallons'][0], '0.264172')
            rejected = await adapter.execute('forged', 'get_meter_summary', '{"evidence_id":"meter_other"}')
            self.assertEqual(rejected.status, 'error')
            self.assertNotIn(self.ref, str(adapter.trace))

    async def test_no_scope_and_no_weather_model_utility_or_write_authority(self):
        async with Client(create_imported_meter_server(self.store, self.ref)) as client:
            for name in ('get_meter_summary', 'get_meter_series'):
                self.assertTrue((await client.call_tool(name, {})).is_error)
        for scope in ('weather:read', 'anomaly:read', 'utility:read', 'goals:write'):
            with self.assertRaises(ValueError):
                create_imported_meter_server(self.store, self.ref, frozenset({scope}))
        other = self.sessions.meters(self.sessions.create())
        other.replace(self.data)
        with self.assertRaises(LookupError):
            create_imported_meter_server(other, self.ref, frozenset({'meter:read'}))

    async def test_bound_server_never_follows_replacement_clear_revoke_or_expiry(self):
        for ending in ('replace', 'clear', 'revoke', 'expire'):
            token = self.sessions.create()
            store = self.sessions.meters(token)
            ref = store.replace(self.data).context.evidence_id
            async with Client(create_imported_meter_server(store, ref, frozenset({'meter:read'}))) as client:
                if ending == 'replace':
                    store.replace(self.data)
                elif ending == 'clear':
                    store.clear()
                elif ending == 'revoke':
                    self.sessions.revoke(token)
                else:
                    self.now[0] += 3600
                for name in ('get_meter_summary', 'get_meter_series'):
                    self.assertTrue((await client.call_tool(name, {})).is_error, ending)


if __name__ == '__main__':
    unittest.main()
