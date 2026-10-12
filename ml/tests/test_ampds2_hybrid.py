from copy import deepcopy
import unittest

from aquamind_ml.ampds2_hybrid import generate


def fixture():
    return {'schema': 'aquamind-ampds2-unlabeled-v1', 'labels': 'unknown', 'units': 'US gallons/minute',
            **{split: [{'start_timestamp': f'2012-04-{day:02d}T00:00:00+00:00',
                        'flow_rates_gpm': [0.0, 1.0] * 48}]
               for split, day in (('train', 2), ('validation', 4), ('test', 6))}}


class HybridTests(unittest.TestCase):
    def test_injected_volume_bounds_labels_and_source_immutability(self):
        raw = fixture()
        before = deepcopy(raw)
        result = generate(raw, 'source')
        self.assertEqual(raw, before)
        self.assertEqual(len(result['train']), 1)
        self.assertEqual(len(result['validation']), 14)
        self.assertEqual(len(result['test']), 14)
        for split in ('train', 'validation', 'test'):
            base = raw[split][0]['flow_rates_gpm']
            for row in result[split]:
                start, end = row['start_interval'], row['end_interval_exclusive']
                self.assertTrue(0 <= start <= end <= 96)
                self.assertEqual(row['physical_leak_label'], 'unknown')
                self.assertEqual(row['source_sha256'], 'source')
                for i, value in enumerate(row['flow_rates_gpm']):
                    self.assertAlmostEqual(value, base[i] + (row['added_gpm'] if start <= i < end else 0))
                self.assertAlmostEqual((sum(row['flow_rates_gpm']) - sum(base)) * 15, row['added_gallons'])
                self.assertEqual(row['is_continuous_injection'], row['variant_kind'] == 'continuous_injection')
        self.assertEqual(result['train'][0]['flow_rates_gpm'], raw['train'][0]['flow_rates_gpm'])
        demand = result['validation'][-1]
        self.assertTrue(demand['injection_present'])
        self.assertFalse(demand['is_continuous_injection'])
        self.assertEqual(demand['added_gallons'], 120)
        continuous = result['validation'][1:-1]
        self.assertEqual({(r['added_gpm'], r['end_interval_exclusive'] - r['start_interval']) for r in continuous},
                         {(rate, length) for rate in (.01, .03, .1, .3) for length in (16, 48, 96)})

    def test_determinism_and_split_independence(self):
        raw = fixture()
        original = generate(raw, 'source')
        self.assertEqual(original, generate(raw, 'source'))
        raw['test'][0]['flow_rates_gpm'] = [50] * 96
        changed = generate(raw, 'source')
        self.assertEqual(original['train'], changed['train'])
        self.assertEqual(original['validation'], changed['validation'])
        self.assertTrue({r['base_day_id'] for r in original['validation']}.isdisjoint(
                        r['base_day_id'] for r in original['test']))

    def test_rejects_overlap_missing_gap_and_malformed_input(self):
        for date in ('2012-04-02T00:00:00+00:00', '2012-04-03T00:00:00+00:00'):
            raw = fixture()
            raw['validation'][0]['start_timestamp'] = date
            with self.assertRaises(ValueError):
                generate(raw, 'source')
        for value in (True, -1, float('nan'), '1'):
            raw = fixture()
            raw['train'][0]['flow_rates_gpm'][0] = value
            with self.assertRaises(ValueError):
                generate(raw, 'source')
