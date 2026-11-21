from copy import deepcopy
from decimal import ROUND_DOWN, localcontext
import unittest

from aquamind_ml.evidence_rates import discusses_rates, render_imported_rates


def reported(values=None, *, total='15.000000', minutes=15, count=2):
    data = {'inference_status': 'not_enabled_for_imported_data', 'total_us_gallons': total,
            'context': {'interval_minutes': minutes, 'reading_count': count, 'reading_type': 'unknown', 'volume_unit': 'us_gallons'}}
    if values is not None:
        data['interval_volumes_us_gallons'] = values
    return data


def coverage(kind='partial_period', bill='15.000000'):
    return {'assessment': {'coverage': kind}, 'bill': {'total_us_gallons': bill}}


class EvidenceRateTests(unittest.TestCase):
    def test_gpm_and_gph_are_computed_with_distinct_units(self):
        text = render_imported_rates(reported(['6.000000', '9.000000']), coverage())
        self.assertIn('0.5 GPM (30 US gallons/hour)', text)
        self.assertIn('6 US gallons / 15 minutes = 0.4 GPM', text)
        self.assertIn('9 US gallons / 15 minutes = 0.6 GPM', text)
        self.assertNotIn('24 GPM', text)
        self.assertNotIn('36 GPM', text)
        self.assertIn('Coverage is partial', text)

    def test_summary_does_not_invent_individual_readings_or_rates(self):
        text = render_imported_rates(reported(total='27.000000'), coverage())
        self.assertIn('0.9 GPM (54 US gallons/hour)', text)
        self.assertIn('Individual interval rates are not supplied by the summary alone.', text)
        self.assertNotIn('Interval 1:', text)

    def test_zero_hourly_volumes_and_complete_period_comparison_remain_unverified(self):
        text = render_imported_rates(reported(['0.000000'] * 2, total='0.000000', minutes=60), coverage())
        self.assertIn('0 GPM (0 US gallons/hour)', text)
        self.assertIn('do not independently prove the absence', text)
        whole = render_imported_rates(reported(['3.000000'] * 24, total='72.000000', minutes=60, count=24),
                                      coverage('same_period', '80.000000'))
        self.assertIn('meter-minus-bill difference is -8 US gallons', whole)
        self.assertIn('compares supplied numbers only', whole)
        self.assertIn('first 8 of 24', whole)
        self.assertNotIn('Interval 9:', whole)

    def test_rounding_is_explicit_and_uses_reported_converted_volumes(self):
        with localcontext() as context:
            context.prec = 5
            context.rounding = ROUND_DOWN
            data = reported(['2.641721', '5.283441'], total='7.925162', minutes=30)
            data['context']['volume_unit'] = 'liters'
            text = render_imported_rates(data, coverage())
        self.assertIn('0.132086 GPM', text)
        self.assertIn('Original CSV unit: liters.', text)
        self.assertIn('displayed, rounded reported volumes', text)

    def test_malformed_or_nonfinite_data_cannot_be_rendered(self):
        good = reported(['6.000000', '9.000000'])
        for key, value in (('total_us_gallons', 'NaN'), ('total_us_gallons', '-1'),
                           ('total_us_gallons', '1000001'), ('interval_volumes_us_gallons', ['6.000000']),
                           ('inference_status', 'verified_sensor')):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                render_imported_rates(good | {key: value}, coverage())
        for key, value in (('interval_minutes', 0), ('reading_count', True), ('reading_count', 673)):
            bad = deepcopy(good); bad['context'][key] = value
            with self.assertRaises(ValueError):
                render_imported_rates(bad, coverage())

    def test_rate_discussion_selection_does_not_capture_bill_daily_average(self):
        for text in ('GPM', 'gph', 'US gallons/hour', 'gal/min', 'flow rate', 'flow_rates_gpm'):
            self.assertTrue(discusses_rates(text), text)
        self.assertFalse(discusses_rates('Is my bill daily average unusually high?'))
        self.assertFalse(discusses_rates(None))
