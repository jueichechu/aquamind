import asyncio
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

from mcp import Client, StdioServerParameters
from aquamind_ml.mcp_server import create_server
from aquamind_ml.weather import DEFAULT_WEATHER_PATH, WeatherQuery, WeatherStore


class WeatherTests(unittest.IsolatedAsyncioTestCase):
    def test_shared_values_and_provenance(self):
        store = WeatherStore(DEFAULT_WEATHER_PATH)
        for scenario, rain, temperature in (("normal", 0, 76), ("overnight-leak", 0, 72),
                                           ("running-toilet", 0, 74), ("irrigation-after-rain", .68, 69)):
            result = store.context(WeatherQuery(scenario_id=scenario))
            self.assertEqual(result.rainfall_inches_last_24h, rain)
            self.assertEqual(result.temperature_f, temperature)
            self.assertEqual(result.source, "synthetic")
            self.assertEqual(result.snapshot_sha256, hashlib.sha256(DEFAULT_WEATHER_PATH.read_bytes()).hexdigest())

    def test_invalid_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "weather.json"
            for patch in ({"schemaVersion": True}, {"schemaVersion": 2}, {"source": "live"},
                          {"scenarios": {}}, {"unexpected": 1}):
                raw = json.loads(DEFAULT_WEATHER_PATH.read_text()) | patch
                path.write_text(json.dumps(raw))
                with self.assertRaises(ValueError):
                    WeatherStore(path)
            for field, value in (("rainfallInchesLast24h", -1), ("temperatureF", "69"),
                                 ("temperatureF", 999), ("rainfallInchesLast24h", True)):
                raw = json.loads(DEFAULT_WEATHER_PATH.read_text())
                raw["scenarios"]["normal"][field] = value
                path.write_text(json.dumps(raw))
                with self.assertRaises(ValueError):
                    WeatherStore(path)

    async def test_stdio_weather_and_invalid_requests(self):
        params = StdioServerParameters(command=sys.executable, args=["-m", "aquamind_ml.mcp_server"],
                env={"PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                     "AQUAMIND_MCP_SCOPES": "weather:read"})
        async with asyncio.timeout(30), Client(params) as client:
            result = await client.call_tool("get_weather_context", {"request": {"scenario_id": "irrigation-after-rain"}})
            self.assertFalse(result.is_error)
            self.assertEqual(result.structured_content["rainfall_inches_last_24h"], .68)
            self.assertEqual(result.structured_content["source"], "synthetic")
            for request in ({"scenario_id": "unknown"}, {"scenario_id": "normal", "date": "2026-10-09"},
                            {"scenario_id": "normal", "scopes": ["weather:read"]}):
                result = await client.call_tool("get_weather_context", {"request": request})
                self.assertTrue(result.is_error)
            result = await client.call_tool("get_utility_rate", {})
            self.assertTrue(result.is_error)
            self.assertIn("Permission denied", str(result.content))

    async def test_scope_and_unavailable_snapshot(self):
        for scopes in (frozenset(), frozenset({"meter:read", "utility:read", "anomaly:read"})):
            async with Client(create_server(None, scopes)) as client:
                result = await client.call_tool("get_weather_context", {"request": {"scenario_id": "normal"}})
                self.assertTrue(result.is_error)
                self.assertIn("weather:read required", str(result.content))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.json"
            for contents in (None, "invalid json"):
                if contents is not None:
                    path.write_text(contents)
                async with Client(create_server(None, frozenset({"weather:read"}), weather_path=path)) as client:
                    result = await client.call_tool("get_weather_context", {"request": {"scenario_id": "normal"}})
                    self.assertTrue(result.is_error)
                    self.assertIn("unavailable", str(result.content))
