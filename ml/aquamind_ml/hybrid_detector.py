"""Freeze strict-persistence inference before held-out hybrid evaluation."""

import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import shutil

import torch

from .calibration import residuals
from .hybrid_data import HybridFlowNormalizer
from .hybrid_persistence import strict_persistence
from .hybrid_sustained import SustainedCalibration
from .hybrid_validate import load_checkpoint
from .model import LSTMAutoencoder

RUNTIME_SOURCES = ('hybrid_detector.py', 'hybrid_persistence.py', 'calibration.py',
                   'model.py', 'data.py', 'hybrid_data.py')


def source_hashes(names):
    return {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in names}


def freeze_detector(dataset_path: Path, checkpoint: Path, validation_path: Path, output: Path):
    if output.exists():
        raise FileExistsError(f'Refusing to overwrite {output}')
    dataset, model, normalizer, training, weights_hash = load_checkpoint(dataset_path, checkpoint)
    validation_bytes = validation_path.read_bytes()
    report = json.loads(validation_bytes)
    if (report.get('schema') != 'aquamind-hybrid-strict-persistence-validation-v1' or
            report.get('scoring_protocol') != 'strict-persistence-v1' or
            report.get('pattern_protocol') != 'ampds2-hybrid-v1' or report.get('test_evaluated') is not False or
            report.get('dataset_sha256') != dataset.sha256 or report.get('weights_sha256') != weights_hash or
            report.get('normalizer') != training['normalizer'] or
            report.get('selected_epoch') != training['selected_epoch']):
        raise ValueError('Validation report does not match this checkpoint and protocol')
    expected_sources = source_hashes(('hybrid_persistence.py', 'hybrid_sustained.py', 'hybrid_validate.py', 'calibration.py'))
    if report.get('source_sha256') != expected_sources:
        raise ValueError('Validation scoring source changed; create a new validation report')
    previous_threads = torch.get_num_threads()
    try:
        torch.set_num_threads(1)
        calibration = SustainedCalibration.fit(model, normalizer, dataset.train)
    finally:
        torch.set_num_threads(previous_threads)
    if json.loads(json.dumps(asdict(calibration))) != report['training_calibration']:
        raise ValueError('Calibration differs from training-only fit')
    selected = report['methods']['strict_lstm_residual']
    threshold = selected['threshold']
    if type(threshold) not in (int, float) or not math.isfinite(threshold) or threshold < 0:
        raise ValueError('Invalid selected threshold')
    if selected['validation']['count'] != len(dataset.validation) or any(
            selected['by_variant_kind'][kind]['alarm_rate'] > .05
            for kind in ('unmodified', 'demand_confounder')):
        raise ValueError('Validation does not meet declared alarm constraints')
    manifest = {'schema': 'aquamind-frozen-hybrid-detector-v1', 'score': 'strict-persistence-v1',
                'target': 'controlled continuous patterns; physical leak labels unknown',
                'weights_sha256': weights_hash, 'normalizer': asdict(normalizer),
                'model': {name: training['config'][name] for name in ('hidden_size', 'latent_size')},
                'calibration': {'center': calibration.center, 'scale': calibration.scale},
                'window_intervals': 16, 'comparison': '>=', 'threshold': threshold,
                'validation': {key: selected[key] for key in ('validation', 'by_variant_kind', 'by_injection_pattern')},
                'validation_report_sha256': hashlib.sha256(validation_bytes).hexdigest(),
                'development_base_days': sorted({w.base_day_id for split in (dataset.train, dataset.validation) for w in split}),
                'development_last_timestamp': dataset.validation[-1].start_timestamp,
                'source_sha256': source_hashes(RUNTIME_SOURCES), 'test_evaluated': False,
                'limitations': report['limitations']}
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(checkpoint / 'weights.pt', output / 'weights.pt')
    (output / 'detector.json').write_text(json.dumps(manifest, sort_keys=True, indent=2, allow_nan=False) + '\n')
    return manifest


class FrozenHybridDetector:
    def __init__(self, directory: Path):
        contents = (directory / 'detector.json').read_bytes()
        manifest = json.loads(contents)
        if (manifest.get('schema') != 'aquamind-frozen-hybrid-detector-v1' or
                manifest.get('score') != 'strict-persistence-v1' or manifest.get('comparison') != '>=' or
                type(manifest.get('window_intervals')) is not int or manifest['window_intervals'] != 16):
            raise ValueError('Unsupported hybrid detector contract')
        threshold = manifest['threshold']
        if type(threshold) not in (int, float) or not math.isfinite(threshold) or threshold < 0:
            raise ValueError('Invalid threshold')
        if manifest['source_sha256'] != source_hashes(RUNTIME_SOURCES):
            raise ValueError('Frozen inference source mismatch')
        if hashlib.sha256((directory / 'weights.pt').read_bytes()).hexdigest() != manifest['weights_sha256']:
            raise ValueError('Frozen weights checksum mismatch')
        self.manifest = manifest
        self.version = 'hybrid-detector-' + hashlib.sha256(contents).hexdigest()[:16]
        self.threshold = float(threshold)
        self.normalizer = HybridFlowNormalizer(**manifest['normalizer'])
        self.calibration = SustainedCalibration(tuple(manifest['calibration']['center']),
                                                tuple(manifest['calibration']['scale']))
        self.model = LSTMAutoencoder(**manifest['model'])
        self.model.load_state_dict(torch.load(directory / 'weights.pt', map_location='cpu', weights_only=True))
        self.model.eval()

    def predict(self, windows):
        errors = residuals(self.model, self.normalizer, windows)
        standardized = (errors - errors.new_tensor(self.calibration.center)) / errors.new_tensor(self.calibration.scale)
        scores = strict_persistence(standardized)
        return [{'score': score, 'is_continuous_pattern': score >= self.threshold,
                 'model_version': self.version} for score in scores]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--validation', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    freeze_detector(args.dataset, args.checkpoint, args.validation, args.output)
    print(FrozenHybridDetector(args.output).version)


if __name__ == '__main__':
    main()
