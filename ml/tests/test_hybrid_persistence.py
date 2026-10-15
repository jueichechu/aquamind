from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

import torch

from aquamind_ml.hybrid_data import HybridFlowNormalizer, load_hybrid_dataset
from aquamind_ml.hybrid_persistence import compare, strict_persistence
from test_hybrid_data import fixture
from test_hybrid_sustained import ZeroModel


class PersistenceTests(unittest.TestCase):
    def test_requires_every_interval_of_a_within_day_stretch(self):
        values = torch.zeros(5, 96)
        values[0, 30:46] = .01
        values[1, 30:45] = 10
        values[2, 30:46] = .1
        values[2, 35] = 0
        values[3, :8] = 1
        values[3, -8:] = 1
        values[4] = -.1
        scores = strict_persistence(values)
        self.assertAlmostEqual(scores[0], .01)
        self.assertEqual(scores[1:], [0, 0, 0, 0])
        for bad in (torch.zeros(1, 95), torch.zeros(0, 96), torch.full((1, 96), float('nan'))):
            with self.assertRaises(ValueError):
                strict_persistence(bad)

    def test_fixed_methods_train_only_calibration_and_heldout_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'data.json'
            path.write_text(json.dumps(fixture()))
            data = load_hybrid_dataset(path)
        normalizer = HybridFlowNormalizer.fit(data)
        class NoTest:
            train = data.train
            validation = data.validation
            @property
            def test(self):
                raise AssertionError('Held-out partition accessed')
        report = compare(NoTest(), ZeroModel(), normalizer)
        self.assertEqual(report, compare(replace(data, test=()), ZeroModel(), normalizer))
        self.assertFalse(report['test_evaluated'])
        self.assertEqual(set(report['methods']), {'lower_quartile_lstm_reference',
                         'strict_lstm_residual', 'strict_measured_flow_model_free'})
        for method in report['methods'].values():
            for kind in ('unmodified', 'demand_confounder'):
                self.assertLessEqual(method['by_variant_kind'][kind]['alarm_rate'], .05)
