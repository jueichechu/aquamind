"""Bounded interval-volume CSV parsing, without files, providers or model fitting."""

import csv
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from hashlib import sha256
from io import StringIO
import re
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator

from .bills import BillUnit, _us_gallons
from .evidence import EvidenceModel, MeterWindowContext

METER_CSV_LIMIT = 64 * 1024
METER_BODY_LIMIT = 96 * 1024
MAX_READINGS = 672
ReadingType = Literal['actual', 'estimated', 'mixed', 'unknown']


class MeterImportRequest(EvidenceModel):
    csv_text: str = Field(min_length=1, max_length=METER_CSV_LIMIT, repr=False)
    volume_unit: BillUnit
    interval_minutes: int = Field(ge=1, le=60)
    timezone: str = Field(min_length=1, max_length=64)
    reading_type: ReadingType
    consent_to_process: bool

    @field_validator('timezone')
    @classmethod
    def explicit_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError('An explicit supported IANA timezone is required') from None
        return value


@dataclass(frozen=True, repr=False)
class ImportedMeter:
    dataset_sha256: str
    start: datetime
    end_exclusive: datetime
    interval_minutes: int
    timezone: str
    volume_unit: BillUnit
    reading_type: ReadingType
    gallons: tuple[Decimal, ...]

    def context(self, *, evidence_id: str, household_id: str) -> MeterWindowContext:
        return MeterWindowContext(evidence_id=evidence_id, household_id=household_id,
            origin='user_provided', dataset_sha256=self.dataset_sha256,
            start=self.start, end_exclusive=self.end_exclusive,
            interval_minutes=self.interval_minutes, reading_count=len(self.gallons),
            volume_unit=self.volume_unit, reading_type=self.reading_type)

    @property
    def total_us_gallons(self) -> str:
        with localcontext() as context:
            context.prec = 40
            return str(sum(self.gallons, Decimal(0)).quantize(Decimal('0.000001')))


class MeterCsvError(ValueError):
    """Only fixed, source-free messages may cross the HTTP boundary."""


def parse_meter_csv(request: MeterImportRequest) -> ImportedMeter:
    # Revalidate constructed models at the ingestion boundary as well.
    request = MeterImportRequest.model_validate(request.model_dump())
    if not request.consent_to_process:
        raise MeterCsvError('Consent to process meter readings is required')
    try:
        contents = request.csv_text.encode('utf-8')
    except UnicodeEncodeError:
        raise MeterCsvError('CSV must be valid UTF-8 text') from None
    if len(contents) > METER_CSV_LIMIT:
        raise MeterCsvError('CSV exceeds the byte limit')
    reader = csv.reader(StringIO(request.csv_text, newline=''), strict=True)
    zone = ZoneInfo(request.timezone)
    cadence = timedelta(minutes=request.interval_minutes)
    starts: list[datetime] = []
    gallons: list[Decimal] = []
    try:
        if next(reader, None) != ['interval_start', 'volume']:
            raise MeterCsvError('CSV needs exactly interval_start,volume columns')
        for row in reader:
            if len(gallons) >= MAX_READINGS:
                raise MeterCsvError('CSV exceeds 672 readings')
            if len(row) != 2:
                raise MeterCsvError('Each CSV row needs exactly two values')
            instant, volume = row
            if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}(?::00)?(?:Z|[+-][0-9]{2}:[0-9]{2})', instant):
                raise MeterCsvError('Intervals need minute-aligned ISO timestamps with UTC offsets')
            try:
                start = datetime.fromisoformat(instant)
                utc = start.astimezone(UTC)
                local = utc.astimezone(zone)
                end = utc + cadence
            except (ValueError, OverflowError):
                raise MeterCsvError('CSV timestamp is outside the supported range') from None
            if local.utcoffset() != start.utcoffset() or local.replace(tzinfo=None) != start.replace(tzinfo=None):
                raise MeterCsvError('Timestamp offset or local time conflicts with the declared timezone')
            if starts and utc != starts[-1] + cadence:
                raise MeterCsvError('Intervals must be ordered and contiguous without duplicates or gaps')
            if not re.fullmatch(r'[0-9]{1,9}(?:\.[0-9]{1,6})?', volume):
                raise MeterCsvError('Volumes must be nonnegative decimals with at most six decimal places')
            normalized = _us_gallons(Decimal(volume), request.volume_unit)
            if normalized > 1000 * request.interval_minutes:
                raise MeterCsvError('Interval volume exceeds the supported flow limit')
            starts.append(utc)
            gallons.append(normalized)
    except csv.Error:
        raise MeterCsvError('Malformed CSV') from None
    if not gallons:
        raise MeterCsvError('CSV needs at least one reading')
    with localcontext() as context:
        context.prec = 40
        if sum(gallons, Decimal(0)) > 1_000_000:
            raise MeterCsvError('CSV exceeds 1,000,000 US gallons')
    return ImportedMeter(dataset_sha256=sha256(contents).hexdigest(), start=starts[0],
        end_exclusive=end, interval_minutes=request.interval_minutes, timezone=request.timezone,
        volume_unit=request.volume_unit, reading_type=request.reading_type, gallons=tuple(gallons))
