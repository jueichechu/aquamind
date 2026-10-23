"""Validate manual bill entries and normalize aggregate usage; no diagnosis or tariff inference."""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

BillUnit = Literal['us_gallons', 'ccf', 'cubic_meters', 'liters']
Usage = Annotated[Decimal, Field(ge=0, max_digits=15, decimal_places=6, allow_inf_nan=False)]
Charge = Annotated[Decimal, Field(ge=0, le=1_000_000, decimal_places=2, allow_inf_nan=False)]
US_GALLON_LITERS = Decimal('3.785411784')


def _decimal(value, places):
    if value is None:
        return value
    if type(value) not in (str, int, float, Decimal):
        raise ValueError('Expected a non-negative decimal amount')
    text = str(value)
    if len(text) > 32 or not re.fullmatch(r'[0-9]{1,9}(?:\.[0-9]{1,' + str(places) + r'})?', text.strip()):
        raise ValueError('Expected a bounded decimal amount without separators or unit suffixes')
    return Decimal(text.strip())


def _us_gallons(usage: Decimal, unit: BillUnit) -> Decimal:
    # NIST: 1 US liquid gallon = 231 in³ = 3.785411784 L; 1 ft³ = 1728 in³.
    # EPA: 1 CCF = 100 ft³. Keep the exact ratio instead of rounding to 748 gallons.
    with localcontext() as context:
        context.prec = 40
        context.rounding = ROUND_HALF_UP
        if unit == 'us_gallons':
            return usage
        if unit == 'ccf':
            return usage * 172800 / 231
        if unit == 'cubic_meters':
            return usage * 1000 / US_GALLON_LITERS
        return usage / US_GALLON_LITERS


class ManualBill(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    period_start: date
    period_end_exclusive: date
    usage: Usage
    usage_unit: BillUnit
    water_charge: Charge | None = None
    sewer_charge: Charge | None = None
    currency: Literal['USD'] | None = None

    @field_validator('period_start', 'period_end_exclusive', mode='before')
    @classmethod
    def calendar_date(cls, value):
        if type(value) is date:
            return value
        if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
            raise ValueError('Expected an ISO calendar date, YYYY-MM-DD')
        return date.fromisoformat(value)

    @field_validator('usage', mode='before')
    @classmethod
    def usage_decimal(cls, value):
        return _decimal(value, 6)

    @field_validator('water_charge', 'sewer_charge', mode='before')
    @classmethod
    def charge_decimal(cls, value):
        return _decimal(value, 2)

    @model_validator(mode='after')
    def consistent_bill(self):
        if not 1 <= (self.period_end_exclusive - self.period_start).days <= 366:
            raise ValueError('Billing period must cover 1–366 days, with an exclusive end date')
        if _us_gallons(self.usage, self.usage_unit) > 1_000_000:
            raise ValueError('Bill usage must not exceed 1,000,000 US gallons')
        if (self.water_charge is not None or self.sewer_charge is not None) and self.currency is None:
            raise ValueError('Explicit USD currency is required when entering charges')
        return self


class NormalizedBill(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    source: Literal['manual_entry'] = 'manual_entry'
    evidence_level: Literal['bill_only'] = 'bill_only'
    confidence: Literal['limited'] = 'limited'
    bill: ManualBill
    billing_days: int
    total_us_gallons: str
    us_gallons_per_day: str
    water_and_sewer_subtotal: str | None
    limitations: tuple[str, ...] = (
        'Entered values are unverified; no original bill was inspected.',
        'One aggregate bill cannot establish a usage trend, precise leak timing or a fixture diagnosis.',
        'The water/sewer subtotal covers only entered line items, not a verified total bill.',
        'No tariff, savings estimate or leak prediction is inferred.',
    )


def normalize_bill(bill: ManualBill) -> NormalizedBill:
    days = (bill.period_end_exclusive - bill.period_start).days
    with localcontext() as context:
        context.prec = 40
        context.rounding = ROUND_HALF_UP
        gallons = _us_gallons(bill.usage, bill.usage_unit)
        subtotal = None
        if bill.water_charge is not None and bill.sewer_charge is not None:
            subtotal = str((bill.water_charge + bill.sewer_charge).quantize(Decimal('0.01')))
        return NormalizedBill(bill=bill, billing_days=days,
            total_us_gallons=str(gallons.quantize(Decimal('0.000001'))),
            us_gallons_per_day=str((gallons / days).quantize(Decimal('0.000001'))),
            water_and_sewer_subtotal=subtotal)
