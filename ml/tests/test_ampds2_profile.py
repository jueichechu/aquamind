from copy import deepcopy
import unittest

from aquamind_ml.ampds2_profile import profile_training


def fixture():
    return {'schema': 'aquamind-ampds2-unlabeled-v1', 'units': 'US gallons/minute', 'labels': 'unknown',
            'train': [{'start_timestamp': '2012-04-02T00:00:00+00:00', 'flow_rates_gpm': [0, 2] * 48},
                      {'start_timestamp': '2012-04-03T00:00:00+00:00', 'flow_rates_gpm': [1] * 96}]}


class ProfileTests(unittest.TestCase):
    def test_units_runs_and_observed_statistics(self):
        report = profile_training(fixture())
        self.assertEqual(report['daily_gallons']['mean'], 1440)
        self.assertEqual(report['interval_average_gpm']['mean'], 1)
        self.assertEqual(report['daily_zero_interval_fraction']['mean'], .25)
        self.assertEqual(report['longest_daily_positive_run_minutes']['min'], 15)
        self.assertEqual(report['longest_daily_positive_run_minutes']['max'], 1440)
        self.assertEqual(report['labels'], 'unknown')

    def test_heldout_data_is_never_accessed(self):
        class TrainingOnly(dict):
            def __getitem__(self, key):
                if key in ('validation', 'test'):
                    raise AssertionError('Held-out partition accessed')
                return super().__getitem__(key)
        data = TrainingOnly(fixture() | {'validation': object(), 'test': object()})
        self.assertEqual(profile_training(data), profile_training(fixture()))
        changed = deepcopy(fixture())
        changed['train'][0]['flow_rates_gpm'][0] = 1
        self.assertNotEqual(profile_training(changed)['training_sha256'], profile_training(data)['training_sha256'])

    def test_invalid_training_data_is_rejected(self):
        for patch in ({'units': 'liters/minute'}, {'labels': 'normal'}, {'train': []}):
            with self.assertRaises(ValueError):
                profile_training(fixture() | patch)
        for value in (True, -1, float('nan'), '1'):
            data = fixture()
            data['train'][0]['flow_rates_gpm'][0] = value
            with self.assertRaises(ValueError):
                profile_training(data)
        for stamp in ('2012-04-02T00:00:00+00:00', '2012-04-04T00:00:00+00:00', '2012-04-03T01:00:00+00:00'):
            data = fixture()
            data['train'][1]['start_timestamp'] = stamp
            with self.assertRaises(ValueError):
                profile_training(data)
