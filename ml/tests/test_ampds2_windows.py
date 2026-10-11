import unittest

from aquamind_ml.ampds2_windows import daily_windows, chronological_split, LITERS_PER_US_GALLON


class WindowTests(unittest.TestCase):
    def test_preceding_minute_alignment_volume_and_unknown_labels(self):
        start = 1333324800  # UTC midnight, April 2, 2012
        rows = [(start, 999.0)] + [(start + i * 60, LITERS_PER_US_GALLON) for i in range(1, 1441)]
        rows[1] = (start + 60, 16 * LITERS_PER_US_GALLON)
        windows, discarded = daily_windows(rows)
        self.assertEqual(discarded, 1)
        self.assertEqual(windows[0]['start_timestamp'], '2012-04-02T00:00:00+00:00')
        rates = windows[0]['flow_rates_gpm']
        self.assertEqual(len(rates), 96)
        self.assertAlmostEqual(rates[0], 2)
        self.assertAlmostEqual(sum(rates) * 15, 1455)
        self.assertNotIn('has_leak', windows[0])

    def test_partial_days_are_dropped_and_bad_minutes_rejected(self):
        start = 1333324800
        windows, discarded = daily_windows((start - 60 + i * 60, 1) for i in range(1443))
        self.assertEqual(len(windows), 1)
        self.assertEqual(discarded, 3)
        for rows in ([], [(start, 0)], [(start, 0), (start + 120, 0)],
                     [(start, 0), (start, 0)], [(start, float('nan'))], [(start, -1)], [(start, True)]):
            with self.assertRaises(ValueError):
                daily_windows(rows)

    def test_splits_are_ordered_nonoverlapping_and_purged(self):
        windows = [{'start_timestamp': str(i), 'flow_rates_gpm': [i] * 96} for i in range(20)]
        splits = chronological_split(windows)
        self.assertEqual([len(splits[k]) for k in ('train', 'validation', 'test')], [14, 2, 2])
        self.assertEqual(splits['purged_days'], ['14', '17'])
        self.assertEqual(splits['validation'][0]['start_timestamp'], '15')
        self.assertEqual(splits['test'][0]['start_timestamp'], '18')
        with self.assertRaises(ValueError):
            chronological_split(windows[:3])
