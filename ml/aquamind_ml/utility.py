"""Illustrative water-only estimates; never a real provider tariff or bill."""

from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Gallons = Annotated[float, Field(strict=True, ge=0, le=1_000_000, allow_inf_nan=False)]
RATE = Decimal("5.00")


class UtilityRate(BaseModel):
    rate_id: Literal["demo-flat-usd-v1"] = "demo-flat-usd-v1"
    source: Literal["illustrative_assumption"] = "illustrative_assumption"
    currency: Literal["USD"] = "USD"
    dollars_per_1000_gallons: str = str(RATE)
    exclusions: tuple[str, ...] = ("sewer", "fixed fees", "taxes", "tiered pricing")


class CostRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gallons: Gallons


class SavingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    baseline_daily_gallons: Gallons
    proposed_daily_gallons: Gallons
    days: int = Field(strict=True, ge=1, le=366)

    @model_validator(mode="after")
    def reduction(self):
        if self.proposed_daily_gallons > self.baseline_daily_gallons:
            raise ValueError("Proposed usage must not exceed baseline usage")
        return self


class CostEstimate(BaseModel):
    rate: UtilityRate
    gallons: float
    estimated_water_cost_usd: str


class SavingsEstimate(BaseModel):
    rate: UtilityRate
    baseline_daily_gallons: float
    proposed_daily_gallons: float
    days: int
    saved_gallons: float
    estimated_water_savings_usd: str
    assumption: Literal["Daily reduction persists for every requested day; not guaranteed savings"] = (
        "Daily reduction persists for every requested day; not guaranteed savings")


def water_charge(gallons: Decimal) -> str:
    return str((gallons * RATE / 1000).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def estimate_cost(request: CostRequest) -> CostEstimate:
    return CostEstimate(rate=UtilityRate(), gallons=request.gallons,
                        estimated_water_cost_usd=water_charge(Decimal(str(request.gallons))))


def estimate_savings(request: SavingsRequest) -> SavingsEstimate:
    saved = (Decimal(str(request.baseline_daily_gallons)) -
             Decimal(str(request.proposed_daily_gallons))) * request.days
    return SavingsEstimate(rate=UtilityRate(), **request.model_dump(), saved_gallons=float(saved),
                           estimated_water_savings_usd=water_charge(saved))
