"""Read-only imported-meter MCP server; selection and scope belong to the host."""

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from .approvals import ApprovalSessionUnavailable
from .meter_session import ImportedMeterSeries, ImportedMeterSummary, SessionMeters


def create_imported_meter_server(store: SessionMeters, evidence_id: str,
                                 scopes: frozenset[str] = frozenset()) -> MCPServer:
    granted = frozenset(scopes)
    if granted - {'meter:read'}:
        raise ValueError('Imported meter server supports only meter:read')
    # Check ownership/expiry at binding and again atomically on every tool call.
    store.selected(evidence_id)
    server = MCPServer('AquaMind imported meter', version='0.1.0', log_level='WARNING')
    read_only = ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                               idempotentHint=True, openWorldHint=False)

    def selected(series=False):
        if 'meter:read' not in granted:
            raise ToolError('Permission denied: meter:read required')
        try:
            return store.selected(evidence_id, include_series=series)
        except ApprovalSessionUnavailable:
            raise ToolError('Session unavailable') from None
        except LookupError:
            raise ToolError('Selected meter evidence unavailable') from None

    @server.tool(annotations=read_only)
    def get_meter_summary() -> ImportedMeterSummary:
        """Summarize the host-selected user-provided intervals, not verified measurements.

        Requires meter:read. Selection cannot be changed by a tool argument.
        This is the imported period only, with no historical baseline, model
        inference, weather, tariff or leak/fixture diagnosis. Totals are US gallons.
        """
        return selected()

    @server.tool(annotations=read_only)
    def get_meter_series() -> ImportedMeterSeries:
        """Read up to 672 imported interval volumes rounded to six-decimal US gallons.

        Requires meter:read. Values begin at context.start at the declared cadence;
        context.end_exclusive is excluded. context.volume_unit is the original
        CSV unit; interval_volumes_us_gallons are converted volumes, not GPM or
        cumulative register readings. No interpolation, labels or model prediction.
        """
        return selected(True)

    return server
