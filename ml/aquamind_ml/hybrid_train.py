"""Unsupervised LSTM training on unmodified AMPds2 baseline days with unknown labels."""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform

import torch

from .hybrid_data import HybridDataset, HybridFlowNormalizer, load_hybrid_dataset
from .train import TrainingConfig, fit_sequences


def fit_hybrid_model(dataset: HybridDataset, config: TrainingConfig):
    normalizer = HybridFlowNormalizer.fit(dataset)
    references = tuple(w for w in dataset.validation if w.variant_kind == 'unmodified')
    if not references or any(w.injection_present or w.is_continuous_injection or
                             w.physical_leak_label != 'unknown' for w in references):
        raise ValueError('Unmodified unlabeled validation references are required')
    train = torch.tensor(normalizer.transform(dataset.train), dtype=torch.float32).unsqueeze(-1)
    validation = torch.tensor(normalizer.transform(references), dtype=torch.float32).unsqueeze(-1)
    model, report = fit_sequences(train, validation, config)
    report['unmodified_validation_windows'] = report.pop('validation_windows')
    for row in report['history']:
        row['unmodified_validation_mse'] = row.pop('validation_mse')
    return model, normalizer, report


def train_to_directory(dataset_path: Path, output: Path, config: TrainingConfig):
    if output.exists():
        raise FileExistsError(f'Refusing to overwrite {output}')
    dataset = load_hybrid_dataset(dataset_path)
    model, normalizer, report = fit_hybrid_model(dataset, config)
    output.mkdir(parents=True, exist_ok=False)
    weights = output / 'weights.pt'
    torch.save(model.state_dict(), weights)
    report.update({'schema': 'aquamind-hybrid-training-v1', 'source': 'AMPds2 real baseline',
                   'training_label_scope': 'unmodified and unlabeled; not verified normal',
                   'architecture': 'LSTM autoencoder', 'config': asdict(config),
                   'normalizer': asdict(normalizer), 'base_export_sha256': dataset.base_export_sha256,
                   'weights_sha256': hashlib.sha256(weights.read_bytes()).hexdigest(),
                   'source_sha256': {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                     for name in ('hybrid_train.py', 'train.py', 'model.py', 'hybrid_data.py',
                                                  'data.py', 'ampds2_hybrid.py')},
                   'environment': {'python': platform.python_version(), 'torch': str(torch.__version__),
                                   'platform': platform.platform(), 'device': 'cpu', 'threads': 1},
                   'selection': 'minimum unmodified-validation MSE; earliest epoch breaks ties',
                   'validation_injections_scored': False, 'test_evaluated': False})
    (output / 'training.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--epochs', type=int, default=20)
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    print(json.dumps(train_to_directory(args.dataset, args.output,
                                       TrainingConfig(seed=args.seed, epochs=args.epochs)), indent=2))


if __name__ == '__main__':
    main()
