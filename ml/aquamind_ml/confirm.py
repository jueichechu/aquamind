"""Evaluate a frozen detector on a disjoint export's test split without refitting."""

import argparse
import hashlib
import json
from pathlib import Path

import torch

from .data import load_dataset
from .detector import FrozenDetector
from .evaluate import metrics


def confirm(dataset_path: Path, detector_path: Path):
    dataset = load_dataset(dataset_path)
    detector = FrozenDetector(detector_path)
    seeds = {w.seed for split in (dataset.train, dataset.validation, dataset.test) for w in split}
    if seeds.intersection(detector.manifest["development_seeds"]):
        raise ValueError("Confirmation seeds overlap development data")
    previous_threads = torch.get_num_threads()
    try:
        torch.set_num_threads(1)
        predictions = detector.predict(dataset.test)
    finally:
        torch.set_num_threads(previous_threads)
    labels = [w.has_leak for w in dataset.test]
    predicted = [p["is_leak"] for p in predictions]
    return {
        "schema_version": 1, "source": "synthetic", "split": "fresh-seed test",
        "model_version": detector.version, "dataset_sha256": dataset.sha256,
        "detector_manifest_sha256": hashlib.sha256((detector_path / "detector.json").read_bytes()).hexdigest(),
        "weights_sha256": detector.manifest["weights_sha256"],
        "threshold": detector.manifest["threshold"], "refitted": False,
        "export_seed_count": len(seeds), "test_seed_count": len({w.seed for w in dataset.test}),
        "test_seeds": sorted({w.seed for w in dataset.test}),
        "test": metrics(labels, predicted),
        "by_scenario": {
            scenario: metrics([labels[i] for i, w in enumerate(dataset.test) if w.scenario_id == scenario],
                              [predicted[i] for i, w in enumerate(dataset.test) if w.scenario_id == scenario])
            for scenario in sorted({w.scenario_id for w in dataset.test})},
        "limitations": ["Unseen seeds from the same fixed synthetic household model",
                         "Not real-world or unseen-household validation",
                         "Daily window classification; not interval-level localization",
                         "Calibration requires midnight UTC alignment"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--detector", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output}")
    report = confirm(args.dataset, args.detector)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        output.write(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report["test"], indent=2))


if __name__ == "__main__":
    main()
