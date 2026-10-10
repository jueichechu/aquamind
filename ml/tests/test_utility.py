import asyncio
from pathlib import Path
import sys
import unittest

from mcp import Client, StdioServerParameters
from pydantic import ValidationError

from aquamind_ml.mcp_server import create_server
from aquamind_ml.utility import CostRequest, SavingsRequest, estimate_cost, estimate_savings


class UtilityTests(unittest.IsolatedAsyncioTestCase):
    def test_cost_units_and_cent_rounding(self):
        for gallons, expected in ((0, "0.00"), (1, "0.01"), (0.99, "0.00"),
                                  (1000, "5.00"), (1440, "7.20"), (1_000_000, "5000.00")):
            with self.subTest(gallons=gallons):
                result = estimate_cost(CostRequest(gallons=gallons))
                self.assertEqual(result.estimated_water_cost_usd, expected)
                self.assertEqual(result.rate.source, "illustrative_assumption")
                self.assertIn("sewer", result.rate.exclusions)

    def test_savings_duration_and_round_only_after_subtraction(self):
        request = SavingsRequest(baseline_daily_gallons=200, proposed_daily_gallons=150, days=30)
        result = estimate_savings(request)
        self.assertEqual(result.saved_gallons, 1500)
        self.assertEqual(result.estimated_water_savings_usd, "7.50")
        fractional = estimate_savings(SavingsRequest(baseline_daily_gallons=1,
                                                     proposed_daily_gallons=0.9, days=1))
        self.assertEqual(fractional.saved_gallons, 0.1)
        self.assertEqual(fractional.estimated_water_savings_usd, "0.00")
        unchanged = estimate_savings(SavingsRequest(baseline_daily_gallons=100,
                                                    proposed_daily_gallons=100, days=366))
        self.assertEqual(unchanged.estimated_water_savings_usd, "0.00")

    def test_invalid_inputs(self):
        for bad in (True, "100", -1, float("nan"), float("inf"), 1_000_001):
            with self.subTest(value=bad), self.assertRaises(ValidationError):
                CostRequest(gallons=bad)
            for field in ("baseline_daily_gallons", "proposed_daily_gallons"):
                values = {"baseline_daily_gallons": 100, "proposed_daily_gallons": 50, "days": 30}
                with self.assertRaises(ValidationError):
                    SavingsRequest(**(values | {field: bad}))
        for days in (0, 367, True, "30", 1.5):
            with self.assertRaises(ValidationError):
                SavingsRequest(baseline_daily_gallons=100, proposed_daily_gallons=50, days=days)
        with self.assertRaises(ValidationError):
            SavingsRequest(baseline_daily_gallons=50, proposed_daily_gallons=100, days=30)
        with self.assertRaises(ValidationError):
            CostRequest(gallons=100, dollars_per_1000_gallons=0)

    async def test_stdio_three_utility_tools(self):
        params = StdioServerParameters(command=sys.executable, args=["-m", "aquamind_ml.mcp_server"],
                env={"PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                     "AQUAMIND_MCP_SCOPES": "utility:read"})
        async with asyncio.timeout(30), Client(params) as client:
            rate = await client.call_tool("get_utility_rate", {})
            self.assertFalse(rate.is_error)
            self.assertEqual(rate.structured_content["dollars_per_1000_gallons"], "5.00")
            cost = await client.call_tool("estimate_water_cost", {"request": {"gallons": 1000}})
            self.assertFalse(cost.is_error)
            self.assertEqual(cost.structured_content["estimated_water_cost_usd"], "5.00")
            savings = await client.call_tool("estimate_conservation_savings", {"request": {
                "baseline_daily_gallons": 200, "proposed_daily_gallons": 150, "days": 30}})
            self.assertFalse(savings.is_error)
            self.assertEqual(savings.structured_content["estimated_water_savings_usd"], "7.50")
            malformed = await client.call_tool("estimate_water_cost", {"request": {"gallons": -1}})
            self.assertTrue(malformed.is_error)
            denied = await client.call_tool("get_meter_summary", {"request": {
                "seed": 0, "scenario_id": "normal", "start_timestamp": "2026-06-15T00:00:00Z"}})
            self.assertTrue(denied.is_error)
            self.assertIn("Permission denied", str(denied.content))

    async def test_scope_required_for_every_tool(self):
        calls = [("get_utility_rate", {}), ("estimate_water_cost", {"request": {"gallons": 1}}),
                 ("estimate_conservation_savings", {"request": {
                     "baseline_daily_gallons": 2, "proposed_daily_gallons": 1, "days": 1}})]
        for scopes in (frozenset(), frozenset({"meter:read", "anomaly:read"})):
            async with Client(create_server(None, scopes)) as client:
                for name, arguments in calls:
                    result = await client.call_tool(name, arguments)
                    self.assertTrue(result.is_error)
                    self.assertIn("utility:read required", str(result.content))
                result = await client.call_tool("estimate_water_cost", {
                    "request": {"gallons": 1, "scopes": ["utility:read"]}})
                self.assertTrue(result.is_error)
