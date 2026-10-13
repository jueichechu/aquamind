from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
import tempfile
import unittest

from aquamind_ml.ampds2_hybrid import generate
from aquamind_ml.hybrid_data import HybridFlowNormalizer, load_hybrid_dataset


def fixture(test_flow=1):
    base = {'schema': 'aquamind-ampds2-unlabeled-v1', 'labels': 'unknown', 'units': 'US gallons/minute',
            'purged_days': ['2012-04-03T00:00:00+00:00', '2012-04-05T00:00:00+00:00']}
    for split, day in (('train', 2), ('validation', 4), ('test', 6)):
        base[split] = [{'start_timestamp': f'2012-04-{day:02d}T00:00:00+00:00',
                        'flow_rates_gpm': [test_flow] * 96 if split != 'train' else [0, 2] * 48}]
    return generate(base, 'a' * 64)


class HybridDataTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'hybrid.json'

    def load(self, raw):
        self.path.write_text(json.dumps(raw))
        return load_hybrid_dataset(self.path)

    def test_immutable_windows_and_distinct_targets(self):
        dataset = self.load(fixture())
        self.assertEqual([len(getattr(dataset, k)) for k in ('train', 'validation', 'test')], [1, 14, 14])
        self.assertIsInstance(dataset.train[0].flow_rates_gpm, tuple)
        demand = dataset.validation[-1]
        self.assertTrue(demand.injection_present)
        self.assertFalse(demand.is_continuous_injection)
        self.assertEqual(demand.physical_leak_label, 'unknown')
        self.assertFalse(hasattr(demand, 'has_leak'))
        self.assertEqual(dataset.base_export_sha256, 'a' * 64)

    def test_training_only_fit_frozen_application_and_roundtrip(self):
        original = self.load(fixture())
        normalizer = HybridFlowNormalizer.fit(original)
        changed = self.load(fixture(1000))
        other = HybridFlowNormalizer.fit(changed)
        self.assertEqual((normalizer.mean_gpm, normalizer.scale_gpm, normalizer.training_value_count), (1, 1, 96))
        self.assertEqual(normalizer.training_sha256, other.training_sha256)
        self.assertEqual((other.mean_gpm, other.scale_gpm), (1, 1))
        self.assertEqual(normalizer.transform(changed.test)[0], (999,) * 96)
        self.assertEqual(normalizer.transform(original.train)[0], (-1, 1) * 48)
        self.assertEqual(HybridFlowNormalizer(**json.loads(json.dumps(asdict(normalizer)))), normalizer)
        constant = replace(original, train=(replace(original.train[0], flow_rates_gpm=(0,) * 96),))
        self.assertEqual(HybridFlowNormalizer.fit(constant).scale_gpm, 1)
        with self.assertRaises(ValueError):
            HybridFlowNormalizer.fit(replace(original, train=(original.validation[1],)))

    def test_rejects_tampered_protocol_labels_features_and_split_manifests(self):
        changes = [
            lambda r: r.update(protocol='unknown'),
            lambda r: r.update(interval_minutes=True),
            lambda r: r.update(base_export_sha256='bad'),
            lambda r: r.update(purged_days=[]),
            lambda r: r['validation'].pop(),
            lambda r: r['validation'].append(deepcopy(r['validation'][0])),
            lambda r: r['validation'][1].update(physical_leak_label='leak'),
            lambda r: r['validation'][1].update(is_continuous_injection=1),
            lambda r: r['validation'][1].update(start_interval=True),
            lambda r: r['validation'][1].update(added_gallons=0),
            lambda r: r['validation'][1]['flow_rates_gpm'].__setitem__(0, 99),
            lambda r: r['train'][0]['flow_rates_gpm'].__setitem__(0, float('nan')),
            lambda r: r.update(test=deepcopy(r['validation'])),
        ]
        for index, change in enumerate(changes):
            raw = fixture()
            change(raw)
            with self.subTest(case=index), self.assertRaises(ValueError):
                self.load(raw)
