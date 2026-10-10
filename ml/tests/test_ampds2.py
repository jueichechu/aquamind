from pathlib import Path
import tempfile
import unittest

from aquamind_ml.ampds2 import inspect_water, verified_report


class AmpdsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'water.csv'

    def write(self, rows):
        self.path.write_text('unix_ts,counter,avg_rate,inst_rate\n' + rows)

    def test_inspection_preserves_units_and_does_not_invent_labels(self):
        self.write('1333263600,100,0,0\n1333263660,103.785,3.785,0\n')
        result = inspect_water(self.path)
        self.assertEqual(result['rows'], 2)
        self.assertEqual(result['max_average_rate_liters_per_minute'], 3.785)
        self.assertEqual(result['nonzero_average_rate_rows'], 1)
        self.assertEqual(result['counter_rate_discrepancies_over_0_002_liters'], 0)
        self.assertEqual(result['leak_labels'], 'not_provided')
        self.assertEqual(result['transformations'], [])
        with self.assertRaises(ValueError):
            verified_report(self.path)

    def test_rejects_missing_duplicate_or_invalid_readings(self):
        for rows in ('', '1333263600,100,0,0\n1333263720,101,1,0\n',
                     '1333263600,100,0,0\n1333263600,101,1,0\n',
                     '1333263600,100,nan,0\n', '1333263600,100,-1,0\n',
                     '1333263600,100,0\n', '1333263600,100,0,0,extra\n',
                     '1333263600,100,0,0\n1333263660,99,0,0\n'):
            self.write(rows)
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                inspect_water(self.path)
        self.path.write_text('wrong,columns\n')
        with self.assertRaises(ValueError):
            inspect_water(self.path)

    def test_reports_discrepancies_instead_of_silently_repairing(self):
        self.write('1333263600,100,0,0\n1333263660,105,1,0\n')
        self.assertEqual(inspect_water(self.path)['counter_rate_discrepancies_over_0_002_liters'], 1)
