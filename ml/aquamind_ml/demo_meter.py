"""The dashboard's fixed synthetic household, exported by the TypeScript simulator."""

import hashlib
from datetime import datetime, timedelta
from math import fsum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .meter import MeterSummary
from .weather import ScenarioId

DEFAULT_DEMO_METER_PATH = Path(__file__).resolve().parents[1] / 'data/demo/meter-v1.json'
SCENARIOS = {'normal', 'overnight-leak', 'running-toilet', 'irrigation-after-rain'}
Gallons = Annotated[float, Field(ge=0, le=15000, allow_inf_nan=False)]


class DemoMeterSnapshot(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    schema_version: Literal[1]
    source: Literal['synthetic']
    seed: Literal[42]
    start_timestamp: str = Field(max_length=40)
    interval_minutes: Literal[15]
    scenarios: dict[ScenarioId, Annotated[tuple[Gallons, ...], Field(min_length=672, max_length=672)]]

    @field_validator('schema_version', 'seed', 'interval_minutes', mode='before')
    @classmethod
    def integer_constants(cls, value):
        if type(value) is not int:
            raise ValueError('Expected an integer')
        return value

    @field_validator('start_timestamp')
    @classmethod
    def midnight_utc(cls, value):
        start = datetime.fromisoformat(value)
        if start.utcoffset() != timedelta(0) or start.time().isoformat() != '00:00:00':
            raise ValueError('Expected midnight UTC')
        try:
            start + timedelta(days=7)
        except OverflowError:
            raise ValueError('Timestamp outside supported range') from None
        return start.isoformat()

    @field_validator('scenarios')
    @classmethod
    def complete_scenarios(cls, value):
        if set(value) != SCENARIOS:
            raise ValueError('Expected all four demo scenarios')
        return value


class DemoMeterSummary(MeterSummary):
    baseline_start_timestamp: str
    baseline_end_timestamp_exclusive: str
    baseline_days: Literal[6] = 6
    baseline_daily_gallons: float
    difference_pct: float | None


class DemoMeterSeries(DemoMeterSummary):
    flow_rates_gpm: list[float]


class DemoMeterStore:
    """Load once; return fresh views without simulator ground truth or fixture labels."""

    def __init__(self, path: Path = DEFAULT_DEMO_METER_PATH):
        with path.open('rb') as stream:
            contents = stream.read(65537)
        if len(contents) > 65536:
            raise ValueError('Demo meter snapshot too large')
        snapshot = DemoMeterSnapshot.model_validate_json(contents)
        self.sha256 = hashlib.sha256(contents).hexdigest()
        self._start = datetime.fromisoformat(snapshot.start_timestamp)
        self._scenarios = dict(snapshot.scenarios)

    def series(self, scenario_id: ScenarioId) -> DemoMeterSeries:
        readings = self._scenarios[scenario_id]
        today = readings[-96:]
        baseline = fsum(readings[:-96]) / 6
        total = fsum(today)
        return DemoMeterSeries(seed=42, scenario_id=scenario_id,
            start_timestamp=(self._start + timedelta(days=6)).isoformat(),
            end_timestamp_exclusive=(self._start + timedelta(days=7)).isoformat(),
            dataset_sha256=self.sha256, total_gallons=total, mean_flow_gpm=total / 1440,
            peak_interval_flow_gpm=max(today) / 15,
            baseline_start_timestamp=self._start.isoformat(),
            baseline_end_timestamp_exclusive=(self._start + timedelta(days=6)).isoformat(),
            baseline_daily_gallons=baseline,
            difference_pct=(total - baseline) / baseline * 100 if baseline else None,
            flow_rates_gpm=[gallons / 15 for gallons in today])

    def summary(self, scenario_id: ScenarioId) -> DemoMeterSummary:
        return DemoMeterSummary(**self.series(scenario_id).model_dump(exclude={'flow_rates_gpm'}))
