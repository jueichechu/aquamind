from copy import deepcopy
import unittest

from pydantic import ValidationError

from aquamind_ml.demo_meter import DemoMeterStore
from aquamind_ml.evidence import EvidenceContext, assess_evidence, demo_meter_context


def example_context():
    return {'schema_version': 1, 'bill': {
        'evidence_id': 'bill_demo01', 'household_id': 'house_demo1',
        'origin': 'synthetic', 'input_method': 'document_import', 'reviewed': True,
        'timezone': 'UTC', 'bill': {'period_start': '2026-06-21',
            'period_end_exclusive': '2026-06-22', 'usage': '100', 'usage_unit': 'us_gallons'}},
        'meter': {'evidence_id': 'meter_demo1', 'household_id': 'house_demo1',
            'origin': 'synthetic', 'dataset_sha256': 'a' * 64,
            'start': '2026-06-21T00:00:00+00:00', 'end_exclusive': '2026-06-22T00:00:00+00:00',
            'interval_minutes': 15, 'reading_count': 96, 'volume_unit': 'us_gallons',
            'reading_type': 'actual'}}


class EvidenceTests(unittest.TestCase):
    def assess(self, data):
        return assess_evidence(EvidenceContext.model_validate(data))

    def test_existing_demo_adapter_and_bill_contract_produce_related_unverified_context(self):
        data = example_context()
        summary = DemoMeterStore().summary('overnight-leak')
        meter = demo_meter_context(summary, evidence_id='meter_demo1', household_id='house_demo1')
        data['meter'] = meter
        context = EvidenceContext.model_validate(data)
        result = assess_evidence(context)
        self.assertEqual((result.status, result.coverage), ('ready', 'same_period'))
        self.assertTrue(result.can_compare_period_totals)
        self.assertTrue(any('unverified' in note for note in result.limitations))
        self.assertTrue(any('Synthetic' in note for note in result.limitations))
        self.assertEqual(meter.origin, 'synthetic')
        self.assertEqual(meter.reading_type, 'unknown')
        for forbidden in ('scenario_id', 'anomaly', 'fixture', 'file_path'):
            self.assertNotIn(forbidden, meter.model_dump())
        with self.assertRaises(ValidationError):
            context.bill.reviewed = False

    def test_partial_period_is_context_only_and_never_full_bill_total_comparison(self):
        data = example_context()
        data['bill']['bill'].update(period_start='2026-06-01', period_end_exclusive='2026-07-01')
        result = self.assess(data)
        self.assertEqual((result.status, result.coverage), ('ready', 'partial_period'))
        self.assertFalse(result.can_compare_period_totals)

    def test_households_origins_and_review_status_block_association(self):
        for key, value, reason in [('household_id', 'house_other1', 'different_households'),
                                   ('origin', 'user_provided', 'different_origins')]:
            data = example_context(); data['meter'][key] = value
            result = self.assess(data)
            self.assertEqual((result.status, result.reasons), ('blocked', (reason,)))
            self.assertEqual(result.coverage, 'none')
            self.assertFalse(result.can_compare_period_totals)
        data = example_context(); data['bill']['reviewed'] = False
        self.assertEqual(self.assess(data).reasons, ('bill_needs_review',))

    def test_adjacent_and_cross_boundary_windows_do_not_corroborate_a_bill(self):
        for start, end, reason in [
            ('2026-06-22T00:00:00Z', '2026-06-23T00:00:00Z', 'disjoint_periods'),
            ('2026-06-20T12:00:00Z', '2026-06-21T12:00:00Z', 'meter_outside_bill_period'),
            ('2024-07-24T00:00:00Z', '2024-07-25T00:00:00Z', 'disjoint_periods')]:
            data = example_context(); data['meter'].update(start=start, end_exclusive=end)
            result = self.assess(data)
            self.assertEqual((result.status, result.reasons), ('blocked', (reason,)))

    def test_timezone_and_dst_use_actual_instants_not_assumed_24_hour_days(self):
        data = example_context()
        data['bill'].update(timezone='America/Los_Angeles')
        data['bill']['bill'].update(period_start='2026-03-08', period_end_exclusive='2026-03-09')
        data['meter'].update(start='2026-03-08T00:00:00-08:00',
                             end_exclusive='2026-03-09T00:00:00-07:00', reading_count=92)
        self.assertEqual(self.assess(data).coverage, 'same_period')
        data['meter']['reading_count'] = 96
        with self.assertRaises(ValidationError):
            EvidenceContext.model_validate(data)
        data = example_context()
        data['meter'].update(start='2026-06-20T17:00:00-07:00',
                             end_exclusive='2026-06-21T17:00:00-07:00')
        self.assertEqual(self.assess(data).coverage, 'same_period')

    def test_reviewed_voice_is_a_query_not_evidence_of_real_meter_origin(self):
        data = example_context()
        data['voice'] = {'evidence_id': 'voice_demo1', 'household_id': 'house_demo1',
                         'reviewed': False, 'transcript': 'Explain this synthetic day.'}
        self.assertEqual(self.assess(data).reasons, ('voice_needs_review',))
        data['voice']['reviewed'] = True
        self.assertEqual(self.assess(data).status, 'ready')
        data['voice']['household_id'] = 'house_other1'
        self.assertEqual(self.assess(data).reasons, ('different_households',))

    def test_missing_evidence_is_incomplete_and_never_authorizes_comparison(self):
        for missing in ('bill', 'meter'):
            data = example_context(); data.pop(missing)
            result = self.assess(data)
            self.assertEqual(result.status, 'incomplete')
            self.assertEqual(result.reasons, ('missing_' + missing,))
            self.assertFalse(result.can_compare_period_totals)
        result = self.assess({'schema_version': 1})
        self.assertEqual(result.reasons, ('missing_bill', 'missing_meter'))

    def test_malformed_units_identity_timestamps_cadence_and_extra_fields_rejected(self):
        mutations = [
            ('schema_version', None, True), ('schema_version', None, 1.0),
            ('meter', 'volume_unit', 'kgal'), ('meter', 'reading_count', 95),
            ('meter', 'reading_count', True), ('meter', 'reading_count', 673),
            ('meter', 'interval_minutes', 0), ('meter', 'start', '2026-06-21T00:00:00'),
            ('meter', 'start', 'private upstream text'), ('meter', 'file_path', '/tmp/private'),
            ('bill', 'timezone', 'not/a/timezone'), ('bill', 'timezone', '../private'),
            ('bill', 'reviewed', 'true'), ('bill', 'account_number', 'private account'),
            ('meter', 'evidence_id', 'bill_demo01'), ('meter', 'dataset_sha256', 'bad'),
        ]
        for group, key, value in mutations:
            data = deepcopy(example_context())
            if key is None:
                data[group] = value
            else:
                data[group][key] = value
            with self.subTest(group=group, key=key), self.assertRaises(ValidationError):
                EvidenceContext.model_validate(data)

    def test_voice_bounds_and_invalid_error_strings_do_not_expose_raw_query(self):
        for text in ('', '   ', '\x00private query', 'q' * 2001):
            data = example_context()
            data['voice'] = {'evidence_id': 'voice_demo1', 'household_id': 'house_demo1',
                             'reviewed': True, 'transcript': text}
            with self.assertRaises(ValidationError):
                EvidenceContext.model_validate(data)
        data = example_context(); data['meter']['start'] = 'private upstream text'
        with self.assertRaises(ValidationError) as error:
            EvidenceContext.model_validate(data)
        self.assertNotIn('private upstream text', str(error.exception))
