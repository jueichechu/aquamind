"""Training-centered sustained residuals with validation alarm-rate constraints."""

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path

import torch

from .calibration import residuals
from .evaluate import metrics
from .hybrid_validate import load_checkpoint, summarize_validation


@dataclass(frozen=True)
class SustainedCalibration:
    center: tuple[float, ...]
    scale: tuple[float, ...]
    window_intervals: int = 16
    quantile_rank: int = 4

    def __post_init__(self):
        if (len(self.center) != 96 or len(self.scale) != 96 or
                not all(math.isfinite(v) for v in self.center) or
                not all(math.isfinite(v) and v >= .01 for v in self.scale) or
                self.window_intervals != 16 or self.quantile_rank != 4):
            raise ValueError('Invalid sustained calibration')

    @classmethod
    def fit(cls, model, normalizer, training_windows):
        if not training_windows or any(w.variant_kind != 'unmodified' or w.injection_present
                                       for w in training_windows):
            raise ValueError('Expected unmodified training baseline')
        errors = residuals(model, normalizer, training_windows)
        return cls(tuple(errors.median(dim=0).values.tolist()),
                   tuple(max(value, .01) for value in errors.std(dim=0, correction=0).tolist()))

    def score(self, errors: torch.Tensor) -> list[float]:
        if (errors.ndim != 2 or errors.shape[0] < 1 or errors.shape[1] != 96 or
                not torch.isfinite(errors).all()):
            raise ValueError('Expected finite nonempty [windows, 96] residuals')
        standardized = (errors - errors.new_tensor(self.center)) / errors.new_tensor(self.scale)
        stretches = standardized.unfold(1, self.window_intervals, 1)
        # Fourth-smallest value of 16 is the nearest-rank lower quartile.
        return stretches.kthvalue(self.quantile_rank, dim=-1).values.amax(dim=1).clamp_min(0).tolist()


def select_constrained_threshold(windows, scores: list[float]) -> float:
    if (not windows or len(windows) != len(scores) or
            any(not math.isfinite(s) or s < 0 for s in scores)):
        raise ValueError('Expected aligned finite nonnegative validation scores')
    labels = [w.is_continuous_injection for w in windows]
    groups = [[i for i, w in enumerate(windows) if w.variant_kind == kind]
              for kind in ('unmodified', 'demand_confounder')]
    if not all(groups) or not any(labels):
        raise ValueError('Expected injection targets and both reference groups')
    candidates = sorted(set(scores) | {math.nextafter(max(scores), math.inf)})
    eligible = [threshold for threshold in candidates
                if all(20 * sum(scores[i] >= threshold for i in group) <= len(group) for group in groups)]
    return max(eligible, key=lambda threshold: (
        metrics(labels, [score >= threshold for score in scores])['f1'], threshold))


def compare(dataset, model, normalizer) -> dict:
    previous_threads = torch.get_num_threads()
    try:
        torch.set_num_threads(1)
        calibration = SustainedCalibration.fit(model, normalizer, dataset.train)
        errors = residuals(model, normalizer, dataset.validation)
        scores = calibration.score(errors)
        threshold = select_constrained_threshold(dataset.validation, scores)
        # Apply the same alarm constraints to MSE, isolating the scoring change.
        mse_scores = errors.square().mean(dim=1).tolist()
        mse_threshold = select_constrained_threshold(dataset.validation, mse_scores)
        return {'calibration': asdict(calibration),
                'sustained': summarize_validation(dataset.validation, scores, threshold),
                'mse_with_same_constraints': summarize_validation(dataset.validation, mse_scores, mse_threshold),
                'test_evaluated': False}
    finally:
        torch.set_num_threads(previous_threads)


def validate(dataset_path: Path, checkpoint: Path) -> dict:
    dataset, model, normalizer, training, digest = load_checkpoint(dataset_path, checkpoint)
    return {'schema': 'aquamind-hybrid-sustained-validation-v1',
            'pattern_protocol': 'ampds2-hybrid-v1', 'scoring_protocol': 'sustained-residual-v1',
            'score': 'maximum over 16-interval stretches of fourth-smallest training-standardized residual; clamped at zero',
            'selection': 'maximum validation F1 subject to <=5% alarm rate separately on unmodified and demand-confounder references; higher threshold breaks ties',
            'dataset_sha256': dataset.sha256, 'weights_sha256': digest,
            'selected_epoch': training['selected_epoch'], 'normalizer': training['normalizer'],
            'source_sha256': {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                              for name in ('hybrid_sustained.py', 'hybrid_validate.py', 'calibration.py', 'evaluate.py')},
            'limitations': ['One household; physical leak labels unknown',
                            'Controlled injection grid, not realistic leak prevalence',
                            'Validation informed score development and threshold selection; optimistic results',
                            'Five percent daily-window reference cap is a development criterion, not production validation',
                            'UTC-aligned calibration; neighboring variants are correlated'],
            **compare(dataset, model, normalizer)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Refusing to overwrite report')
    report = validate(args.dataset, args.checkpoint)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        stream.write(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({method: {k: report[method][k] for k in ('threshold', 'validation', 'by_variant_kind')}
                      for method in ('sustained', 'mse_with_same_constraints')}, indent=2))


if __name__ == '__main__':
    main()
