"""Synthetic scenario context shared with the TypeScript demo, not live weather."""

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ScenarioId = Literal["normal", "overnight-leak", "running-toilet", "irrigation-after-rain"]
DEFAULT_WEATHER_PATH = (Path(__file__).resolve().parents[2] /
                        "apps/web/src/lib/water/scenario-weather.json")


class WeatherQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: ScenarioId


class WeatherValues(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rainfallInchesLast24h: float = Field(strict=True, ge=0, le=100, allow_inf_nan=False)
    temperatureF: float = Field(strict=True, ge=-150, le=150, allow_inf_nan=False)


class WeatherSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schemaVersion: Literal[1]
    source: Literal["synthetic"]
    scenarios: dict[ScenarioId, WeatherValues]

    @field_validator("schemaVersion", mode="before")
    @classmethod
    def version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("Unsupported weather schema")
        return value


class WeatherContext(WeatherQuery):
    source: Literal["synthetic"] = "synthetic"
    snapshot_sha256: str
    rainfall_inches_last_24h: float
    temperature_f: float
    temporal_scope: Literal["Static scenario context; no observation time or real location"] = (
        "Static scenario context; no observation time or real location")


class WeatherStore:
    def __init__(self, path: Path):
        contents = path.read_bytes()
        snapshot = WeatherSnapshot.model_validate_json(contents)
        if set(snapshot.scenarios) != {
            "normal", "overnight-leak", "running-toilet", "irrigation-after-rain"
        }:
            raise ValueError("Invalid weather snapshot")
        self._scenarios = snapshot.scenarios
        self.sha256 = hashlib.sha256(contents).hexdigest()

    def context(self, query: WeatherQuery) -> WeatherContext:
        weather = self._scenarios[query.scenario_id]
        return WeatherContext(scenario_id=query.scenario_id, snapshot_sha256=self.sha256,
                              rainfall_inches_last_24h=weather.rainfallInchesLast24h,
                              temperature_f=weather.temperatureF)
