from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from pydantic import ValidationError

SCRIPT = Path(__file__).resolve().parents[2] / 'evals/evidence_contract.py'
spec = importlib.util.spec_from_file_location('evidence_contract_eval', SCRIPT)
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


class EvidenceEvaluationTests(unittest.TestCase):
    def fixture(self):
        return json.loads(evaluation.DEFAULT_MANIFEST.read_text())

    def test_frozen_expectations_cover_outcomes_and_expected_rejections_separately(self):
        result = evaluation.evaluate(evaluation.Manifest.model_validate(self.fixture()))
        self.assertEqual(result['case_count'], 17)
        self.assertEqual(result['failed_cases'], 0)
        self.assertEqual(result['observed_status_counts'],
                         {'ready': 4, 'blocked': 7, 'incomplete': 2, 'invalid': 4})
        self.assertEqual(result['expected_invalid_cases'], 4)
        self.assertEqual(result['passed_cases'], result['case_count'])
        self.assertGreaterEqual(result['timing']['p95_ms'], result['timing']['p50_ms'])

    def test_wrong_expectation_stays_in_denominator_and_fails_the_cli(self):
        fixture = self.fixture()
        fixture['cases'][0]['expected']['coverage'] = 'partial_period'
        report = evaluation.evaluate(evaluation.Manifest.model_validate(fixture))
        self.assertEqual(report['failed_cases'], 1)
        self.assertEqual(report['case_count'], 17)
        self.assertAlmostEqual(report['case_pass_rate'], 16 / 17)
        with tempfile.TemporaryDirectory() as folder:
            manifest = Path(folder) / 'cases.json'
            manifest.write_text(json.dumps(fixture))
            done = subprocess.run([sys.executable, str(SCRIPT), '--manifest', str(manifest)],
                                  capture_output=True, text=True)
            self.assertEqual(done.returncode, 1)
            self.assertEqual(json.loads(done.stdout)['failed_cases'], 1)

    def test_duplicate_cases_unknown_grading_fields_and_empty_suite_are_not_accepted(self):
        source = self.fixture()
        for mutation in ('duplicate', 'unknown', 'empty', 'version'):
            fixture = deepcopy(source)
            if mutation == 'duplicate':
                fixture['cases'].append(deepcopy(fixture['cases'][0]))
            elif mutation == 'unknown':
                fixture['cases'][0]['expected']['ignore_errors'] = True
            elif mutation == 'version':
                fixture['schema_version'] = True
            else:
                fixture['cases'] = []
            with self.subTest(mutation=mutation), self.assertRaises(ValidationError):
                evaluation.Manifest.model_validate(fixture)

    def test_crashes_never_count_as_expected_invalid_and_raw_inputs_are_not_written(self):
        fixture = self.fixture()
        fixture['cases'] = [fixture['cases'][12]]  # An expected unsupported-unit rejection.
        manifest = evaluation.Manifest.model_validate(fixture)
        with patch.object(evaluation.EvidenceContext, 'model_validate',
                          side_effect=RuntimeError('private exception text')):
            result = evaluation.evaluate(manifest)
        self.assertEqual(result['failed_cases'], 1)
        self.assertEqual(result['observed_status_counts'], {'error': 1})
        self.assertNotIn('private exception text', json.dumps(result))
        fixture = self.fixture()
        fixture['base_context']['voice'] = {'evidence_id': 'voice_demo1',
            'household_id': 'house_demo1', 'reviewed': True, 'transcript': 'private transcript sentinel'}
        result = evaluation.evaluate(evaluation.Manifest.model_validate(fixture))
        serialized = json.dumps(result)
        self.assertNotIn('private transcript sentinel', serialized)
        self.assertNotIn('house_demo1', serialized)
        self.assertNotIn('usage_unit', serialized)

    def test_default_cli_records_source_hashes_and_refuses_to_replace_reports(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'report.json'
            args = [sys.executable, str(SCRIPT), '--output', str(output)]
            first = subprocess.run(args, capture_output=True, text=True, check=True)
            original = output.read_bytes()
            report = json.loads(first.stdout)
            self.assertEqual(report['kind'], 'evidence_contract_evaluation')
            self.assertEqual(len(report['manifest_sha256']), 64)
            self.assertEqual(len(report['source_sha256']), 3)
            second = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(second.returncode, 2)
            self.assertEqual(output.read_bytes(), original)

    def test_duplicate_json_keys_cannot_silently_change_a_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            manifest = Path(folder) / 'cases.json'
            manifest.write_text('{"schema_version":1,"schema_version":1,"base_context":{},"cases":[]}')
            done = subprocess.run([sys.executable, str(SCRIPT), '--manifest', str(manifest)],
                                  capture_output=True, text=True)
            self.assertEqual(done.returncode, 2)
            self.assertIn('Manifest could not be validated', done.stderr)
