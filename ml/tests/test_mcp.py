import asyncio
import json
from pathlib import Path
from threading import Lock
import sys
import tempfile
import unittest
from unittest.mock import patch

from mcp import Client, StdioServerParameters

from aquamind_ml.data import load_dataset, MeterWindow
from aquamind_ml.demo_meter import DemoMeterStore, SCENARIOS
from aquamind_ml.detector import FrozenDetector, freeze_detector
from aquamind_ml.mcp_server import create_server
from aquamind_ml.train import TrainingConfig, train_to_directory
from test_data import fixture


class McpTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        root = Path(cls.directory.name)
        path = root / "data.json"
        raw = fixture()
        raw["validation"].append(dict(raw["validation"][0], scenarioId="overnight-leak",
                                     hasAnomaly=True, hasLeak=True, flowRatesGpm=[3.0] * 96))
        path.write_text(json.dumps(raw))
        train_to_directory(path, root / "training", TrainingConfig(epochs=1, hidden_size=4, latent_size=2))
        cls.detector_path = root / "detector"
        freeze_detector(path, root / "training", cls.detector_path)
        cls.window = load_dataset(path).test[0]
        cls.arguments = {"request": {"start_timestamp": cls.window.start_timestamp,
                                     "flow_rates_gpm": list(cls.window.flow_rates_gpm)}}

    async def test_stdio_protocol_and_prediction(self):
        params = StdioServerParameters(command=sys.executable, args=["-m", "aquamind_ml.mcp_server"],
                env={"PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                     "AQUAMIND_DETECTOR_PATH": str(self.detector_path), "AQUAMIND_MCP_SCOPES": "anomaly:read"})
        async with asyncio.timeout(30):
            async with Client(params) as client:
                tools = await client.list_tools()
                self.assertEqual({tool.name for tool in tools.tools},
                                 {"detect_water_anomaly", "get_meter_series", "get_meter_summary",
                                  "get_utility_rate", "estimate_water_cost", "estimate_conservation_savings",
                                  "get_weather_context", "set_conservation_goal"})
                self.assertTrue(all(tool.output_schema is not None for tool in tools.tools))
                result = await client.call_tool("detect_water_anomaly", self.arguments)
                self.assertFalse(result.is_error)
                expected = FrozenDetector(self.detector_path).predict((self.window,))[0]
                for key, value in expected.items():
                    self.assertEqual(result.structured_content[key], value)

    async def test_scope_denial_and_model_failure(self):
        for server, message in ((create_server(self.detector_path), "Permission denied"),
                                (create_server(None, frozenset({"anomaly:read"})), "unavailable")):
            async with Client(server) as client:
                result = await client.call_tool("detect_water_anomaly", self.arguments)
                self.assertTrue(result.is_error)
                self.assertIn(message, str(result.content))

    async def test_malformed_input_cannot_grant_scope(self):
        async with Client(create_server(self.detector_path)) as client:
            for arguments in ({}, {"request": self.arguments["request"] | {"scopes": ["anomaly:read"]}},
                              {"request": self.arguments["request"] | {"flow_rates_gpm": [0] * 95}}):
                result = await client.call_tool("detect_water_anomaly", arguments)
                self.assertTrue(result.is_error)

    async def test_selected_demo_predictions_match_frozen_model_without_labels(self):
        detector, meter, lock = FrozenDetector(self.detector_path), DemoMeterStore(), Lock()
        for scenario in sorted(SCENARIOS):
            series = meter.series(scenario)
            window = MeterWindow(tuple(series.flow_rates_gpm), 0, 'normal', False, False,
                                 series.start_timestamp, '2026-06-21T23:45:00+00:00')
            expected = detector.predict((window,))[0]

            def predict(windows):
                self.assertTrue(lock.locked())
                self.assertEqual(windows, (window,))
                return [expected]

            server = create_server(None, frozenset({'meter:read', 'anomaly:read'}),
                demo_meter=meter, demo_scenario=scenario, detector=detector, detector_lock=lock)
            with patch.object(detector, 'predict', side_effect=predict) as prediction:
                async with Client(server) as client:
                    tool = next(tool for tool in (await client.list_tools()).tools
                                if tool.name == 'detect_water_anomaly')
                    self.assertEqual(tool.input_schema.get('properties', {}), {})
                    self.assertTrue(tool.annotations.read_only_hint)
                    result = await client.call_tool('detect_water_anomaly', {})
                self.assertFalse(result.is_error)
                data = result.structured_content
                for key, value in expected.items():
                    self.assertEqual(data[key], value)
                self.assertEqual(data['threshold'], detector.manifest['threshold'])
                self.assertEqual(data['dataset_sha256'], meter.sha256)
                self.assertEqual(data['scenario_id'], scenario)
                self.assertEqual(data['source'], 'synthetic')
                self.assertEqual(data['training_data'], 'synthetic')
                self.assertEqual(data['start_timestamp'], series.start_timestamp)
                self.assertEqual(data['end_timestamp_exclusive'], series.end_timestamp_exclusive)
                self.assertIn('not proof of a physical leak', data['interpretation'])
                self.assertIn('not a probability', data['interpretation'])
                prediction.assert_called_once()
                self.assertFalse(lock.locked())

    async def test_selected_anomaly_requires_both_scopes_and_an_available_model(self):
        meter, detector = DemoMeterStore(), FrozenDetector(self.detector_path)
        for scopes in (frozenset(), frozenset({'meter:read'}), frozenset({'anomaly:read'})):
            with patch.object(detector, 'predict') as prediction:
                async with Client(create_server(None, scopes, demo_meter=meter,
                        demo_scenario='normal', detector=detector)) as client:
                    result = await client.call_tool('detect_water_anomaly', {})
                self.assertTrue(result.is_error)
                self.assertIn('Permission denied', str(result.content))
                prediction.assert_not_called()
        scopes = frozenset({'meter:read', 'anomaly:read'})
        async with Client(create_server(None, scopes, demo_meter=meter, demo_scenario='normal')) as client:
            result = await client.call_tool('detect_water_anomaly', {})
            self.assertTrue(result.is_error)
            self.assertIn('unavailable', str(result.content))
        with patch.object(detector, 'predict', side_effect=RuntimeError('private model path')):
            async with Client(create_server(None, scopes, demo_meter=meter,
                    demo_scenario='normal', detector=detector)) as client:
                result = await client.call_tool('detect_water_anomaly', {})
                self.assertTrue(result.is_error)
                self.assertNotIn('private model path', str(result.content))
        with self.assertRaises(ValueError):
            create_server(self.detector_path, scopes, detector=detector)
