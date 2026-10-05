from dataclasses import asdict, replace
import json
from pathlib import Path
import tempfile
import unittest

import torch

from aquamind_ml.calibration import ResidualCalibration, residuals
from aquamind_ml.data import FlowNormalizer, load_dataset
from aquamind_ml.model import LSTMAutoencoder
from test_data import fixture


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        path = Path(self.directory.name) / "dataset.json"
        path.write_text(json.dumps(fixture()))
        self.dataset = load_dataset(path)
        self.normalizer = FlowNormalizer.fit(self.dataset)
        torch.manual_seed(42)
        self.model = LSTMAutoencoder(4, 2)
        previous = torch.get_num_threads()
        torch.set_num_threads(1)
        self.addCleanup(torch.set_num_threads, previous)

    def test_fit_uses_only_normal_training_and_handles_zero_variance(self):
        first = ResidualCalibration.fit(self.model, self.normalizer, self.dataset)
        second = ResidualCalibration.fit(self.model, self.normalizer,
                                        replace(self.dataset, validation=(), test=()))
        self.assertEqual(first, second)
        self.assertEqual(first.scale, (0.01,) * 96)
        self.assertTrue(self.model.training)
        with self.assertRaises(ValueError):
            ResidualCalibration.fit(self.model, self.normalizer, replace(
                self.dataset, train=(replace(self.dataset.train[0], has_leak=True),)))

    def test_score_formula_and_saved_parameter_roundtrip(self):
        calibrated = ResidualCalibration((1.0,) * 96, (2.0,) * 96)
        errors = torch.tensor([[5.0] * 96, [-1.0] * 96])
        self.assertEqual(calibrated.score(errors), [4.0, 0.0])
        restored = ResidualCalibration(**json.loads(json.dumps(asdict(calibrated))))
        self.assertEqual(restored.score(errors), calibrated.score(errors))

    def test_rejects_misaligned_windows_and_invalid_parameters(self):
        for timestamp in ("2026-06-15T00:15:00Z", "2026-06-15T00:00:00+01:00"):
            with self.assertRaises(ValueError):
                residuals(self.model, self.normalizer,
                          (replace(self.dataset.train[0], start_timestamp=timestamp),))
        for scale in (0.0, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                ResidualCalibration((0.0,) * 96, (scale,) * 96)
        calibrated = ResidualCalibration((0.0,) * 96, (1.0,) * 96)
        for errors in (torch.ones(1, 95), torch.full((1, 96), float("nan"))):
            with self.assertRaises(ValueError):
                calibrated.score(errors)
