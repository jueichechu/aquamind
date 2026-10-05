"""Calibrate a window-MSE threshold on validation, then evaluate held-out seeds."""

import argparse
import hashlib
import json
import math
from pathlib import Path

import torch

from .data import FlowNormalizer, load_dataset
from .model import LSTMAutoencoder, reconstruction_errors


def metrics(labels: list[bool], predictions: list[bool]) -> dict:
    if not labels or len(labels) != len(predictions):
        raise ValueError("Expected nonempty aligned labels and predictions")
    if any(type(value) is not bool for value in labels + predictions):
        raise ValueError("Labels and predictions must be booleans")
    tp = sum(a and b for a, b in zip(labels, predictions))
    fp = sum(not a and b for a, b in zip(labels, predictions))
    fn = sum(a and not b for a, b in zip(labels, predictions))
    tn = len(labels) - tp - fp - fn
    return {"count": len(labels), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": tp / (tp + fp) if tp + fp else 0.0,
            "recall": tp / (tp + fn) if tp + fn else 0.0,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0}


def select_threshold(scores: list[float], labels: list[bool]) -> float:
    if not scores or len(scores) != len(labels):
        raise ValueError("Expected aligned validation scores and labels")
    if any(not math.isfinite(v) or v < 0 for v in scores):
        raise ValueError("Scores must be finite and non-negative")
    if any(type(v) is not bool for v in labels) or not any(labels) or all(labels):
        raise ValueError("Validation requires both positive and negative boolean labels")
    # Include every decision boundary; ties favor the higher, more conservative threshold.
    candidates = sorted(set(scores) | {math.nextafter(max(scores), math.inf)})
    return max(candidates, key=lambda threshold: (
        metrics(labels, [score >= threshold for score in scores])["f1"], threshold,
    ))


def load_checkpoint(dataset_path: Path, checkpoint: Path):
    """Load and verify a trained checkpoint without scoring any split."""
    dataset = load_dataset(dataset_path)
    training = json.loads((checkpoint / "training.json").read_text())
    weights = checkpoint / "weights.pt"
    weights_hash = hashlib.sha256(weights.read_bytes()).hexdigest()
    if weights_hash != training["weights_sha256"]:
        raise ValueError("Checkpoint weight checksum mismatch")
    normalizer = FlowNormalizer(**training["normalizer"])
    if normalizer.dataset_sha256 != dataset.sha256:
        raise ValueError("Dataset checksum differs from training dataset")
    if normalizer != FlowNormalizer.fit(dataset):
        raise ValueError("Normalization does not match training-only fit")
    model = LSTMAutoencoder(training["config"]["hidden_size"], training["config"]["latent_size"])
    model.load_state_dict(torch.load(weights, map_location="cpu", weights_only=True))
    model.eval()
    return dataset, model, normalizer, training, weights_hash


def evaluate(dataset_path: Path, checkpoint: Path) -> dict:
    dataset, model, normalizer, training, weights_hash = load_checkpoint(dataset_path, checkpoint)

    def score(windows):
        flows = torch.tensor(normalizer.transform(windows), dtype=torch.float32).unsqueeze(-1)
        with torch.inference_mode():
            return [value for batch in flows.split(64)
                    for value in reconstruction_errors(batch, model(batch))[1].tolist()]

    previous_threads = torch.get_num_threads()
    try:
        torch.set_num_threads(1)
        validation_scores = score(dataset.validation)
        validation_labels = [w.has_leak for w in dataset.validation]
        threshold = select_threshold(validation_scores, validation_labels)
        # Only after freezing the validation-selected threshold may test scores be computed.
        test_scores = score(dataset.test)
    finally:
        torch.set_num_threads(previous_threads)
    predictions = [s >= threshold for s in test_scores]
    labels = [w.has_leak for w in dataset.test]
    return {
        "schema_version": 1, "source": "synthetic", "unit": "96-interval daily window",
        "target": "physical leak; irrigation-after-rain is negative",
        "score": "mean squared reconstruction error in normalized flow units",
        "threshold": threshold, "comparison": ">=",
        "selection": "maximum validation F1; higher threshold breaks ties",
        "dataset_sha256": dataset.sha256, "weights_sha256": weights_hash,
        "model_version": f"lstm-{weights_hash[:12]}",
        "training": training,
        "evaluation_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "evaluation_torch": str(torch.__version__),
        "validation": metrics(validation_labels, [s >= threshold for s in validation_scores]),
        "test": metrics(labels, predictions),
        "test_by_scenario": {
            scenario: metrics(
                [labels[i] for i, w in enumerate(dataset.test) if w.scenario_id == scenario],
                [predictions[i] for i, w in enumerate(dataset.test) if w.scenario_id == scenario],
            ) for scenario in sorted({w.scenario_id for w in dataset.test})
        },
        "test_rows": [{"seed": w.seed, "scenario": w.scenario_id, "start": w.start_timestamp,
                       "has_leak": label, "score": value, "predicted_leak": prediction}
                      for w, label, value, prediction in zip(dataset.test, labels, test_scores, predictions)],
        "limitations": ["Synthetic seed holdout, not real-world field validation",
                        "Scenario variants within each split are correlated",
                        "Validation selects both checkpoint and threshold; validation F1 is optimistic",
                        "Daily reconstruction score is not an interval-level diagnosis or probability"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output}")
    report = evaluate(args.dataset, args.checkpoint)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        output.write(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({key: report[key] for key in ("threshold", "validation", "test")}, indent=2))


if __name__ == "__main__":
    main()
