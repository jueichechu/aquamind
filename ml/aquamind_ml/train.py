"""Deterministic CPU training on normal synthetic meter sequences."""

import argparse
from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import platform

import torch

from .data import FlowNormalizer, MeterDataset, load_dataset
from .model import LSTMAutoencoder


@dataclass(frozen=True)
class TrainingConfig:
    seed: int = 42
    epochs: int = 20
    batch_size: int = 64
    learning_rate: float = 0.001
    hidden_size: int = 32
    latent_size: int = 8

    def __post_init__(self):
        for name in ("epochs", "batch_size", "hidden_size", "latent_size"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        if type(self.seed) is not int or not 0 <= self.seed <= 0xFFFFFFFF:
            raise ValueError("seed must be a uint32 integer")
        if not math.isfinite(self.learning_rate) or self.learning_rate <= 0:
            raise ValueError("learning_rate must be positive and finite")


def fit_model(dataset: MeterDataset, config: TrainingConfig):
    """Select weights using normal validation loss; never transform or score test data."""
    normalizer = FlowNormalizer.fit(dataset)
    normal_validation = tuple(w for w in dataset.validation if not w.has_anomaly)
    if not normal_validation:
        raise ValueError("Normal validation windows are required for checkpoint selection")
    train = torch.tensor(normalizer.transform(dataset.train), dtype=torch.float32).unsqueeze(-1)
    validation = torch.tensor(normalizer.transform(normal_validation), dtype=torch.float32).unsqueeze(-1)
    model, report = fit_sequences(train, validation, config)
    report["normal_validation_windows"] = report.pop("validation_windows")
    for row in report["history"]:
        row["normal_validation_mse"] = row.pop("validation_mse")
    return model, normalizer, report


def fit_sequences(train: torch.Tensor, validation: torch.Tensor, config: TrainingConfig):
    """Shared deterministic optimizer; callers choose training/validation features."""
    for values in (train, validation):
        if (values.ndim != 3 or values.shape[0] < 1 or values.shape[1:] != (96, 1) or
                values.dtype != torch.float32 or values.device.type != "cpu" or
                not torch.isfinite(values).all()):
            raise ValueError("Expected finite nonempty CPU float32 [batch, 96, 1] tensors")
    previous_threads = torch.get_num_threads()
    previous_determinism = torch.are_deterministic_algorithms_enabled()
    previous_warn_only = torch.is_deterministic_algorithms_warn_only_enabled()
    try:
        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(config.seed)
            model = LSTMAutoencoder(config.hidden_size, config.latent_size)
            optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate)
            history = []
            best_loss, best_epoch, best_state = math.inf, 0, None
            for epoch in range(1, config.epochs + 1):
                model.train()
                order = torch.randperm(len(train))
                total = 0.0
                for indices in order.split(config.batch_size):
                    batch = train[indices]
                    optimizer.zero_grad()
                    loss = (model(batch) - batch).square().mean()
                    if not torch.isfinite(loss):
                        raise ValueError("Non-finite training loss")
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0, error_if_nonfinite=True)
                    optimizer.step()
                    total += loss.item() * len(batch)
                model.eval()
                with torch.inference_mode():
                    validation_loss = sum(
                        (model(batch) - batch).square().mean().item() * len(batch)
                        for batch in validation.split(config.batch_size)
                    ) / len(validation)
                if not math.isfinite(validation_loss):
                    raise ValueError("Non-finite validation loss")
                history.append({"epoch": epoch, "train_mse": total / len(train),
                                "validation_mse": validation_loss})
                if validation_loss < best_loss:
                    best_loss, best_epoch = validation_loss, epoch
                    best_state = deepcopy(model.state_dict())
            model.load_state_dict(best_state)
            return model, {"history": history, "selected_epoch": best_epoch,
                           "training_windows": len(train), "validation_windows": len(validation)}
    finally:
        torch.set_num_threads(previous_threads)
        torch.use_deterministic_algorithms(previous_determinism, warn_only=previous_warn_only)


def train_to_directory(dataset_path: Path, output: Path, config: TrainingConfig):
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite {output}")
    dataset = load_dataset(dataset_path)
    model, normalizer, report = fit_model(dataset, config)
    output.mkdir(parents=True, exist_ok=False)
    weights = output / "weights.pt"
    torch.save(model.state_dict(), weights)
    source_hashes = {
        name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in ("train.py", "model.py", "data.py")
    }
    report.update({
        "schema_version": 1, "source": "synthetic", "architecture": "LSTM autoencoder",
        "config": asdict(config), "normalizer": asdict(normalizer),
        "weights_sha256": hashlib.sha256(weights.read_bytes()).hexdigest(),
        "source_sha256": source_hashes,
        "environment": {"python": platform.python_version(), "torch": str(torch.__version__),
                        "platform": platform.platform(), "device": "cpu", "threads": 1},
        "selection": "minimum normal-validation MSE; earliest epoch breaks ties",
        "test_evaluated": False,
    })
    # This report is written last and is the completion marker for an artifact directory.
    (output / "training.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    report = train_to_directory(args.dataset, args.output, TrainingConfig(seed=args.seed, epochs=args.epochs))
    print(json.dumps({"output": str(args.output), "selected_epoch": report["selected_epoch"],
                      "history": report["history"], "test_evaluated": False}, indent=2))


if __name__ == "__main__":
    main()
