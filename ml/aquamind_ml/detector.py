"""Freeze and reload a calibrated detector without fitting at inference time."""

import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import shutil

import torch

from .calibration import ResidualCalibration, residuals
from .data import FlowNormalizer
from .evaluate import load_checkpoint
from .model import LSTMAutoencoder
from .validate_scoring import validate_scoring


def freeze_detector(dataset_path: Path, checkpoint: Path, output: Path):
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite {output}")
    dataset, _, normalizer, training, weights_hash = load_checkpoint(dataset_path, checkpoint)
    validation = validate_scoring(dataset_path, checkpoint)
    manifest = {
        "schema_version": 1, "source": "synthetic", "score": "positive_standardized_residual_v1",
        "weights_sha256": weights_hash, "normalizer": asdict(normalizer),
        "model": {name: training["config"][name] for name in ("hidden_size", "latent_size")},
        "calibration": validation["calibration"],
        "threshold": validation["results"]["positive_standardized_residual"]["threshold"],
        "comparison": ">=", "validation": validation["results"]["positive_standardized_residual"]["metrics"],
        # Exclude even previously inspected baseline test seeds from confirmation.
        "development_seeds": sorted({w.seed for split in (dataset.train, dataset.validation, dataset.test) for w in split}),
        "source_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                          for name in ("model.py", "calibration.py", "detector.py")},
    }
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(checkpoint / "weights.pt", output / "weights.pt")
    (output / "detector.json").write_text(json.dumps(manifest, sort_keys=True, indent=2, allow_nan=False) + "\n")
    return manifest


class FrozenDetector:
    def __init__(self, directory: Path):
        contents = (directory / "detector.json").read_bytes()
        self.manifest = json.loads(contents)
        m = self.manifest
        if m["schema_version"] != 1 or m["score"] != "positive_standardized_residual_v1" or m["comparison"] != ">=":
            raise ValueError("Unsupported detector contract")
        if not math.isfinite(m["threshold"]) or m["threshold"] < 0:
            raise ValueError("Invalid detector threshold")
        if hashlib.sha256((directory / "weights.pt").read_bytes()).hexdigest() != m["weights_sha256"]:
            raise ValueError("Detector weight checksum mismatch")
        self.version = "detector-" + hashlib.sha256(contents).hexdigest()[:16]
        self.normalizer = FlowNormalizer(**m["normalizer"])
        self.calibration = ResidualCalibration(**m["calibration"])
        self.model = LSTMAutoencoder(**m["model"])
        self.model.load_state_dict(torch.load(directory / "weights.pt", map_location="cpu", weights_only=True))
        self.model.eval()

    def predict(self, windows):
        scores = self.calibration.score(residuals(self.model, self.normalizer, windows))
        return [{"score": score, "is_leak": score >= self.manifest["threshold"],
                 "model_version": self.version} for score in scores]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    freeze_detector(args.dataset, args.checkpoint, args.output)
    print(FrozenDetector(args.output).version)


if __name__ == "__main__":
    main()
