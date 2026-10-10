"""Read-only views of the existing synthetic meter export; no model labels exposed."""

from datetime import datetime, timedelta
from math import fsum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .data import load_dataset


class MeterQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seed: int = Field(strict=True, ge=0, le=0xFFFFFFFF)
    scenario_id: Literal["normal", "overnight-leak", "running-toilet", "irrigation-after-rain"]
    start_timestamp: str = Field(max_length=40)

    @field_validator("start_timestamp")
    @classmethod
    def utc_start(cls, value: str) -> str:
        timestamp = datetime.fromisoformat(value)
        if timestamp.utcoffset() != timedelta(0):
            raise ValueError("Expected a UTC window start")
        return timestamp.isoformat()


class MeterSummary(MeterQuery):
    source: Literal["synthetic"] = "synthetic"
    dataset_sha256: str
    end_timestamp_exclusive: str
    interval_minutes: Literal[15] = 15
    reading_count: Literal[96] = 96
    total_gallons: float
    mean_flow_gpm: float
    peak_interval_flow_gpm: float


class MeterSeries(MeterSummary):
    flow_rates_gpm: list[float]


class MeterStore:
    """Load one trusted host-selected snapshot, indexed by seed/scenario/start."""

    def __init__(self, path: Path):
        dataset = load_dataset(path)
        self.sha256 = dataset.sha256
        self._windows = {
            (row.seed, row.scenario_id, datetime.fromisoformat(row.start_timestamp)): row
            for row in (*dataset.train, *dataset.validation, *dataset.test)
        }

    def series(self, query: MeterQuery) -> MeterSeries:
        start = datetime.fromisoformat(query.start_timestamp)
        row = self._windows.get((query.seed, query.scenario_id, start))
        if row is None:
            raise LookupError("Meter window not found")
        total_flow = fsum(row.flow_rates_gpm)
        return MeterSeries(**query.model_dump(), dataset_sha256=self.sha256,
                           end_timestamp_exclusive=(start + timedelta(days=1)).isoformat(),
                           total_gallons=total_flow * 15, mean_flow_gpm=total_flow / 96,
                           peak_interval_flow_gpm=max(row.flow_rates_gpm),
                           flow_rates_gpm=list(row.flow_rates_gpm))

    def summary(self, query: MeterQuery) -> MeterSummary:
        return MeterSummary(**self.series(query).model_dump(exclude={"flow_rates_gpm"}))
