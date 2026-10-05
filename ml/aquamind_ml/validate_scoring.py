"""Compare baseline and calibrated scores on validation only; never score test."""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import torch

from .calibration import ResidualCalibration, residuals
from .evaluate import load_checkpoint, metrics, select_threshold


def validate_scoring(dataset_path: Path, checkpoint: Path) -> dict:
    dataset, model, normalizer, _, weights_hash = load_checkpoint(dataset_path, checkpoint)
    previous_threads = torch.get_num_threads()
    try:
        torch.set_num_threads(1)
        calibration = ResidualCalibration.fit(model, normalizer, dataset)
        errors = residuals(model, normalizer, dataset.validation)
        labels = [w.has_leak for w in dataset.validation]
        candidates = {"daily_mse": errors.square().mean(dim=1).tolist(),
                      "positive_standardized_residual": calibration.score(errors)}
        results = {}
        for name, scores in candidates.items():
            threshold = select_threshold(scores, labels)
            predicted = [value >= threshold for value in scores]
            results[name] = {"threshold": threshold, "metrics": metrics(labels, predicted),
                "by_scenario": {
                    scenario: metrics([labels[i] for i, w in enumerate(dataset.validation) if w.scenario_id == scenario],
                                      [predicted[i] for i, w in enumerate(dataset.validation) if w.scenario_id == scenario])
                    for scenario in sorted({w.scenario_id for w in dataset.validation})}}
        return {"schema_version": 1, "source": "synthetic", "split": "validation",
                "dataset_sha256": dataset.sha256, "weights_sha256": weights_hash,
                "source_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                  for name in ("calibration.py", "validate_scoring.py")},
                "calibration": asdict(calibration), "results": results, "test_evaluated": False,
                "limitations": ["Development results, not held-out performance",
                                 "All seeds share fixed household schedules and leak patterns",
                                 "Requires midnight UTC alignment; household/time-zone variation untested",
                                 "Fresh unseen seeds required for confirmatory testing"]}
    finally:
        torch.set_num_threads(previous_threads)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output}")
    report = validate_scoring(args.dataset, args.checkpoint)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        output.write(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report["results"], indent=2))


if __name__ == "__main__":
    main()
