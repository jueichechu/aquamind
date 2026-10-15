from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch

from aquamind_ml.hybrid_detector import FrozenHybridDetector, freeze_detector
from aquamind_ml.hybrid_data import load_hybrid_dataset
from aquamind_ml.hybrid_persistence import validate
from aquamind_ml.hybrid_train import train_to_directory
from aquamind_ml.train import TrainingConfig
from test_hybrid_data import fixture


class HybridDetectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.root = Path(cls.directory.name)
        cls.path = cls.root / 'data.json'
        cls.path.write_text(json.dumps(fixture()))
        cls.training = cls.root / 'training'
        train_to_directory(cls.path, cls.training, TrainingConfig(epochs=1, hidden_size=4, latent_size=2))
        cls.validation = cls.root / 'validation.json'
        cls.report = validate(cls.path, cls.training)
        cls.validation.write_text(json.dumps(cls.report))
        cls.output = cls.root / 'detector'
        freeze_detector(cls.path, cls.training, cls.validation, cls.output)

    def test_reload_matches_validation_without_fitting_or_target_metadata(self):
        windows = load_hybrid_dataset(self.path).validation
        previous_threads = torch.get_num_threads()
        try:
            torch.set_num_threads(1)
            with patch('aquamind_ml.hybrid_detector.HybridFlowNormalizer.fit', side_effect=AssertionError('refit')), \
                 patch('aquamind_ml.hybrid_detector.SustainedCalibration.fit', side_effect=AssertionError('refit')):
                detector = FrozenHybridDetector(self.output)
                predictions = detector.predict(windows)
                changed = tuple(replace(w, variant_kind='ignored', is_continuous_injection=not w.is_continuous_injection,
                                        physical_leak_label='ignored') for w in windows)
                self.assertEqual(predictions, detector.predict(changed))
                self.assertEqual(predictions, FrozenHybridDetector(self.output).predict(windows))
            for prediction, row in zip(predictions, self.report['methods']['strict_lstm_residual']['validation_rows']):
                self.assertEqual(prediction['score'], row['score'])
                self.assertEqual(prediction['is_continuous_pattern'], row['alarm'])
                self.assertNotIn('is_leak', prediction)
            self.assertFalse(detector.manifest['test_evaluated'])
        finally:
            torch.set_num_threads(previous_threads)

    def test_refuses_overwrite_and_mismatched_validation(self):
        with self.assertRaises(FileExistsError):
            freeze_detector(self.path, self.training, self.validation, self.output)
        for patch_data in ({'weights_sha256': 'bad'}, {'test_evaluated': True}, {'source_sha256': {}},
                           {'selected_epoch': 999}):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'invalid.json'
                path.write_text(json.dumps(self.report | patch_data))
                with self.assertRaises(ValueError):
                    freeze_detector(self.path, self.training, path, Path(directory) / 'detector')

    def test_checks_frozen_weights_code_contract_and_threshold(self):
        original = json.loads((self.output / 'detector.json').read_text())
        for changed in ({'source_sha256': {}}, {'threshold': -1}, {'threshold': True},
                        {'score': 'unknown'}, {'window_intervals': 15}):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                root.joinpath('detector.json').write_text(json.dumps(original | changed))
                root.joinpath('weights.pt').write_bytes((self.output / 'weights.pt').read_bytes())
                with self.assertRaises(ValueError):
                    FrozenHybridDetector(root)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.joinpath('detector.json').write_text(json.dumps(original))
            root.joinpath('weights.pt').write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                FrozenHybridDetector(root)
