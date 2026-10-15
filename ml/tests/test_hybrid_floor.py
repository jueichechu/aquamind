from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

import torch

from aquamind_ml.hybrid_data import load_hybrid_dataset, HybridFlowNormalizer
from aquamind_ml.hybrid_floor import compare, persistent_floor
from test_hybrid_data import fixture
from test_hybrid_sustained import ZeroModel


class FloorTests(unittest.TestCase):
    def test_physical_units_duration_and_robustness_to_short_bursts(self):
        values = torch.zeros(4, 96)
        values[0, 20:36] = .01
        values[1, 20:28] = 5
        values[2, :8] = .1
        values[2, -8:] = .1
        values[3] = -.1
        score = persistent_floor(values)
        self.assertAlmostEqual(score[0], .01)
        self.assertEqual(score[1:], [0, 0, 0])
        with self.assertRaises(ValueError):
            persistent_floor(torch.full((1, 96), float('nan')))

    def test_ablation_keeps_model_free_and_model_based_methods_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'data.json'
            path.write_text(json.dumps(fixture()))
            data = load_hybrid_dataset(path)
        normalizer = HybridFlowNormalizer.fit(data)
        class TrainAndValidation:
            train = data.train
            validation = data.validation
            @property
            def test(self):
                raise AssertionError('Test partition accessed')
        report = compare(TrainAndValidation(), ZeroModel(), normalizer)
        self.assertFalse(report['test_evaluated'])
        self.assertEqual(set(report['methods']), {'slot_standardized_lstm_residual',
                         'centered_lstm_residual_gpm', 'measured_flow_gpm_model_free'})
        doubled = HybridFlowNormalizer(normalizer.mean_gpm, normalizer.scale_gpm * 2,
                    normalizer.training_value_count, normalizer.dataset_sha256, normalizer.training_sha256)
        other = compare(replace(data, test=()), ZeroModel(), doubled)
        # Physical-flow baseline is independent of all model/normalization parameters.
        self.assertEqual(report['methods']['measured_flow_gpm_model_free'], other['methods']['measured_flow_gpm_model_free'])
