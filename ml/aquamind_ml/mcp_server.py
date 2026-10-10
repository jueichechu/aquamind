"""Local stdio MCP server with a server-owned read-only scope boundary."""

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


def create_server(detector_path: Path | None, scopes: frozenset[str] = frozenset()) -> MCPServer:
    # Copy policy into this server; it cannot be changed through an MCP request.
    granted_scopes = frozenset(scopes)
    if granted_scopes - {"anomaly:read"}:
        raise ValueError("Unsupported MCP scope")
    server = MCPServer("AquaMind", version="0.1.0", log_level="WARNING")
    detector = None
    if detector_path is not None and "anomaly:read" in granted_scopes:
        try:
            detector = FrozenDetector(detector_path)
        except Exception:
            logging.getLogger(__name__).error("AquaMind MCP detector unavailable")
    lock = Lock()

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
    scopes = frozenset(scope.strip() for scope in os.environ.get("AQUAMIND_MCP_SCOPES", "").split(",") if scope.strip())
    create_server(Path(path) if path else None, scopes).run(transport="stdio")


if __name__ == "__main__":
    main()
