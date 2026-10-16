"""Score the pinned frozen hybrid detector on the chronological held-out period."""

import argparse
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import platform
import random

import torch

from .hybrid_data import load_hybrid_dataset
from .hybrid_detector import FrozenHybridDetector
from .hybrid_validate import summarize_validation

FREEZE_RECORD = Path(__file__).resolve().parents[2] / 'evals/baselines/ampds2-detector-freeze-v1.json'


def block_bootstrap(windows, alarms: list[bool], repetitions: int = 1000) -> dict:
    """Fixed seven-day circular moving blocks; related variants remain grouped."""
    if not windows or len(windows) != len(alarms) or type(repetitions) is not int or repetitions < 1:
        raise ValueError('Expected aligned nonempty windows/alarms and positive repetitions')
    days = {}
    for window, alarm in zip(windows, alarms):
        if type(alarm) is not bool:
            raise ValueError('Alarms must be boolean')
        counts = days.setdefault(window.base_day_id, [0] * 8)
        label = window.is_continuous_injection
        counts[0 if label and alarm else 1 if alarm else 2 if label else 3] += 1
        if window.variant_kind == 'unmodified':
            counts[4] += alarm
            counts[5] += 1
        elif window.variant_kind == 'demand_confounder':
            counts[6] += alarm
            counts[7] += 1
    ordered = [days[key] for key in sorted(days)]
    block_days = min(7, len(ordered))
    rng = random.Random(42)
    samples = {key: [] for key in ('precision', 'recall', 'f1', 'unmodified_alarm_rate', 'demand_confounder_alarm_rate')}
    for _ in range(repetitions):
        indices = []
        while len(indices) < len(ordered):
            start = rng.randrange(len(ordered))
            indices.extend((start + offset) % len(ordered) for offset in range(block_days))
        total = [sum(ordered[index][column] for index in indices[:len(ordered)]) for column in range(8)]
        tp, fp, fn, _, original_alarms, original_n, demand_alarms, demand_n = total
        if not original_n or not demand_n:
            raise ValueError('Bootstrap requires both reference kinds')
        values = (tp / (tp + fp) if tp + fp else 0, tp / (tp + fn) if tp + fn else 0,
                  2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0,
                  original_alarms / original_n, demand_alarms / demand_n)
        for key, value in zip(samples, values):
            samples[key].append(value)
    return {'method': 'seven-day circular moving-block percentile bootstrap over ordered base days',
            'repetitions': repetitions, 'seed': 42, 'base_days': len(days), 'block_days': block_days,
            'confidence_level': .95, 'percentile_method': 'nearest rank',
            'intervals': {key: {'lower': sorted(values)[math.ceil(.025 * repetitions) - 1],
                                'upper': sorted(values)[math.ceil(.975 * repetitions) - 1]}
                          for key, values in samples.items()}}


def evaluate_test(dataset, detector) -> dict:
    windows = dataset.test
    if not windows:
        raise ValueError('Empty held-out partition')
    development = set(detector.manifest['development_base_days'])
    last_development = datetime.fromisoformat(detector.manifest['development_last_timestamp'])
    if any(w.base_day_id in development or
           datetime.fromisoformat(w.start_timestamp) - last_development < timedelta(days=2) for w in windows):
        raise ValueError('Held-out days overlap or violate the development boundary gap')
    previous_threads = torch.get_num_threads()
    try:
        torch.set_num_threads(1)
        predictions = detector.predict(windows)
    finally:
        torch.set_num_threads(previous_threads)
    scores = [row['score'] for row in predictions]
    alarms = [row['is_continuous_pattern'] for row in predictions]
    if len(predictions) != len(windows) or any(alarm != (score >= detector.threshold) for score, alarm in zip(scores, alarms)):
        raise ValueError('Frozen prediction contract mismatch')
    diagnostics = summarize_validation(windows, scores, detector.threshold)
    diagnostics['test'] = diagnostics.pop('validation')
    diagnostics['test_rows'] = diagnostics.pop('validation_rows')
    return diagnostics | {'uncertainty': block_bootstrap(windows, alarms),
                           'test_base_days': len({w.base_day_id for w in windows}),
                           'first_test_day': min(w.start_timestamp for w in windows),
                           'last_test_day': max(w.start_timestamp for w in windows)}


def confirm(dataset_path: Path, detector_path: Path, freeze_record_path: Path = FREEZE_RECORD) -> dict:
    record = json.loads(freeze_record_path.read_text())
    manifest_bytes = (detector_path / 'detector.json').read_bytes()
    if (record.get('schema') != 'aquamind-hybrid-freeze-record-v1' or record.get('test_evaluated') is not False or
            hashlib.sha256(manifest_bytes).hexdigest() != record['detector_manifest_sha256']):
        raise ValueError('Detector differs from the pre-test freeze record')
    detector = FrozenHybridDetector(detector_path)
    dataset = load_hybrid_dataset(dataset_path)
    if (dataset.sha256 != record['dataset_sha256'] or detector.version != record['model_version'] or
            detector.manifest['weights_sha256'] != record['weights_sha256'] or
            detector.threshold != record['threshold'] or
            dataset.training_sha256 != detector.normalizer.training_sha256):
        raise ValueError('Dataset or detector does not match the frozen experiment')
    return {'schema': 'aquamind-hybrid-heldout-v1', 'source': 'real AMPds2 consumption with controlled synthetic patterns',
            'target': 'controlled continuous-injection detection; real physical leak labels unknown',
            'pattern_protocol': 'ampds2-hybrid-v1', 'scoring_protocol': 'strict-persistence-v1',
            'model_version': detector.version, 'dataset_sha256': dataset.sha256,
            'detector_manifest_sha256': record['detector_manifest_sha256'],
            'freeze_record_sha256': hashlib.sha256(freeze_record_path.read_bytes()).hexdigest(),
            'weights_sha256': record['weights_sha256'], 'refitted': False, 'threshold_changed': False,
            'test_evaluated': True,
            'environment': {'python': platform.python_version(), 'torch': str(torch.__version__), 'device': 'cpu', 'threads': 1},
            'source_sha256': {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                              for name in ('hybrid_confirm.py', 'hybrid_validate.py', 'evaluate.py')},
            'limitations': ['One household and one temporal holdout; no unseen-household generalization',
                            'Real baseline leak labels unknown; positive patterns are injected',
                            'Designed class composition is not real leak prevalence',
                            'Bootstrap intervals reflect within-period variation, not household diversity or all temporal dependence',
                            'Short low-flow, interrupted, and cross-midnight patterns remain limitations',
                            'This period is now inspected and cannot be fresh confirmation for further tuning'],
            **evaluate_test(dataset, detector)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--detector', type=Path, required=True)
    parser.add_argument('--freeze-record', type=Path, default=FREEZE_RECORD)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Refusing to overwrite report')
    report = confirm(args.dataset, args.detector, args.freeze_record)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        stream.write(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({key: report[key] for key in ('test', 'by_variant_kind', 'uncertainty')}, indent=2))


if __name__ == '__main__':
    main()
