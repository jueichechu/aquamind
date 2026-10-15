"""Validation-only ablation of background-flow persistence and LSTM residuals."""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import torch

from .calibration import residuals
from .hybrid_sustained import SustainedCalibration, select_constrained_threshold
from .hybrid_validate import load_checkpoint, summarize_validation


def persistent_floor(values: torch.Tensor) -> list[float]:
    """Four-hour lower quartile; accepts signed residuals or measured GPM."""
    if (values.ndim != 2 or values.shape[0] < 1 or values.shape[1] != 96 or
            values.dtype != torch.float32 or not torch.isfinite(values).all()):
        raise ValueError('Expected finite nonempty float32 [windows, 96] values')
    return values.unfold(1, 16, 1).kthvalue(4, dim=-1).values.amax(dim=1).clamp_min(0).tolist()


def compare(dataset, model, normalizer) -> dict:
    previous_threads = torch.get_num_threads()
    try:
        torch.set_num_threads(1)
        calibration = SustainedCalibration.fit(model, normalizer, dataset.train)
        errors = residuals(model, normalizer, dataset.validation)
        flows = torch.tensor([w.flow_rates_gpm for w in dataset.validation], dtype=torch.float32)
        centered_gpm = (errors - errors.new_tensor(calibration.center)) * normalizer.scale_gpm
        scores = {'slot_standardized_lstm_residual': calibration.score(errors),
                  'centered_lstm_residual_gpm': persistent_floor(centered_gpm),
                  'measured_flow_gpm_model_free': persistent_floor(flows)}
        return {'training_calibration': asdict(calibration),
                'methods': {name: summarize_validation(dataset.validation, values,
                            select_constrained_threshold(dataset.validation, values))
                            for name, values in scores.items()},
                'test_evaluated': False}
    finally:
        torch.set_num_threads(previous_threads)


def validate(dataset_path: Path, checkpoint: Path) -> dict:
    dataset, model, normalizer, training, digest = load_checkpoint(dataset_path, checkpoint)
    return {'schema': 'aquamind-hybrid-background-ablation-v1',
            'pattern_protocol': 'ampds2-hybrid-v1', 'scoring_protocol': 'background-ablation-v1',
            'target': 'continuous injected patterns, not real physical leak truth',
            'selection': 'maximum validation F1 with <=5% alarms separately on unmodified and demand-confounder references; higher threshold breaks ties',
            'dataset_sha256': dataset.sha256, 'weights_sha256': digest,
            'selected_epoch': training['selected_epoch'], 'normalizer': training['normalizer'],
            'model_free_method': 'measured_flow_gpm_model_free',
            'source_sha256': {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                              for name in ('hybrid_floor.py', 'hybrid_sustained.py', 'hybrid_validate.py', 'calibration.py')},
            'limitations': ['Validation development on one household; optimistic metrics',
                            'Real baseline labels unknown and added patterns synthetic',
                            'Related variants are correlated and do not reflect field prevalence',
                            'Model-free performance is not evidence of LSTM contribution',
                            'Only within-day four-hour patterns; no midnight wrapping'],
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
    print(json.dumps({name: {key: result[key] for key in ('threshold', 'validation', 'by_variant_kind')}
                      for name, result in report['methods'].items()}, indent=2))


if __name__ == '__main__':
    main()
