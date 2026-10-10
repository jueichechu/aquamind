import asyncio
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

from mcp import Client, StdioServerParameters
from pydantic import ValidationError

from aquamind_ml.meter import MeterQuery, MeterStore
from aquamind_ml.mcp_server import create_server
from test_data import fixture


class MeterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "meter.json"
        self.path.write_text(json.dumps(fixture()))
        self.query = {"seed": 2, "scenario_id": "normal", "start_timestamp": "2026-06-15T00:00:00Z"}

    def test_units_provenance_and_immutable_snapshot(self):
        store = MeterStore(self.path)
        series = store.series(MeterQuery(**self.query))
        self.assertEqual(series.flow_rates_gpm, [0.0, 2.0] * 48)
        self.assertEqual(series.total_gallons, 1440)
        self.assertEqual(series.mean_flow_gpm, 1)
        self.assertEqual(series.peak_interval_flow_gpm, 2)
        self.assertEqual(series.end_timestamp_exclusive, "2026-06-16T00:00:00+00:00")
        self.assertEqual(series.dataset_sha256, hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(series.source, "synthetic")
        self.assertEqual(store.summary(MeterQuery(**self.query)).model_dump(),
                         series.model_dump(exclude={"flow_rates_gpm"}))
        self.assertTrue({"has_leak", "has_anomaly"}.isdisjoint(series.model_dump()))
        series.flow_rates_gpm[0] = 999
        self.assertEqual(store.series(MeterQuery(**self.query)).flow_rates_gpm[0], 0)
        with self.assertRaises(LookupError):
            store.series(MeterQuery(**(self.query | {"seed": 99})))

    def test_invalid_queries(self):
        for patch in ({"seed": True}, {"seed": "2"}, {"seed": -1}, {"seed": 2**32},
                      {"scenario_id": "unknown"}, {"start_timestamp": "invalid"},
                      {"start_timestamp": "2026-06-15T00:00:00"},
                      {"start_timestamp": "2026-06-15T00:00:00-07:00"},
                      {"path": "/etc/passwd"}, {"scopes": ["meter:read"]}):
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                MeterQuery(**(self.query | patch))

    async def test_stdio_reads_both_tools_without_anomaly_permission(self):
        params = StdioServerParameters(command=sys.executable, args=["-m", "aquamind_ml.mcp_server"],
                env={"PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                     "AQUAMIND_METER_DATASET_PATH": str(self.path), "AQUAMIND_MCP_SCOPES": "meter:read"})
        async with asyncio.timeout(30), Client(params) as client:
            for name in ("get_meter_series", "get_meter_summary"):
                result = await client.call_tool(name, {"request": self.query})
                self.assertFalse(result.is_error)
                self.assertEqual(result.structured_content["total_gallons"], 1440)
                self.assertEqual(result.structured_content["source"], "synthetic")
            denied = await client.call_tool("detect_water_anomaly", {"request": {
                "start_timestamp": self.query["start_timestamp"], "flow_rates_gpm": [0] * 96}})
            self.assertTrue(denied.is_error)
            self.assertIn("Permission denied", str(denied.content))

    async def test_permissions_failures_and_missing_windows(self):
        cases = [
            (frozenset(), self.path, self.query, "Permission denied"),
            (frozenset({"anomaly:read"}), self.path, self.query, "Permission denied"),
            (frozenset({"meter:read"}), None, self.query, "unavailable"),
            (frozenset({"meter:read"}), self.path.parent / "absent", self.query, "unavailable"),
            (frozenset({"meter:read"}), self.path, self.query | {"seed": 99}, "not found"),
        ]
        for scopes, path, query, message in cases:
            async with Client(create_server(None, scopes, path)) as client:
                for name in ("get_meter_series", "get_meter_summary"):
                    result = await client.call_tool(name, {"request": query})
                    self.assertTrue(result.is_error)
                    self.assertIn(message, str(result.content))
        self.path.write_text("invalid json")
        async with Client(create_server(None, frozenset({"meter:read"}), self.path)) as client:
            result = await client.call_tool("get_meter_series", {"request": self.query})
            self.assertTrue(result.is_error)
            self.assertIn("unavailable", str(result.content))
