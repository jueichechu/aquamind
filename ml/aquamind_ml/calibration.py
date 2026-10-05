"""Training-only time-of-day calibration of LSTM reconstruction residuals."""

from dataclasses import dataclass
from datetime import datetime, timedelta
import math

import torch

from .data import FlowNormalizer, MeterDataset, MeterWindow
from .model import LSTMAutoencoder


def residuals(model: LSTMAutoencoder, normalizer: FlowNormalizer,
              windows: tuple[MeterWindow, ...]) -> torch.Tensor:
    if not windows:
        raise ValueError("Expected nonempty daily windows")
    for window in windows:
        start = datetime.fromisoformat(window.start_timestamp)
        if (len(window.flow_rates_gpm) != 96 or start.utcoffset() != timedelta(0) or
                (start.hour, start.minute, start.second, start.microsecond) != (0, 0, 0, 0)):
            raise ValueError("Calibration requires midnight-aligned 96-interval daily windows")
    flows = torch.tensor(normalizer.transform(windows), dtype=torch.float32).unsqueeze(-1)
    previous_mode = model.training
    try:
        model.eval()
        with torch.inference_mode():
            return torch.cat([(batch - model(batch)).squeeze(-1) for batch in flows.split(64)])
    finally:
        model.train(previous_mode)


@dataclass(frozen=True)
class ResidualCalibration:
    mean: tuple[float, ...]
    scale: tuple[float, ...]
    scale_floor: float = 0.01

    def __post_init__(self):
        if len(self.mean) != 96 or len(self.scale) != 96:
            raise ValueError("Expected 96 calibration parameters")
        if (not all(math.isfinite(v) for v in self.mean) or
                not all(math.isfinite(v) for v in self.scale) or
                not 0 < self.scale_floor < float("inf") or
                any(value < self.scale_floor for value in self.scale)):
            raise ValueError("Invalid calibration parameters")

    @classmethod
    def fit(cls, model: LSTMAutoencoder, normalizer: FlowNormalizer, dataset: MeterDataset):
        if any(w.scenario_id != "normal" or w.has_anomaly or w.has_leak for w in dataset.train):
            raise ValueError("Residual calibration requires normal training windows")
        errors = residuals(model, normalizer, dataset.train)
        # Fixed numerical floor in normalized-flow units; not selected on test data.
        return cls(tuple(errors.mean(dim=0).tolist()),
                   tuple(max(value, 0.01) for value in errors.std(dim=0, correction=0).tolist()))

    def score(self, errors: torch.Tensor) -> list[float]:
        if errors.ndim != 2 or errors.shape[0] == 0 or errors.shape[1] != 96 or not torch.isfinite(errors).all():
            raise ValueError("Expected finite [windows, 96] residuals")
        centered = errors - errors.new_tensor(self.mean)
        standardized = centered / errors.new_tensor(self.scale)
        # Positive residuals represent excess flow. Do not use scenario labels as features.
        return standardized.clamp_min(0).square().mean(dim=1).tolist()
