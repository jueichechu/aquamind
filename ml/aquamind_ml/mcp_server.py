"""Local MCP tools with host-owned scopes and approval-only goal proposals."""

import logging
import os
from pathlib import Path
from threading import Lock
from uuid import uuid4
from datetime import datetime, timedelta

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
import torch

from .api import PredictionRequest, PredictionResponse
from .data import MeterWindow
from .detector import FrozenDetector
from .approvals import ApprovalSessionUnavailable, GoalApprovals, GoalProposal, GoalRequest
from .meter import MeterQuery, MeterSeries, MeterStore, MeterSummary
from .demo_meter import DemoMeterStore, DemoMeterSummary, DemoMeterSeries
from .weather import DEFAULT_WEATHER_PATH, WeatherContext, WeatherQuery, WeatherStore
from .weather import ScenarioId
from .utility import (CostRequest, CostEstimate, SavingsRequest, SavingsEstimate,
                      UtilityRate, estimate_cost, estimate_savings)


def create_server(detector_path: Path | None, scopes: frozenset[str] = frozenset(),
                  meter_path: Path | None = None,
                  weather_path: Path = DEFAULT_WEATHER_PATH,
                  goal_approvals: GoalApprovals | None = None, *,
                  demo_meter: DemoMeterStore | None = None,
                  demo_scenario: ScenarioId | None = None) -> MCPServer:
    if demo_scenario is not None:
        demo_scenario = WeatherQuery(scenario_id=demo_scenario).scenario_id
        if demo_meter is None or meter_path is not None:
            raise ValueError('Demo meter requires one host-selected snapshot')
    # Copy policy into this server; it cannot be changed through an MCP request.
    granted_scopes = frozenset(scopes)
    if granted_scopes - {"anomaly:read", "meter:read", "utility:read", "weather:read", "goals:write"}:
        raise ValueError("Unsupported MCP scope")
    server = MCPServer("AquaMind", version="0.1.0", log_level="WARNING")
    approvals = goal_approvals if goal_approvals is not None else GoalApprovals()

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                           idempotentHint=False, openWorldHint=False))
    def set_conservation_goal(request: GoalRequest) -> GoalProposal:
        """Propose a daily water goal; requires goals:write and human approval.

        Returns approval_required, not an executed goal. Only the trusted host can
        approve the exact proposal. Never claim the goal changed from this result.
        No plumbing equipment is controlled. Proposals expire after ten minutes.
        """
        if "goals:write" not in granted_scopes:
            raise ToolError("Permission denied: goals:write required")
        try:
            return approvals.propose(request)
        except ApprovalSessionUnavailable:
            raise ToolError("Session unavailable") from None
        except ValueError:
            raise ToolError("Goal proposal unavailable") from None

    detector = None
    if detector_path is not None and "anomaly:read" in granted_scopes:
        try:
            detector = FrozenDetector(detector_path)
        except Exception:
            logging.getLogger(__name__).error("AquaMind MCP detector unavailable")
    lock = Lock()
    weather = None
    if "weather:read" in granted_scopes:
        try:
            weather = WeatherStore(weather_path)
        except Exception:
            logging.getLogger(__name__).error("AquaMind MCP weather context unavailable")

    def weather_context(request: WeatherQuery) -> WeatherContext:
        """Read synthetic rainfall and temperature for the selected demo scenario.

        Requires weather:read. Static scenario context, not live weather, a forecast,
        or an observation for a real location/date. Rainfall alone does not prove
        irrigation is unnecessary; soil, plants and local conditions also matter.
        """
        if "weather:read" not in granted_scopes:
            raise ToolError("Permission denied: weather:read required")
        if weather is None:
            raise ToolError("Weather context unavailable")
        return weather.context(request)

    read_only = ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                idempotentHint=True, openWorldHint=False)
    if demo_scenario is not None:
        @server.tool(annotations=read_only)
        def get_weather_context() -> WeatherContext:
            """Read synthetic weather for the host-selected demo scenario, not live weather."""
            return weather_context(WeatherQuery(scenario_id=demo_scenario))
    else:
        server.tool(name='get_weather_context', annotations=read_only)(weather_context)

    def require_utility_scope():
        if "utility:read" not in granted_scopes:
            raise ToolError("Permission denied: utility:read required")

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                           idempotentHint=True, openWorldHint=False))
    def get_utility_rate() -> UtilityRate:
        """Return the illustrative USD flat water rate, not a real utility tariff.

        Requires utility:read. Excludes sewer, fixed fees, taxes and tiered pricing.
        """
        require_utility_scope()
        return UtilityRate()

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                           idempotentHint=True, openWorldHint=False))
    def estimate_water_cost(request: CostRequest) -> CostEstimate:
        """Estimate water-only cost for supplied gallons using the illustrative rate.

        Requires utility:read. Returns USD rounded half-up to cents, not a bill.
        Input volume is caller-supplied; this tool does not retrieve meter data.
        """
        require_utility_scope()
        return estimate_cost(request)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                           idempotentHint=True, openWorldHint=False))
    def estimate_conservation_savings(request: SavingsRequest) -> SavingsEstimate:
        """Project gallons and water-only USD saved from a proposed daily reduction.

        Requires utility:read. Uses the illustrative rate and caller-supplied daily
        volumes over 1–366 days. Savings are conditional, not measured or guaranteed.
        Does not set a goal, change a fixture, or execute a conservation action.
        """
        require_utility_scope()
        return estimate_savings(request)

    meter = None
    if meter_path is not None and "meter:read" in granted_scopes:
        try:
            meter = MeterStore(meter_path)
        except Exception:
            logging.getLogger(__name__).error("AquaMind MCP meter data unavailable")

    def meter_store() -> MeterStore:
        if "meter:read" not in granted_scopes:
            raise ToolError("Permission denied: meter:read required")
        if meter is None:
            raise ToolError("Meter data unavailable")
        return meter

    def meter_series(request: MeterQuery) -> MeterSeries:
        """Read 96 synthetic fifteen-minute average GPM values for an exported window.

        Requires meter:read. Select by generator seed, scenario ID and UTC start.
        Values start at start_timestamp; end_timestamp_exclusive is one day later.
        Missing windows are errors; no readings or anomaly labels are fabricated.
        """
        store = meter_store()
        try:
            return store.series(request)
        except LookupError:
            raise ToolError("Meter window not found") from None

    def meter_summary(request: MeterQuery) -> MeterSummary:
        """Summarize one exported synthetic day: gallons, mean and peak interval GPM.

        Requires meter:read. This describes measured usage, not a leak diagnosis.
        Peak refers to a fifteen-minute average, not instantaneous fixture flow.
        """
        store = meter_store()
        try:
            return store.summary(request)
        except LookupError:
            raise ToolError("Meter window not found") from None

    if demo_scenario is not None:
        def require_demo_meter():
            if 'meter:read' not in granted_scopes:
                raise ToolError('Permission denied: meter:read required')

        @server.tool(annotations=read_only)
        def get_meter_summary() -> DemoMeterSummary:
            """Read the selected synthetic demo's final day and preceding six-day baseline.

            Requires meter:read. Gallons and fifteen-minute average flow describe usage,
            not a leak diagnosis. Selection is fixed by the host for this turn.
            """
            require_demo_meter()
            return demo_meter.summary(demo_scenario)

        @server.tool(annotations=read_only)
        def get_meter_series() -> DemoMeterSeries:
            """Read 96 fifteen-minute average GPM values for the selected synthetic demo day.

            Requires meter:read. Starts at start_timestamp, ends before
            end_timestamp_exclusive. No fixture identities or simulator anomaly labels.
            """
            require_demo_meter()
            return demo_meter.series(demo_scenario)
    else:
        server.tool(name='get_meter_series', annotations=read_only)(meter_series)
        server.tool(name='get_meter_summary', annotations=read_only)(meter_summary)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                           idempotentHint=True, openWorldHint=False))
    def detect_water_anomaly(request: PredictionRequest) -> PredictionResponse:
        """Classify one midnight-UTC day of 96 fifteen-minute flow readings in GPM.

        Requires anomaly:read. Uses a trained LSTM and frozen residual calibration.
        Score is not a probability. Synthetic training; no real-world validation.
        This tool does not change alerts, goals, meters, or other persistent state.
        """
        if "anomaly:read" not in granted_scopes:
            raise ToolError("Permission denied: anomaly:read required")
        if detector is None:
            raise ToolError("Anomaly model unavailable")
        start = datetime.fromisoformat(request.start_timestamp)
        window = MeterWindow(tuple(request.flow_rates_gpm), 0, "normal", False, False,
                             request.start_timestamp, (start + timedelta(minutes=95 * 15)).isoformat())
        try:
            with lock:
                prediction = detector.predict((window,))[0]
            return PredictionResponse(**prediction, threshold=detector.manifest["threshold"],
                                      request_id=str(uuid4()))
        except Exception:
            raise ToolError("Anomaly inference unavailable") from None

    return server


def main():
    torch.set_num_threads(1)
    path = os.environ.get("AQUAMIND_DETECTOR_PATH")
    meter_path = os.environ.get("AQUAMIND_METER_DATASET_PATH")
    scopes = frozenset(scope.strip() for scope in os.environ.get("AQUAMIND_MCP_SCOPES", "").split(",") if scope.strip())
    create_server(Path(path) if path else None, scopes,
                  Path(meter_path) if meter_path else None).run(transport="stdio")


if __name__ == "__main__":
    main()
