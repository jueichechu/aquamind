from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

import torch

from aquamind_ml.data import load_dataset
from aquamind_ml.model import LSTMAutoencoder
from aquamind_ml.train import TrainingConfig, fit_model, train_to_directory
from test_data import fixture


class TrainingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "data.json"
        self.path.write_text(json.dumps(fixture()))
        self.dataset = load_dataset(self.path)
        self.config = TrainingConfig(epochs=2, hidden_size=4, latent_size=2)

    def test_reproducible_and_independent_of_test_data(self):
        first, norm, report = fit_model(self.dataset, self.config)
        second, norm2, report2 = fit_model(replace(self.dataset, test=()), self.config)
        self.assertEqual(norm, norm2)
        self.assertEqual(report, report2)
        for name, value in first.state_dict().items():
            torch.testing.assert_close(value, second.state_dict()[name], rtol=0, atol=0)
        best = min(report["history"], key=lambda row: row["normal_validation_mse"])
        self.assertEqual(report["selected_epoch"], best["epoch"])

    def test_saved_artifacts_reload_and_refuse_overwrite(self):
        output = Path(self.directory.name) / "run"
        report = train_to_directory(self.path, output, self.config)
        self.assertEqual(json.loads((output / "training.json").read_text()), report)
        self.assertFalse(report["test_evaluated"])
        model = LSTMAutoencoder(4, 2)
        model.load_state_dict(torch.load(output / "weights.pt", weights_only=True))
        self.assertTrue(torch.isfinite(model(torch.ones(1, 96, 1))).all())
        with self.assertRaises(FileExistsError):
            train_to_directory(self.path, output, self.config)

    def test_invalid_config_and_missing_validation(self):
        for kwargs in ({"epochs": 0}, {"batch_size": -1}, {"seed": -1},
                       {"learning_rate": float("nan")}):
            with self.assertRaises(ValueError):
                TrainingConfig(**kwargs)
        with self.assertRaises(ValueError):
            fit_model(replace(self.dataset, validation=()), self.config)
