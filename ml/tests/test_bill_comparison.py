from decimal import Decimal, ROUND_DOWN, localcontext
import json
import unittest

from pydantic import ValidationError

from aquamind_ml.bills import BillComparisonRequest, compare_bills


def bill(start, end, usage, unit='us_gallons', **fields):
    return {'period_start': start, 'period_end_exclusive': end,
            'usage': usage, 'usage_unit': unit, **fields}


class BillComparisonTests(unittest.TestCase):
    def compare(self, bills):
        return compare_bills(BillComparisonRequest.model_validate({'bills': bills}))

    def test_weighted_baseline_excludes_latest_and_gaps_and_sorts_without_mutation(self):
        january = bill('2024-01-01', '2024-02-01', '3100')  # 31 days at 100 gpd.
        february = bill('2024-02-01', '2024-03-01', '5800')  # 29 days at 200 gpd.
        april = bill('2024-04-01', '2024-05-01', '6000')  # 30 days at 200 gpd.
        entered = [april, january, february]
        original = json.dumps(entered)
        result = self.compare(entered)
        self.assertEqual(json.dumps(entered), original)
        self.assertEqual([item.bill.period_start.isoformat() for item in result.bills],
                         ['2024-01-01', '2024-02-01', '2024-04-01'])
        self.assertEqual((result.baseline_bill_count, result.baseline_billing_days), (2, 60))
        self.assertEqual((result.covered_days, result.gap_days), (90, 31))
        self.assertEqual(result.baseline_us_gallons_per_day, '148.333333')
        self.assertEqual(result.bills[-1].us_gallons_per_day, '200.000000')
        self.assertEqual(result.latest_us_gallons_per_day_change, '51.666667')
        self.assertEqual(result.latest_percent_change, '34.83')

    def test_equal_daily_usage_across_unequal_periods_is_not_a_consumption_increase(self):
        result = self.compare([bill('2026-02-01', '2026-03-01', '2800'),
                               bill('2026-03-01', '2026-04-01', '3100')])
        self.assertEqual(result.baseline_us_gallons_per_day, '100.000000')
        self.assertEqual(result.latest_us_gallons_per_day_change, '0.000000')
        self.assertEqual(result.latest_percent_change, '0.00')
        self.assertEqual(result.gap_days, 0)

    def test_mixed_units_preserve_entries_and_use_exact_conversions(self):
        result = self.compare([bill('2026-01-01', '2026-01-02', '1', 'ccf'),
                               bill('2026-01-02', '2026-01-03', '1000', 'liters'),
                               bill('2026-01-03', '2026-01-04', '1', 'cubic_meters')])
        self.assertEqual([item.bill.usage_unit for item in result.bills], ['ccf', 'liters', 'cubic_meters'])
        self.assertEqual(result.baseline_us_gallons_per_day, '506.112000')
        self.assertEqual(result.latest_us_gallons_per_day_change, '-241.939948')
        self.assertEqual(result.latest_percent_change, '-47.80')

    def test_comparison_precedes_display_rounding_and_does_not_use_display_zero_as_baseline_zero(self):
        result = self.compare([bill('2026-01-01', '2026-01-02', '0.000001', 'liters'),
                               bill('2026-01-02', '2026-01-03', '0.000002', 'liters')])
        self.assertEqual(result.baseline_us_gallons_per_day, '0.000000')
        self.assertEqual(result.latest_us_gallons_per_day_change, '0.000000')
        self.assertEqual(result.latest_percent_change, '100.00')
        # A tiny negative difference must not render as negative zero.
        rounded = self.compare([bill('2026-01-01', '2026-01-02', '1', 'ccf'),
                                bill('2026-01-02', '2026-01-03', '748.051948')])
        self.assertEqual(rounded.latest_us_gallons_per_day_change, '0.000000')
        self.assertEqual(rounded.latest_percent_change, '0.00')

    def test_true_zero_baseline_has_undefined_percentage_but_valid_absolute_change(self):
        for usage in ('0', '25'):
            result = self.compare([bill('2026-01-01', '2026-01-02', '0'),
                                   bill('2026-01-02', '2026-01-03', usage)])
            self.assertIsNone(result.latest_percent_change)
            self.assertEqual(result.latest_us_gallons_per_day_change, f'{usage}.000000')
        falling = self.compare([bill('2026-01-01', '2026-01-02', '25'),
                                bill('2026-01-02', '2026-01-03', '0')])
        self.assertEqual(falling.latest_us_gallons_per_day_change, '-25.000000')
        self.assertEqual(falling.latest_percent_change, '-100.00')

    def test_decimal_context_does_not_change_the_result(self):
        entries = [bill('2026-01-01', '2026-01-04', '1', 'ccf'),
                   bill('2026-01-04', '2026-01-11', '1', 'cubic_meters')]
        expected = self.compare(entries)
        with localcontext() as context:
            context.prec = 4
            context.rounding = ROUND_DOWN
            self.assertEqual(self.compare(entries), expected)
            self.assertEqual((context.prec, context.rounding), (4, ROUND_DOWN))

    def test_missing_and_zero_charges_preserve_provenance_without_inferred_costs(self):
        first = bill('2026-01-01', '2026-02-01', '1000', water_charge='12.34', currency='USD')
        second = bill('2026-02-01', '2026-03-01', '0', water_charge='0', sewer_charge='0', currency='USD')
        result = self.compare([first, second])
        self.assertIsNone(result.bills[0].bill.sewer_charge)
        self.assertIsNone(result.bills[0].water_and_sewer_subtotal)
        self.assertEqual(result.bills[1].water_and_sewer_subtotal, '0.00')
        serialized = json.loads(result.model_dump_json())
        self.assertEqual((serialized['source'], serialized['evidence_level'], serialized['confidence']),
                         ('manual_entry', 'historical_bills', 'limited'))
        self.assertTrue({'is_leak', 'score', 'rate', 'savings', 'cost_change'}.isdisjoint(serialized))
        self.assertIn('same household', ' '.join(serialized['limitations']))
        with self.assertRaises(ValidationError):
            result.baseline_bill_count = 99
        with self.assertRaises(ValidationError):
            result.bills[0].bill.usage = Decimal(99)

    def test_overlap_duplicate_and_contained_periods_are_rejected(self):
        first = bill('2026-01-01', '2026-02-01', '1000')
        for second in (first, first | {'usage': '1100'},
                       bill('2026-01-31', '2026-02-28', '1000'),
                       bill('2026-01-10', '2026-01-20', '100')):
            for entries in ([first, second], [second, first]):
                with self.subTest(entries=entries), self.assertRaises(ValidationError):
                    self.compare(entries)

    def test_count_and_schema_bounds_with_json_roundtrip(self):
        entries = [bill(f'2026-01-{day:02}', f'2026-01-{day + 1:02}', '1') for day in range(1, 14)]
        for count in (0, 1, 13):
            with self.subTest(count=count), self.assertRaises(ValidationError):
                self.compare(entries[:count])
        request = BillComparisonRequest.model_validate_json(json.dumps({'bills': entries[:12]}))
        self.assertEqual(compare_bills(request).covered_days, 12)
        self.assertIsInstance(request.bills, tuple)
        self.assertEqual(BillComparisonRequest.model_validate_json(request.model_dump_json()), request)
        for fields in ({'bills': 'not an array'}, {'bills': {'first': entries[0]}},
                       {'bills': entries[:2], 'baseline_us_gallons_per_day': '0'},
                       {'bills': [entries[0], entries[1] | {'account_number': 'not-collected'}]},
                       {'bills': [entries[0], entries[1] | {'usage': True}]},
                       {'bills': [entries[0], entries[1] | {'usage': '1000001'}]}):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                BillComparisonRequest.model_validate(fields)
