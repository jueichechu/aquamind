from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

import torch

from aquamind_ml.hybrid_data import load_hybrid_dataset, HybridFlowNormalizer
from aquamind_ml.hybrid_sustained import SustainedCalibration, compare, select_constrained_threshold
from test_hybrid_data import fixture


class ZeroModel(torch.nn.Module):
    def forward(self, values):
        return torch.zeros_like(values)


class SustainedTests(unittest.TestCase):
    def test_persistent_flow_survives_but_short_demand_does_not(self):
        calibration = SustainedCalibration((0,) * 96, (1,) * 96)
        values = torch.zeros(4, 96)
        values[0, 40:56] = .1
        values[1, 40:48] = 10
        values[2, 40:52] = 10
        values[3, :8] = 1
        values[3, -8:] = 1  # No midnight wrapping.
        scores = calibration.score(values)
        self.assertAlmostEqual(scores[0], .1)
        self.assertEqual(scores[1:], [0, 0, 0])
        self.assertEqual(SustainedCalibration(**json.loads(json.dumps({
            'center': [0] * 96, 'scale': [1] * 96}))).score(values), scores)

    def test_threshold_enforces_each_group_cap_and_can_abstain(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'data.json'
            path.write_text(json.dumps(fixture()))
            data = load_hybrid_dataset(path)
        windows = data.validation
        scores = [0] + [2] * 12 + [1]
        self.assertEqual(select_constrained_threshold(windows, scores), 2)
        self.assertGreater(select_constrained_threshold(windows, [1] * 14), 1)
        with self.assertRaises(ValueError):
            select_constrained_threshold(windows, [float('nan')] * 14)
        with self.assertRaises(ValueError):
            select_constrained_threshold(windows[1:-1], [1] * 12)

    def test_training_fit_and_comparison_do_not_access_test_or_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'data.json'
            path.write_text(json.dumps(fixture()))
            data = load_hybrid_dataset(path)
        normalizer = HybridFlowNormalizer.fit(data)
        model = ZeroModel()
        class TrainingAndValidationOnly:
            train = data.train
            validation = data.validation
            @property
            def test(self):
                raise AssertionError('Test accessed')
        report = compare(TrainingAndValidationOnly(), model, normalizer)
        self.assertFalse(report['test_evaluated'])
        self.assertEqual(report, compare(replace(data, test=()), model, normalizer))
        calibration = SustainedCalibration.fit(model, normalizer, data.train)
        self.assertTrue(all(v >= .01 for v in calibration.scale))
        with self.assertRaises(ValueError):
            SustainedCalibration.fit(model, normalizer, (data.validation[1],))
        for errors in (torch.zeros(1, 95), torch.full((1, 96), float('inf')), torch.zeros(0, 96)):
            with self.assertRaises(ValueError):
                calibration.score(errors)
