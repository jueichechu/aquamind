"""Prepare reviewed bill/meter facts from an authenticated host selection."""

from decimal import Decimal, ROUND_HALF_UP, localcontext
from secrets import token_hex
from typing import Literal

from pydantic import Field, field_validator

from .bills import ManualBill, normalize_bill
from .evidence import (BillEvidenceContext, EvidenceContext, EvidenceModel, OpaqueId,
                       assess_evidence)
from .meter_session import SessionMeters
from .agent_tools import McpAgentTools, ToolOutcome

EVIDENCE_TOOLS = frozenset({'get_meter_summary', 'get_meter_series'})


class EvidencePeriodMismatch(ValueError):
    pass


class EvidenceQuestionRequest(EvidenceModel):
    text: str = Field(min_length=1, max_length=8192)
    bill: ManualBill
    bill_timezone: str = Field(min_length=1, max_length=64)
    bill_input_method: Literal['manual_entry', 'document_import']
    bill_reading_type: Literal['actual', 'estimated', 'mixed', 'unknown']
    meter_evidence_id: OpaqueId
    bill_reviewed: bool = Field(json_schema_extra={'const': True})
    meter_reviewed: bool = Field(json_schema_extra={'const': True})
    same_household: bool = Field(json_schema_extra={'const': True})
    share_with_ai: bool = Field(json_schema_extra={'const': True})

    @field_validator('text')
    @classmethod
    def bounded_question(cls, value):
        if not value.strip() or len(value.encode()) > 8192:
            raise ValueError('Expected a bounded household water question')
        return value

    @field_validator('bill_reviewed', 'meter_reviewed', 'same_household', 'share_with_ai', mode='before')
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError('Explicit review, household confirmation and sharing are required')
        return value


def without_identifiers(summary: dict) -> dict:
    return {**summary, 'context': {key: value for key, value in summary['context'].items()
        if key not in {'evidence_id', 'household_id', 'dataset_sha256'}}}


def prepare_evidence(body: EvidenceQuestionRequest, meters: SessionMeters) -> dict:
    selected = meters.selected(body.meter_evidence_id)
    bill = BillEvidenceContext(evidence_id='bill_' + token_hex(16),
        household_id=selected.context.household_id, origin='user_provided',
        input_method=body.bill_input_method, reviewed=body.bill_reviewed,
        timezone=body.bill_timezone, bill=body.bill)
    assessment = assess_evidence(EvidenceContext(schema_version=1, bill=bill, meter=selected.context))
    if assessment.status != 'ready':
        raise EvidencePeriodMismatch('Meter period must be contained in the bill period; check dates and timezone')
    normalized = normalize_bill(body.bill)
    comparison = None
    if assessment.can_compare_period_totals:
        with localcontext() as context:
            context.prec = 40
            difference = Decimal(selected.total_us_gallons) - Decimal(normalized.total_us_gallons)
            comparison = {'meter_minus_bill_us_gallons': str(difference.quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP)),
                          'basis': 'Same complete period; displayed totals rounded to six decimals, both unverified.'}
    return {'bill': normalized.model_dump(mode='json'), 'bill_timezone': body.bill_timezone,
        'bill_input_method_user_reported': body.bill_input_method,
        'bill_reading_type_user_reported': body.bill_reading_type,
        'meter': without_identifiers(selected.model_dump(mode='json')),
        'assessment': assessment.model_dump(mode='json'), 'totals_comparison': comparison,
        'household_association': 'User asserted the bill and readings concern the same household; not independently verified.'}


class EvidenceAgentTools(McpAgentTools):
    """Use real scoped MCP execution; omit unnecessary host IDs from provider input."""

    async def execute(self, call_id, name, arguments_json):
        outcome = await super().execute(call_id, name, arguments_json)
        if outcome.status == 'success':
            return ToolOutcome(outcome.call_id, outcome.status,
                {'result': without_identifiers(outcome.data['result'])})
        return outcome
