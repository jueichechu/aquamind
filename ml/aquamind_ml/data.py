"""Load schema-v1 exports and standardize flow using normal training data only."""

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
from statistics import fmean, pstdev


@dataclass(frozen=True)
class MeterWindow:
    flow_rates_gpm: tuple[float, ...]
    seed: int
    scenario_id: str
    has_anomaly: bool
    has_leak: bool
    start_timestamp: str
    end_timestamp: str


@dataclass(frozen=True)
class MeterDataset:
    train: tuple[MeterWindow, ...]
    validation: tuple[MeterWindow, ...]
    test: tuple[MeterWindow, ...]
    sha256: str


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _seed(value: object) -> bool:
    return type(value) is int and 0 <= value <= 0xFFFFFFFF


def _flow(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def load_dataset(path: str | Path) -> MeterDataset:
    """Reject malformed exports, overlapping seed splits, and anomalous training data."""
    contents = Path(path).read_bytes()
    raw = json.loads(contents)
    _require(isinstance(raw, dict), "Dataset must be an object")
    for key, expected in (("schemaVersion", 1), ("intervalMinutes", 15), ("windowSize", 96)):
        _require(type(raw.get(key)) is int and raw[key] == expected, f"Unsupported {key}")
    _require(raw.get("source") == "synthetic", "Expected explicitly synthetic data")
    manifest = raw.get("seedSplit")
    names = ("train", "validation", "test")
    _require(isinstance(manifest, dict) and set(manifest) == set(names), "Invalid seed manifest")
    assigned: set[int] = set()
    groups = {}
    for name in names:
        seeds = manifest[name]
        _require(isinstance(seeds, list) and bool(seeds), f"Empty or invalid {name} seeds")
        _require(all(_seed(seed) for seed in seeds), "Invalid uint32 seed")
        _require(len(set(seeds)) == len(seeds), "Duplicate manifest seed")
        _require(not assigned.intersection(seeds), "Seed splits overlap")
        assigned.update(seeds)
        rows = raw.get(name)
        _require(isinstance(rows, list) and bool(rows), f"Empty or invalid {name} windows")
        windows = []
        identities = set()
        for row in rows:
            _require(isinstance(row, dict), "Window must be an object")
            seed = row.get("seed")
            _require(_seed(seed) and seed in seeds, "Window seed is outside its split")
            scenario = row.get("scenarioId")
            _require(scenario in ("normal", "overnight-leak", "running-toilet", "irrigation-after-rain"),
                     "Unknown scenario")
            anomaly, leak = row.get("hasAnomaly"), row.get("hasLeak")
            _require(type(anomaly) is bool and type(leak) is bool, "Labels must be booleans")
            _require(anomaly == (scenario != "normal"), "Inconsistent anomaly label")
            _require(leak == (scenario in ("overnight-leak", "running-toilet")), "Inconsistent leak label")
            _require(name != "train" or scenario == "normal", "Training must contain only normal windows")
            flows = row.get("flowRatesGpm")
            _require(isinstance(flows, list) and len(flows) == 96, "Expected 96 flow values")
            _require(all(_flow(value) for value in flows), "Flows must be finite non-negative numbers")
            start, end = row.get("startTimestamp"), row.get("endTimestamp")
            try:
                first, last = datetime.fromisoformat(start), datetime.fromisoformat(end)
            except (TypeError, ValueError):
                raise ValueError("Invalid window timestamps") from None
            _require(first.utcoffset() == timedelta(0) and last.utcoffset() == timedelta(0),
                     "Window timestamps must use UTC")
            _require(last - first == timedelta(minutes=95 * 15), "Invalid window duration")
            identity = (seed, scenario, first)
            _require(identity not in identities, "Duplicate window")
            identities.add(identity)
            windows.append(MeterWindow(tuple(float(v) for v in flows), seed, scenario,
                                       anomaly, leak, start, end))
        _require({window.seed for window in windows} == set(seeds), "Manifest seeds lack windows")
        groups[name] = tuple(windows)
    return MeterDataset(**groups, sha256=hashlib.sha256(contents).hexdigest())


@dataclass(frozen=True)
class FlowNormalizer:
    """Global population z-score; the same frozen parameters serve every split."""

    mean_gpm: float
    scale_gpm: float
    training_value_count: int
    dataset_sha256: str

    def __post_init__(self) -> None:
        _require(math.isfinite(self.mean_gpm) and self.mean_gpm >= 0, "Invalid mean")
        _require(math.isfinite(self.scale_gpm) and self.scale_gpm > 0, "Invalid scale")
        _require(type(self.training_value_count) is int and self.training_value_count > 0,
                 "Invalid training value count")

    @classmethod
    def fit(cls, dataset: MeterDataset) -> "FlowNormalizer":
        _require(bool(dataset.train), "Empty training split")
        _require(all(w.scenario_id == "normal" and not w.has_anomaly and not w.has_leak
                     for w in dataset.train), "Training must contain only normal windows")
        values = [value for window in dataset.train for value in window.flow_rates_gpm]
        _require(bool(values) and all(_flow(v) for v in values), "Invalid training flows")
        # Constant training data uses unit scale; validation/test never affect this choice.
        return cls(fmean(values), pstdev(values) or 1.0, len(values), dataset.sha256)

    def transform(self, windows: tuple[MeterWindow, ...]) -> tuple[tuple[float, ...], ...]:
        """Return only features; retain labels and provenance in the original dataset."""
        _require(all(_flow(v) for w in windows for v in w.flow_rates_gpm), "Invalid flows")
        return tuple(tuple((v - self.mean_gpm) / self.scale_gpm for v in w.flow_rates_gpm)
                     for w in windows)
