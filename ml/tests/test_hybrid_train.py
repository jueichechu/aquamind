from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

import torch

from aquamind_ml.hybrid_data import load_hybrid_dataset
from aquamind_ml.hybrid_train import fit_hybrid_model, train_to_directory
from aquamind_ml.model import LSTMAutoencoder
from aquamind_ml.train import TrainingConfig
from test_hybrid_data import fixture


class HybridTrainingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'dataset.json'
        self.path.write_text(json.dumps(fixture()))
        self.dataset = load_hybrid_dataset(self.path)
        self.config = TrainingConfig(epochs=2, hidden_size=4, latent_size=2)

    def test_reproducible_without_test_or_injected_validation_features(self):
        first, norm, report = fit_hybrid_model(self.dataset, self.config)
        references = tuple(w for w in self.dataset.validation if w.variant_kind == 'unmodified')
        second, norm2, report2 = fit_hybrid_model(replace(self.dataset, validation=references, test=()), self.config)
        self.assertEqual(norm, norm2)
        self.assertEqual(report, report2)
        self.assertEqual(report['unmodified_validation_windows'], 1)
        self.assertEqual(report['selected_epoch'], min(report['history'], key=lambda r: r['unmodified_validation_mse'])['epoch'])
        for key, value in first.state_dict().items():
            torch.testing.assert_close(value, second.state_dict()[key], rtol=0, atol=0)

    def test_saved_artifact_and_no_overwrite(self):
        output = Path(self.directory.name) / 'run'
        report = train_to_directory(self.path, output, self.config)
        self.assertFalse(report['test_evaluated'])
        self.assertFalse(report['validation_injections_scored'])
        self.assertIn('unlabeled', report['training_label_scope'])
        self.assertEqual(json.loads((output / 'training.json').read_text()), report)
        model = LSTMAutoencoder(4, 2)
        model.load_state_dict(torch.load(output / 'weights.pt', weights_only=True))
        self.assertTrue(torch.isfinite(model(torch.ones(1, 96, 1))).all())
        with self.assertRaises(FileExistsError):
            train_to_directory(self.path, output, self.config)

    def test_requires_unmodified_validation_references(self):
        for validation in ((), tuple(w for w in self.dataset.validation if w.injection_present)):
            with self.assertRaises(ValueError):
                fit_hybrid_model(replace(self.dataset, validation=validation), self.config)
