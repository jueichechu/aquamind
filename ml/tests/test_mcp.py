import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest

from mcp import Client, StdioServerParameters

from aquamind_ml.data import load_dataset
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
                self.assertEqual([tool.name for tool in tools.tools], ["detect_water_anomaly"])
                self.assertIsNotNone(tools.tools[0].output_schema)
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
