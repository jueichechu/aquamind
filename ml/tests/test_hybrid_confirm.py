from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aquamind_ml.hybrid_confirm import block_bootstrap, confirm, evaluate_test
from aquamind_ml.hybrid_data import load_hybrid_dataset
from aquamind_ml.hybrid_detector import FrozenHybridDetector, freeze_detector
from aquamind_ml.hybrid_persistence import validate
from aquamind_ml.hybrid_train import train_to_directory
from aquamind_ml.train import TrainingConfig
from test_hybrid_data import fixture


class HybridConfirmationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.root = Path(cls.directory.name)
        cls.path = cls.root / 'data.json'
        cls.path.write_text(json.dumps(fixture()))
        train_to_directory(cls.path, cls.root / 'training', TrainingConfig(epochs=1, hidden_size=4, latent_size=2))
        validation = cls.root / 'validation.json'
        validation.write_text(json.dumps(validate(cls.path, cls.root / 'training')))
        cls.detector_path = cls.root / 'detector'
        freeze_detector(cls.path, cls.root / 'training', validation, cls.detector_path)
        detector = FrozenHybridDetector(cls.detector_path)
        cls.record = cls.root / 'freeze.json'
        cls.record.write_text(json.dumps({'schema': 'aquamind-hybrid-freeze-record-v1', 'test_evaluated': False,
            'detector_manifest_sha256': hashlib.sha256((cls.detector_path / 'detector.json').read_bytes()).hexdigest(),
            'dataset_sha256': detector.normalizer.dataset_sha256, 'model_version': detector.version,
            'weights_sha256': detector.manifest['weights_sha256'], 'threshold': detector.threshold}))

    def test_frozen_test_evaluation_does_not_fit_or_select_threshold(self):
        with patch('aquamind_ml.hybrid_detector.HybridFlowNormalizer.fit', side_effect=AssertionError('refit')), \
             patch('aquamind_ml.hybrid_detector.SustainedCalibration.fit', side_effect=AssertionError('refit')), \
             patch('aquamind_ml.hybrid_sustained.select_constrained_threshold', side_effect=AssertionError('threshold tuning')):
            report = confirm(self.path, self.detector_path, self.record)
        self.assertFalse(report['refitted'])
        self.assertFalse(report['threshold_changed'])
        self.assertTrue(report['test_evaluated'])
        self.assertEqual(report['test']['count'], 14)
        self.assertEqual(report['test_base_days'], 1)
        self.assertEqual(len(report['by_injection_pattern']), 12)
        self.assertEqual(len(report['test_rows']), 14)
        self.assertEqual(report['threshold'], json.loads(self.record.read_text())['threshold'])

    def test_rejects_changed_artifacts_dataset_and_overlapping_days_before_prediction(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            bad_record = path / 'record.json'
            bad_record.write_text(self.record.read_text().replace('detector_manifest_sha256', 'wrong'))
            with self.assertRaises((ValueError, KeyError)):
                confirm(self.path, self.detector_path, bad_record)
            data_path = path / 'data.json'
            data_path.write_text(self.path.read_text() + ' ')
            with patch('aquamind_ml.hybrid_confirm.FrozenHybridDetector.predict', side_effect=AssertionError('must reject before inference')):
                with self.assertRaises(ValueError):
                    confirm(data_path, self.detector_path, self.record)
                data = load_hybrid_dataset(self.path)
                detector = FrozenHybridDetector(self.detector_path)
                with self.assertRaisesRegex(ValueError, 'overlap'):
                    evaluate_test(replace(data, test=data.validation), detector)

    def test_block_bootstrap_groups_related_variants_and_repeats_exactly(self):
        data = load_hybrid_dataset(self.path)
        windows, alarms = [], []
        for day in range(10):
            for row in data.test:
                windows.append(replace(row, base_day_id=f'day-{day:02d}'))
                alarms.append(row.is_continuous_injection if day < 5 else False)
        result = block_bootstrap(windows, alarms, repetitions=100)
        self.assertEqual(result, block_bootstrap(windows, alarms, repetitions=100))
        repeated_windows = [w for w in windows for _ in range(2)]
        repeated_alarms = [a for a in alarms for _ in range(2)]
        self.assertEqual(result, block_bootstrap(repeated_windows, repeated_alarms, repetitions=100))
        self.assertEqual(result['base_days'], 10)
        self.assertEqual(result['block_days'], 7)
        self.assertLess(result['intervals']['recall']['lower'], result['intervals']['recall']['upper'])
