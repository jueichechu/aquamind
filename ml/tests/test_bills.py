from datetime import date, datetime
from decimal import Decimal, localcontext, ROUND_DOWN
import json
import unittest

from pydantic import ValidationError

from aquamind_ml.bills import ManualBill, normalize_bill


class BillTests(unittest.TestCase):
    def bill(self, **updates):
        return ManualBill.model_validate({
            'period_start': '2026-06-01', 'period_end_exclusive': '2026-07-01',
            'usage': '3000', 'usage_unit': 'us_gallons', **updates})

    def test_conversions_use_us_liquid_gallons_and_exact_ccf_ratio(self):
        for unit, usage, gallons, daily in (
                ('us_gallons', '3000', '3000.000000', '100.000000'),
                ('ccf', '1', '748.051948', '24.935065'),
                ('cubic_meters', '1', '264.172052', '8.805735'),
                ('liters', '1000', '264.172052', '8.805735'),
                ('liters', '3785.411784', '1000.000000', '33.333333')):
            with self.subTest(unit=unit):
                result = normalize_bill(self.bill(usage=usage, usage_unit=unit))
                self.assertEqual(result.total_us_gallons, gallons)
                self.assertEqual(result.us_gallons_per_day, daily)
                self.assertEqual(result.billing_days, 30)

    def test_calendar_days_cover_leap_years_and_adjacent_periods(self):
        feb = normalize_bill(self.bill(period_start='2024-02-01', period_end_exclusive='2024-03-01', usage=2900))
        self.assertEqual((feb.billing_days, feb.us_gallons_per_day), (29, '100.000000'))
        march = normalize_bill(self.bill(period_start=date(2024, 3, 1),
                                         period_end_exclusive=date(2024, 4, 1), usage=3100))
        self.assertEqual((march.billing_days, march.us_gallons_per_day), (31, '100.000000'))
        self.assertEqual(feb.bill.period_end_exclusive, march.bill.period_start)
        annual = normalize_bill(self.bill(period_start='2024-01-01', period_end_exclusive='2025-01-01'))
        self.assertEqual(annual.billing_days, 366)

    def test_rounds_daily_volume_only_after_division_with_isolated_decimal_context(self):
        bill = self.bill(period_end_exclusive='2026-06-03', usage='0.000002', usage_unit='liters')
        result = normalize_bill(bill)
        self.assertEqual(result.total_us_gallons, '0.000001')
        self.assertEqual(result.us_gallons_per_day, '0.000000')
        with localcontext() as context:
            context.prec = 4
            context.rounding = ROUND_DOWN
            self.assertEqual(normalize_bill(self.bill(usage=1, usage_unit='ccf')).total_us_gallons,
                             '748.051948')

    def test_zero_usage_and_unknown_charges_remain_distinct(self):
        result = normalize_bill(self.bill(usage=0))
        self.assertEqual(result.total_us_gallons, '0.000000')
        self.assertEqual(result.us_gallons_per_day, '0.000000')
        self.assertIsNone(result.water_and_sewer_subtotal)
        self.assertIsNone(result.bill.currency)
        partial = normalize_bill(self.bill(water_charge='12.34', currency='USD'))
        self.assertIsNone(partial.bill.sewer_charge)
        self.assertIsNone(partial.water_and_sewer_subtotal)
        free = normalize_bill(self.bill(water_charge=0, sewer_charge=0, currency='USD'))
        self.assertEqual(free.water_and_sewer_subtotal, '0.00')
        charged = normalize_bill(self.bill(water_charge='12.34', sewer_charge='5.67', currency='USD'))
        self.assertEqual(charged.water_and_sewer_subtotal, '18.01')

    def test_json_roundtrip_preserves_input_and_limited_evidence(self):
        original = {'period_start': '2026-06-01', 'period_end_exclusive': '2026-07-01',
                    'usage': '8.5', 'usage_unit': 'ccf', 'water_charge': '45.12', 'currency': 'USD'}
        bill = ManualBill.model_validate_json(json.dumps(original))
        serialized = json.loads(normalize_bill(bill).model_dump_json())
        self.assertEqual(serialized['source'], 'manual_entry')
        self.assertEqual(serialized['evidence_level'], 'bill_only')
        self.assertEqual(serialized['confidence'], 'limited')
        self.assertEqual(serialized['bill'], original | {'sewer_charge': None})
        self.assertIn('unverified', serialized['limitations'][0])
        self.assertTrue({'is_leak', 'score', 'rate', 'anomaly_start'}.isdisjoint(serialized))
        with self.assertRaises(ValidationError):
            bill.usage = Decimal(99)

    def test_invalid_dates_durations_and_units(self):
        for update in ({'period_start': '2026-02-30'}, {'period_start': '06/01/2026'},
                       {'period_start': '2026-06-01T00:00:00Z'}, {'period_start': 1780272000},
                       {'period_start': datetime(2026, 6, 1)}, {'period_start': True},
                       {'period_end_exclusive': '2026-06-01'}, {'period_end_exclusive': '2026-05-31'},
                       {'period_end_exclusive': '2027-06-03'},
                       *({'usage_unit': unit} for unit in ('gallons', 'imperial_gallons', 'hcf', '', 1, None))):
            with self.subTest(update=update), self.assertRaises(ValidationError):
                self.bill(**update)

    def test_invalid_numeric_inputs_and_normalized_volume_cap(self):
        for bad in (True, -1, '-0.01', 'NaN', 'Infinity', float('inf'), float('nan'),
                    '', '1,000', '1 gal', '1e3', '1' * 10000, {}, []):
            for field in ('usage', 'water_charge', 'sewer_charge'):
                with self.subTest(field=field, value_type=type(bad)), self.assertRaises(ValidationError):
                    self.bill(**{field: bad, 'currency': 'USD'})
        for update in ({'usage': None}, {'usage': '1.0000001'}, {'usage': 1_000_001},
                       {'usage': 2000, 'usage_unit': 'ccf'},
                       {'usage': 4000, 'usage_unit': 'cubic_meters'},
                       {'usage': 4_000_000, 'usage_unit': 'liters'},
                       {'water_charge': '1.001', 'currency': 'USD'},
                       {'sewer_charge': 1_000_001, 'currency': 'USD'},
                       {'water_charge': 0}, {'sewer_charge': 0}, {'currency': 'CAD'},
                       {'is_leak': True}, {'account_number': 'not-collected'}, {'rate': 5}):
            with self.subTest(fields=list(update)), self.assertRaises(ValidationError):
                self.bill(**update)
        self.assertEqual(normalize_bill(self.bill(usage=1_000_000)).total_us_gallons, '1000000.000000')
