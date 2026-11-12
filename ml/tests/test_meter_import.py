from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import unittest

from pydantic import ValidationError

from aquamind_ml.bills import ManualBill, normalize_bill
from aquamind_ml.meter_import import (MAX_READINGS, METER_CSV_LIMIT,
    MeterCsvError, MeterImportRequest, parse_meter_csv)


def meter_body(*, count=96, start='2026-06-01T00:00:00+00:00', minutes=15, volume='1', **changes):
    first = datetime.fromisoformat(start)
    csv = 'interval_start,volume\n' + ''.join(
        f'{(first + timedelta(minutes=index * minutes)).isoformat()},{volume}\n'
        for index in range(count))
    return dict(csv_text=csv, volume_unit='us_gallons', interval_minutes=minutes,
                timezone='UTC', reading_type='actual', consent_to_process=True) | changes


def parse(body):
    return parse_meter_csv(MeterImportRequest.model_validate(body))


class MeterImportTests(unittest.TestCase):
    def test_all_explicit_units_match_existing_bill_normalization(self):
        for unit in ('us_gallons', 'ccf', 'cubic_meters', 'liters'):
            body = meter_body(count=1, volume_unit=unit)
            dataset = parse(body)
            expected = normalize_bill(ManualBill(period_start='2026-06-01',
                period_end_exclusive='2026-06-02', usage='1', usage_unit=unit))
            self.assertEqual(dataset.total_us_gallons, expected.total_us_gallons)
            self.assertEqual(dataset.dataset_sha256, sha256(body['csv_text'].encode()).hexdigest())
            context = dataset.context(evidence_id='meter_example', household_id='house_example')
            self.assertEqual(context.origin, 'user_provided')
            self.assertEqual(context.volume_unit, unit)
            self.assertEqual(context.reading_count, 1)

    def test_gaps_duplicates_out_of_order_and_overlaps_are_rejected(self):
        body = meter_body(count=3)
        lines = body['csv_text'].splitlines()
        for rows in ([lines[1], lines[3]], [lines[1], lines[1]],
                     [lines[2], lines[1]], [lines[1], lines[2].replace('00:15', '00:10')]):
            with self.subTest(rows=rows), self.assertRaisesRegex(MeterCsvError, 'ordered and contiguous'):
                parse(body | {'csv_text': lines[0] + '\n' + '\n'.join(rows)})

    def test_dst_spring_and_fall_are_contiguous_in_utc(self):
        for start, count in (('2026-03-08T05:00:00+00:00', 92), ('2026-11-01T04:00:00+00:00', 100)):
            from zoneinfo import ZoneInfo
            zone = ZoneInfo('America/New_York')
            first = datetime.fromisoformat(start)
            csv = 'interval_start,volume\n' + ''.join(
                f'{(first + timedelta(minutes=15 * i)).astimezone(zone).isoformat()},1\n' for i in range(count))
            dataset = parse(meter_body(csv_text=csv, timezone='America/New_York'))
            self.assertEqual(len(dataset.gallons), count)
            self.assertEqual(dataset.end_exclusive - dataset.start, timedelta(minutes=15 * count))
        # A nonexistent local hour or wrong offset must never be normalized silently.
        for instant in ('2026-03-08T02:15:00-05:00', '2026-07-01T00:00:00-05:00'):
            with self.assertRaisesRegex(MeterCsvError, 'timezone'):
                parse(meter_body(count=1, start=instant, timezone='America/New_York'))

    def test_one_through_672_readings_and_multiple_cadences(self):
        for count, minutes in ((1, 1), (MAX_READINGS, 15), (24, 60), (100, 5)):
            dataset = parse(meter_body(count=count, minutes=minutes))
            self.assertEqual(len(dataset.gallons), count)
            self.assertEqual(dataset.gallons, (Decimal(1),) * count)
            self.assertEqual(dataset.start.tzinfo, UTC)
            self.assertEqual(dataset.end_exclusive - dataset.start, timedelta(minutes=count * minutes))
        for count in (0, MAX_READINGS + 1):
            with self.assertRaises(MeterCsvError):
                parse(meter_body(count=count))

    def test_rejects_unsupported_semantics_and_forged_metadata(self):
        for changes in ({'volume_unit': 'gpm'}, {'volume_unit': 'kgal'}, {'interval_minutes': True},
                        {'interval_minutes': 0}, {'interval_minutes': 61}, {'timezone': 'Unknown/Zone'},
                        {'reading_type': 'verified'}, {'dataset_sha256': 'a' * 64},
                        {'household_id': 'house_forged'}, {'origin': 'synthetic'},
                        {'file_path': '/private/input.csv'}, {'consent_to_process': 'true'}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                parse(meter_body(**changes))
        with self.assertRaisesRegex(MeterCsvError, 'Consent'):
            parse(meter_body(consent_to_process=False))

    def test_rejects_bad_csv_headers_rows_and_numbers_without_guessing(self):
        instant = '2026-06-01T00:00:00Z'
        bad = ['', 'timestamp,volume\n' + instant + ',1',
               'interval_start,volume,volume\n' + instant + ',1,2',
               'interval_start,volume\n', 'interval_start,volume\n\n',
               'interval_start,volume\n' + instant + ',1,extra',
               'interval_start,volume\n"unterminated',
               'interval_start,volume\n' + instant + ',"1\n2"']
        bad += ['interval_start,volume\n' + instant + ',' + amount for amount in
                ('-1', 'NaN', 'Infinity', '1e2', '=1+2', '1 gallons', '1.0000001', '', '15001')]
        bad += ['interval_start,volume\n' + time + ',1' for time in
                ('2026-06-01T00:00:00', '2026-06-01', '2026-06-01T00:00:01Z',
                 '2026-99-99T00:00Z', '9999-12-31T23:59:00Z')]
        for csv in bad:
            with self.subTest(csv=csv), self.assertRaises(ValueError):
                parse(meter_body(csv_text=csv))

    def test_zero_crlf_quoted_cells_and_total_limits(self):
        body = meter_body(count=1, volume='0')
        csv = body['csv_text'].replace(',0', ',"0"').replace('\n', '\r\n')
        self.assertEqual(parse(body | {'csv_text': csv}).total_us_gallons, '0.000000')
        with self.assertRaisesRegex(MeterCsvError, '1,000,000'):
            parse(meter_body(count=100, volume='15000'))
        self.assertEqual(parse(meter_body(count=1, volume='15000')).total_us_gallons, '15000.000000')

    def test_input_bytes_and_privacy(self):
        with self.assertRaisesRegex(MeterCsvError, 'byte limit'):
            parse(meter_body(csv_text='é' * METER_CSV_LIMIT))
        with self.assertRaises(ValueError):
            parse(meter_body(csv_text='\ud800'))
        body = meter_body(csv_text='PRIVATE_SOURCE_CONTENT')
        with self.assertRaises(ValidationError) as caught:
            MeterImportRequest.model_validate(body | {'interval_minutes': 'PRIVATE_SOURCE_CONTENT'})
        self.assertNotIn('PRIVATE_SOURCE_CONTENT', str(caught.exception))
        self.assertNotIn('PRIVATE_SOURCE_CONTENT', repr(MeterImportRequest.model_validate(body)))


if __name__ == '__main__':
    unittest.main()
