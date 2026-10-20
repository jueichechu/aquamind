import hashlib
import json
from math import fsum
from pathlib import Path
import tempfile
import unittest

from pydantic import ValidationError

from aquamind_ml.demo_meter import DEFAULT_DEMO_METER_PATH, DemoMeterStore, SCENARIOS


class DemoMeterTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'demo.json'
        self.raw = json.loads(DEFAULT_DEMO_METER_PATH.read_bytes())
        self.path.write_text(json.dumps(self.raw))

    def test_all_scenarios_units_baseline_provenance_and_copy_isolation(self):
        store = DemoMeterStore(self.path)
        self.path.write_text('changed after loading')
        expected_hash = hashlib.sha256(json.dumps(self.raw).encode()).hexdigest()
        for scenario in SCENARIOS:
            summary = store.summary(scenario)
            series = store.series(scenario)
            gallons = self.raw['scenarios'][scenario]
            self.assertEqual(summary.dataset_sha256, expected_hash)
            self.assertEqual(summary.source, 'synthetic')
            self.assertEqual(summary.seed, 42)
            self.assertEqual(summary.start_timestamp, '2026-06-21T00:00:00+00:00')
            self.assertEqual(summary.end_timestamp_exclusive, '2026-06-22T00:00:00+00:00')
            self.assertEqual(summary.baseline_start_timestamp, '2026-06-15T00:00:00+00:00')
            self.assertEqual(summary.baseline_end_timestamp_exclusive, summary.start_timestamp)
            self.assertEqual(summary.total_gallons, fsum(gallons[-96:]))
            self.assertEqual(summary.baseline_daily_gallons, fsum(gallons[:-96]) / 6)
            self.assertEqual(series.flow_rates_gpm, [g / 15 for g in gallons[-96:]])
            self.assertAlmostEqual(fsum(series.flow_rates_gpm) * 15, summary.total_gallons)
            self.assertEqual(summary.model_dump(), series.model_dump(exclude={'flow_rates_gpm'}))
            self.assertAlmostEqual(summary.difference_pct,
                (summary.total_gallons / summary.baseline_daily_gallons - 1) * 100)
            self.assertEqual(summary.peak_interval_flow_gpm, max(series.flow_rates_gpm))
            for label in ('is_leak', 'has_anomaly', 'excessGallons', 'fixtures'):
                self.assertNotIn(label, series.model_dump())
            series.flow_rates_gpm[0] = 999
            self.assertNotEqual(store.series(scenario).flow_rates_gpm[0], 999)

    def test_zero_baseline_is_unknown_percentage(self):
        self.raw['scenarios']['normal'] = [0] * 672
        self.path.write_text(json.dumps(self.raw))
        summary = DemoMeterStore(self.path).summary('normal')
        self.assertEqual(summary.total_gallons, 0)
        self.assertIsNone(summary.difference_pct)

    def test_invalid_snapshots_fail_closed(self):
        for patch in ({'seed': True}, {'seed': 1}, {'schema_version': True},
                      {'interval_minutes': 15.0}, {'source': 'real'}, {'unexpected': 1},
                      {'start_timestamp': '2026-06-15T01:00:00Z'},
                      {'start_timestamp': '2026-06-15T00:00:00-07:00'},
                      {'scenarios': {'normal': [0] * 672}},
                      {'scenarios': dict(self.raw['scenarios'], normal=[0] * 671)},
                      *({'scenarios': dict(self.raw['scenarios'], normal=[value] * 672)}
                        for value in (True, '1', -1, 15001, float('nan'), float('inf')))):
            with self.subTest(patch=list(patch)):
                self.path.write_text(json.dumps(self.raw | patch))
                with self.assertRaises(ValidationError):
                    DemoMeterStore(self.path)
        self.path.write_bytes(b' ' * 65537)
        with self.assertRaisesRegex(ValueError, 'too large'):
            DemoMeterStore(self.path)
