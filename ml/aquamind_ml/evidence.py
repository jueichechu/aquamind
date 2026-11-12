"""Bounded, read-only evidence compatibility; no transport, storage or model calls."""

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .bills import BillUnit, ManualBill
from .meter import MeterSummary

OpaqueId = Annotated[str, Field(pattern=r'^[a-z][a-z0-9_-]{7,63}$')]
Origin = Literal['synthetic', 'user_provided']
Reason = Literal['missing_bill', 'missing_meter', 'different_households', 'different_origins',
                 'bill_needs_review', 'voice_needs_review', 'disjoint_periods',
                 'meter_outside_bill_period']


class EvidenceModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True, hide_input_in_errors=True)


class EvidenceReference(EvidenceModel):
    evidence_id: OpaqueId
    household_id: OpaqueId


def _utc_midnight(day: date, timezone: str) -> datetime:
    zone = ZoneInfo(timezone)
    local = datetime.combine(day, time(), zone)
    utc = local.astimezone(UTC)
    if (utc.astimezone(zone).replace(tzinfo=None) != local.replace(tzinfo=None) or
            local.utcoffset() != local.replace(fold=1).utcoffset()):
        raise ValueError('Billing boundary must have an unambiguous local midnight')
    return utc


class BillEvidenceContext(EvidenceReference):
    origin: Origin
    input_method: Literal['manual_entry', 'document_import']
    reviewed: bool
    timezone: str = Field(min_length=1, max_length=64)
    bill: ManualBill

    @field_validator('timezone')
    @classmethod
    def known_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('An explicit supported IANA timezone is required') from None
        return value

    @model_validator(mode='after')
    def valid_boundaries(self):
        try:
            start = _utc_midnight(self.bill.period_start, self.timezone)
            end = _utc_midnight(self.bill.period_end_exclusive, self.timezone)
        except (OverflowError, OSError):
            raise ValueError('Billing boundary outside the supported range') from None
        if end <= start:
            raise ValueError('Billing boundaries must be ordered')
        return self


class MeterWindowContext(EvidenceReference):
    origin: Origin
    dataset_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    start: datetime
    end_exclusive: datetime
    interval_minutes: int = Field(ge=1, le=60)
    reading_count: int = Field(ge=1, le=672)
    volume_unit: BillUnit
    reading_type: Literal['actual', 'estimated', 'mixed', 'unknown']

    @field_validator('start', 'end_exclusive', mode='before')
    @classmethod
    def aware_instant(cls, value):
        if isinstance(value, str) and len(value) <= 64:
            try:
                value = datetime.fromisoformat(value)
            except ValueError:
                raise ValueError('Expected an offset-aware ISO meter instant') from None
        if not isinstance(value, datetime) or value.utcoffset() is None:
            raise ValueError('Meter instants need an explicit UTC offset')
        try:
            value = value.astimezone(UTC)
        except (OverflowError, OSError):
            raise ValueError('Meter instant outside the supported range') from None
        if value.second or value.microsecond:
            raise ValueError('Meter instants must align to whole minutes')
        return value

    @model_validator(mode='after')
    def complete_window(self):
        if self.end_exclusive - self.start != timedelta(
                minutes=self.interval_minutes * self.reading_count):
            raise ValueError('Meter duration must match cadence and reading count')
        return self


class VoiceQueryContext(EvidenceReference):
    # A question is not a measured household fact. A real voice can ask about a
    # synthetic example; do not confuse recording provenance with meter origin.
    reviewed: bool
    transcript: str = Field(min_length=1, max_length=2000)

    @field_validator('transcript')
    @classmethod
    def nonempty_query(cls, value):
        if not value.strip() or any(ord(c) < 32 and c not in '\n\t\r' for c in value):
            raise ValueError('Expected a nonempty query without control characters')
        return value


class EvidenceContext(EvidenceModel):
    schema_version: Literal[1]
    bill: BillEvidenceContext | None = None
    meter: MeterWindowContext | None = None
    voice: VoiceQueryContext | None = None

    @field_validator('schema_version', mode='before')
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError('Expected an integer schema version')
        return value

    @model_validator(mode='after')
    def unique_references(self):
        ids = [item.evidence_id for item in (self.bill, self.meter, self.voice) if item is not None]
        if len(ids) != len(set(ids)):
            raise ValueError('Evidence references must be distinct')
        return self


class EvidenceAssessment(EvidenceModel):
    status: Literal['ready', 'blocked', 'incomplete']
    reasons: tuple[Reason, ...]
    coverage: Literal['same_period', 'partial_period', 'none']
    can_compare_period_totals: bool
    limitations: tuple[str, ...]


def assess_evidence(context: EvidenceContext) -> EvidenceAssessment:
    """Determine permitted association, not truth, consent or authorization."""
    bill, meter, voice = context.bill, context.meter, context.voice
    reasons: list[Reason] = []
    limitations = ['Evidence remains unverified; association does not establish a leak or its cause.']
    if bill is None:
        reasons.append('missing_bill')
    elif not bill.reviewed:
        reasons.append('bill_needs_review')
    if meter is None:
        reasons.append('missing_meter')
    if voice is not None and not voice.reviewed:
        reasons.append('voice_needs_review')
    references = [item for item in (bill, meter, voice) if item is not None]
    if len({item.household_id for item in references}) > 1:
        reasons.append('different_households')
    if bill is not None and meter is not None and bill.origin != meter.origin:
        reasons.append('different_origins')
    if any(item is not None and item.origin == 'synthetic' for item in (bill, meter)):
        limitations.append('Synthetic evidence must remain labeled as synthetic.')
    coverage = 'none'
    if bill is not None and meter is not None:
        start = _utc_midnight(bill.bill.period_start, bill.timezone)
        end = _utc_midnight(bill.bill.period_end_exclusive, bill.timezone)
        if meter.end_exclusive <= start or meter.start >= end:
            reasons.append('disjoint_periods')
        elif meter.start < start or meter.end_exclusive > end:
            reasons.append('meter_outside_bill_period')
        else:
            coverage = 'same_period' if (meter.start, meter.end_exclusive) == (start, end) else 'partial_period'
    status = ('blocked' if set(reasons) - {'missing_bill', 'missing_meter'} else
              'incomplete' if reasons else 'ready')
    if status != 'ready':
        coverage = 'none'
    elif coverage == 'partial_period':
        limitations.append('A partial meter period cannot be compared with the full bill total.')
    if meter is not None and meter.reading_type != 'actual':
        limitations.append('Meter readings are not identified as entirely actual readings.')
    return EvidenceAssessment(status=status, reasons=tuple(reasons), coverage=coverage,
        can_compare_period_totals=status == 'ready' and coverage == 'same_period',
        limitations=tuple(limitations))


def demo_meter_context(summary: MeterSummary, *, evidence_id: str, household_id: str) -> MeterWindowContext:
    """Adapt existing host-selected synthetic meter metadata, without simulator labels."""
    return MeterWindowContext(evidence_id=evidence_id, household_id=household_id,
        origin=summary.source, dataset_sha256=summary.dataset_sha256,
        start=summary.start_timestamp, end_exclusive=summary.end_timestamp_exclusive,
        interval_minutes=summary.interval_minutes, reading_count=summary.reading_count,
        volume_unit='us_gallons', reading_type='unknown')
