"""Select a hybrid reconstruction-MSE threshold using validation only."""

import argparse
import hashlib
import json
from pathlib import Path

import torch

from .calibration import residuals
from .evaluate import metrics, select_threshold
from .hybrid_data import HybridFlowNormalizer, load_hybrid_dataset
from .model import LSTMAutoencoder


def load_checkpoint(dataset_path: Path, checkpoint: Path):
    dataset = load_hybrid_dataset(dataset_path)
    training = json.loads((checkpoint / 'training.json').read_text())
    if training.get('schema') != 'aquamind-hybrid-training-v1':
        raise ValueError('Expected hybrid training artifact')
    weights = checkpoint / 'weights.pt'
    digest = hashlib.sha256(weights.read_bytes()).hexdigest()
    if digest != training['weights_sha256']:
        raise ValueError('Checkpoint weight checksum mismatch')
    normalizer = HybridFlowNormalizer(**training['normalizer'])
    if normalizer != HybridFlowNormalizer.fit(dataset) or training['base_export_sha256'] != dataset.base_export_sha256:
        raise ValueError('Dataset or training-only normalization mismatch')
    model = LSTMAutoencoder(training['config']['hidden_size'], training['config']['latent_size'])
    model.load_state_dict(torch.load(weights, map_location='cpu', weights_only=True))
    model.eval()
    return dataset, model, normalizer, training, digest


def score_windows(model, normalizer, windows) -> list[float]:
    return residuals(model, normalizer, windows).square().mean(dim=1).tolist()


def validate_dataset(dataset, model, normalizer) -> dict:
    """Uses only validation features/targets; test is never accessed or scored."""
    previous_threads = torch.get_num_threads()
    try:
        torch.set_num_threads(1)
        windows = dataset.validation
        scores = score_windows(model, normalizer, windows)
    finally:
        torch.set_num_threads(previous_threads)
    labels = [w.is_continuous_injection for w in windows]
    threshold = select_threshold(scores, labels)
    return summarize_validation(windows, scores, threshold)


def summarize_validation(windows, scores: list[float], threshold: float) -> dict:
    """Shared diagnostic report for a preselected threshold and aligned scores."""
    if len(windows) != len(scores) or not windows:
        raise ValueError('Expected aligned nonempty windows and scores')
    labels = [w.is_continuous_injection for w in windows]
    predictions = [value >= threshold for value in scores]
    references = {w.base_day_id: score for w, score in zip(windows, scores) if w.variant_kind == 'unmodified'}
    kind_reports = {}
    for kind in ('unmodified', 'continuous_injection', 'demand_confounder'):
        indices = [i for i, w in enumerate(windows) if w.variant_kind == kind]
        if not indices:
            raise ValueError('Validation requires references, continuous injections and demand confounders')
        count = sum(predictions[i] for i in indices)
        kind_reports[kind] = {'count': len(indices), 'alarms': count, 'alarm_rate': count / len(indices)}
    patterns = {}
    for rate, duration in sorted({(w.added_gpm, w.end_interval_exclusive - w.start_interval)
                                 for w in windows if w.is_continuous_injection}):
        indices = [i for i, w in enumerate(windows) if w.is_continuous_injection and
                   (w.added_gpm, w.end_interval_exclusive - w.start_interval) == (rate, duration)]
        hits = sum(predictions[i] for i in indices)
        patterns[f'{rate:g}gpm/{duration * 15}min'] = {
            'count': len(indices), 'detected': hits, 'sensitivity': hits / len(indices)}
    result = metrics(labels, predictions)
    result['balanced_accuracy'] = (result['recall'] + result['tn'] / (result['tn'] + result['fp'])) / 2
    return {'threshold': threshold, 'comparison': '>=', 'validation': result,
            'always_positive_reference': metrics(labels, [True] * len(labels)),
            'by_variant_kind': kind_reports, 'by_injection_pattern': patterns,
            'validation_rows': [{'base_day_id': w.base_day_id, 'variant_id': w.variant_id,
                                 'variant_kind': w.variant_kind, 'is_continuous_injection': label,
                                 'score': score, 'alarm': prediction,
                                 'score_change_from_unmodified': score - references[w.base_day_id]}
                                for w, label, score, prediction in zip(windows, labels, scores, predictions)]}


def validate(dataset_path: Path, checkpoint: Path) -> dict:
    dataset, model, normalizer, training, weights_hash = load_checkpoint(dataset_path, checkpoint)
    return {'schema': 'aquamind-hybrid-validation-v1', 'protocol': 'ampds2-hybrid-v1',
            'target': 'controlled continuous-injection detection; physical leak labels unknown',
            'score': 'daily mean squared reconstruction error in normalized flow units',
            'selection': 'maximum validation F1; higher threshold breaks ties',
            'dataset_sha256': dataset.sha256, 'weights_sha256': weights_hash,
            'model_version': 'ampds2-lstm-' + weights_hash[:12],
            'selected_epoch': training['selected_epoch'], 'normalizer': training['normalizer'],
            'validation_base_days': len({w.base_day_id for w in dataset.validation}),
            'test_evaluated': False,
            'evaluation_source_sha256': {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                         for name in ('hybrid_validate.py', 'evaluate.py', 'calibration.py')},
            'limitations': ['Validation selects checkpoint and threshold; results are optimistic',
                            'One real household with controlled synthetic injections',
                            'Unmodified and demand-confounder references are nominal negatives, not verified leak-free data',
                            'Related variants are correlated; this is not real-world leak F1',
                            'Grid composition favors positive class; report reference alarm rates alongside F1'],
            **validate_dataset(dataset, model, normalizer)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f'Refusing to overwrite {args.output}')
    report = validate(args.dataset, args.checkpoint)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        stream.write(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({k: report[k] for k in ('threshold', 'validation', 'always_positive_reference', 'by_variant_kind')}, indent=2))


if __name__ == '__main__':
    main()
