from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from pydantic import ValidationError

SCRIPT = Path(__file__).resolve().parents[2] / 'evals/agent_contract.py'
spec = importlib.util.spec_from_file_location('agent_contract_eval', SCRIPT)
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


class AgentEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.raw = evaluation.DEFAULT_MANIFEST.read_bytes()
        self.digest = sha256(self.raw).hexdigest()
        self.manifest = evaluation.Manifest.model_validate(json.loads(self.raw))

    def subset(self, *ids):
        raw = self.manifest.model_dump()
        raw['cases'] = [c for c in raw['cases'] if c['case_id'] in ids]
        return evaluation.Manifest.model_validate(raw)

    def observation(self, case):
        expected = case.expected
        return dict(case_id=case.case_id, artifact_sha256='a' * 64,
            http_status=expected.http_status, status=expected.status,
            provider_calls=expected.provider_calls_min, automatic_retries=0,
            tool_trace=[dict(tool_name=r.tool_name, status=r.status) for r in expected.tools for _ in range(r.minimum)],
            goal_changed=expected.goal_changed, decision_origin=expected.decision_origin,
            values=dict(expected.values))

    def run_record(self, manifest, *, reviews=False, source='scripted'):
        cohort = manifest.cases[0].cohort
        cases = [c for c in manifest.cases if c.cohort == cohort]
        observations = [self.observation(c) for c in cases]
        return dict(schema_version=1, suite_id=manifest.suite_id, cohort=cohort, manifest_sha256=self.digest,
            source=source, runtime_source_sha256='b' * 64,
            models={} if source == 'scripted' else {'reasoning': 'gpt-test-model'}, observations=observations,
            reviews=[dict(case_id=c.case_id, artifact_sha256='a' * 64, criterion=criterion,
                verdict='pass', reviewer_id='fixture_reviewer', source='scripted_fixture' if source == 'scripted' else 'human')
                for c in cases for criterion in c.quality_rubric] if reviews else [])

    def grade(self, manifest, record):
        return evaluation.grade(manifest, self.digest, evaluation.RecordedRun.model_validate(record))

    def test_plan_is_not_execution_or_a_score_and_covers_real_tool_catalog(self):
        from aquamind_ml.agent_tools import AGENT_TOOLS
        result = evaluation.plan(self.manifest)
        self.assertFalse(result['execution_performed'])
        self.assertIsNone(result['measurements'])
        self.assertEqual(set(result['tool_coverage']), AGENT_TOOLS)
        self.assertEqual(result['manual_cases'], ['human-approved-continuation'])
        self.assertIn('image-voice-meter', {c['case_id'] for c in result['cases']})
        self.assertEqual(self.manifest.split, 'development')

    def test_missing_cases_and_unreviewed_answers_cannot_produce_a_final_rate(self):
        record = self.run_record(self.manifest)
        record['observations'] = record['observations'][:1]
        report = self.grade(self.manifest, record)
        planned = sum(c.cohort == 'agent_workflow' for c in self.manifest.cases)
        self.assertEqual(report['planned_cases'], planned)
        self.assertEqual(report['suite_cases'], len(self.manifest.cases))
        self.assertEqual(report['outcomes']['missing'], planned - 1)
        self.assertEqual(report['outcomes']['pending_review'], 1)
        self.assertFalse(report['complete'])
        self.assertIsNone(report['case_pass_rate'])
        record['observations'] = []
        self.assertIsNone(self.grade(self.manifest, record)['tools']['completion_rate'])

    def test_expected_denial_passes_case_but_remains_in_tool_denominator(self):
        manifest = self.subset('adapter-scoped-read', 'adapter-forbidden-tool', 'adapter-uncertain-timeout')
        report = self.grade(manifest, self.run_record(manifest, reviews=True))
        self.assertEqual(report['outcomes']['passed'], 3)
        self.assertEqual(report['tools'], dict(attempts=4, successful_reads=2, approval_requests=0,
            expected_denials=1, other_errors=0, unconfirmed=1, invalid_outcomes=0, completion_rate=1/2))
        self.assertEqual(report['observation_source_declared'], 'scripted')
        self.assertFalse(report['execution_performed'])

    def test_wrong_facts_keep_failed_cases_in_the_complete_denominator(self):
        manifest = self.subset('bill-only-boundary', 'voice-editable-transcript')
        record = self.run_record(manifest, reviews=True)
        record['observations'][0]['values']['billing_days'] = 31
        record['observations'][1]['values']['needs_review'] = 1  # bool True must not equal integer1.
        record['observations'][1]['values']['transcript'] = 'PRIVATE wrong transcription'
        report = self.grade(manifest, record)
        self.assertTrue(report['complete'])
        self.assertEqual(report['outcomes']['failed'], 2)
        self.assertEqual(report['case_pass_rate'], 0)
        self.assertNotIn('PRIVATE', json.dumps(report))

    def test_unsafe_tools_retries_and_changed_goal_fail_without_inflating_completions(self):
        manifest = self.subset('evidence-partial-period')
        record = self.run_record(manifest, reviews=True)
        o = record['observations'][0]
        o['tool_trace'] += [{'tool_name': 'set_conservation_goal', 'status': 'success'},
                            {'tool_name': 'get_weather_context', 'status': 'success'}]
        o.update(automatic_retries=1, goal_changed=True, decision_origin='agent', provider_calls=8)
        report = self.grade(manifest, record)
        self.assertEqual(report['outcomes']['failed'], 1)
        self.assertEqual(report['tools']['invalid_outcomes'], 2)
        self.assertEqual(report['tools']['completion_rate'], 1/3)
        self.assertIn('automatic_retry_observed', report['cases'][0]['issues'])
        self.assertIn('goal_changed_mismatch', report['cases'][0]['issues'])

    def test_wrong_tool_order_and_missing_required_tool_fail(self):
        manifest = self.subset('evidence-partial-period')
        record = self.run_record(manifest, reviews=True)
        record['observations'][0]['tool_trace'].insert(0, {'tool_name': 'get_meter_series', 'status': 'success'})
        report = self.grade(manifest, record)
        self.assertIn('first_tool_mismatch', report['cases'][0]['issues'])
        record['observations'][0]['tool_trace'] = []
        self.assertIn('tool_count_mismatch', self.grade(manifest, record)['cases'][0]['issues'])

    def test_reviews_are_artifact_bound_and_cannot_be_silently_duplicated_or_ignored(self):
        manifest = self.subset('demo-summary')
        source = self.run_record(manifest, reviews=True)
        for mutation in ('duplicate', 'artifact', 'criterion', 'case', 'scripted_live_review'):
            record = deepcopy(source)
            if mutation == 'duplicate': record['reviews'].append(deepcopy(record['reviews'][0]))
            elif mutation == 'artifact': record['reviews'][0]['artifact_sha256'] = 'c' * 64
            elif mutation == 'criterion': record['reviews'][0]['criterion'] = 'coverage_limits'
            elif mutation == 'case': record['reviews'][0]['case_id'] = 'unknown'
            else:
                record['source'] = 'live_provider'; record['models'] = {'reasoning': 'gpt-test-model'}
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.grade(manifest, record)
        source['reviews'][0]['verdict'] = 'fail'
        self.assertEqual(self.grade(manifest, source)['outcomes']['failed'], 1)

    def test_manifest_identity_duplicate_observations_and_unknown_cases_fail_closed(self):
        source = self.run_record(self.manifest)
        for mutation in ('manifest', 'suite', 'duplicate', 'unknown'):
            record = deepcopy(source)
            if mutation == 'manifest': record['manifest_sha256'] = 'f' * 64
            elif mutation == 'suite': record['suite_id'] = 'another_suite'
            elif mutation == 'duplicate': record['observations'].append(deepcopy(record['observations'][0]))
            else: record['observations'][0]['case_id'] = 'unknown'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): self.grade(self.manifest, record)

    def test_assistant_reviews_are_disclosed_and_cannot_fill_human_gate(self):
        manifest = self.subset('demo-summary')
        record = self.run_record(manifest, reviews=True, source='live_provider')
        for review in record['reviews']:
            review['source'] = 'assistant'
        report = self.grade(manifest, record)
        self.assertEqual(report['review_sources_declared'], {'assistant': 2})
        self.assertEqual(report['outcomes']['passed'], 1)
        manifest = self.subset('human-approved-continuation')
        record = self.run_record(manifest, reviews=True, source='browser_recording')
        record['reviews'][0]['source'] = 'assistant'
        with self.assertRaises(ValueError):
            self.grade(manifest, record)

    def test_human_gate_cannot_be_completed_by_scripted_or_agent_approval(self):
        manifest = self.subset('human-approved-continuation')
        record = self.run_record(manifest, reviews=True)
        with self.assertRaises(ValidationError): self.grade(manifest, record)
        # Synthetic metadata tests only; this does not perform or attest a human action.
        record = self.run_record(manifest, reviews=True, source='browser_recording')
        self.assertEqual(self.grade(manifest, record)['outcomes']['passed'], 1)
        record['observations'][0]['decision_origin'] = 'agent'
        self.assertEqual(self.grade(manifest, record)['outcomes']['failed'], 1)

    def test_fixed_cohorts_prevent_pooling_faults_or_manual_decisions_with_model_runs(self):
        self.assertEqual(evaluation.plan(self.manifest)['cohorts'],
                         {'agent_workflow': 19, 'human_approval': 1, 'host_contract': 3})
        record = self.run_record(self.manifest)
        adapter = next(c for c in self.manifest.cases if c.case_id == 'adapter-forbidden-tool')
        record['observations'].append(self.observation(adapter))
        with self.assertRaises(ValueError): self.grade(self.manifest, record)
        manifest = self.subset('adapter-forbidden-tool')
        record = self.run_record(manifest, source='live_provider')
        with self.assertRaises(ValidationError): self.grade(manifest, record)

    def test_schema_rejects_unknown_grading_options_and_unreviewable_answer_cases(self):
        for mutation in ('unknown', 'empty', 'duplicate', 'version', 'rubric', 'self_approval'):
            raw = json.loads(self.raw)
            if mutation == 'unknown': raw['ignore_failed_cases'] = True
            elif mutation == 'empty': raw['cases'] = []
            elif mutation == 'duplicate': raw['cases'].append(deepcopy(raw['cases'][0]))
            elif mutation == 'version': raw['schema_version'] = True
            elif mutation == 'rubric': raw['cases'][0]['quality_rubric'] = []
            else: raw['cases'][0]['expected']['goal_changed'] = True
            with self.subTest(mutation=mutation), self.assertRaises(ValidationError):
                evaluation.Manifest.model_validate(raw)

    def test_cli_plan_hashes_exclusive_reports_and_incomplete_grading_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'report.json'
            command = [sys.executable, str(SCRIPT), '--output', str(output)]
            done = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            report = json.loads(done.stdout)
            self.assertEqual(report['manifest_sha256'], self.digest)
            self.assertEqual(len(report['grader_sha256']), 64)
            self.assertIsNone(report['measurements'])
            original = output.read_bytes()
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 2)
            self.assertEqual(output.read_bytes(), original)
            records = Path(folder) / 'observations.json'
            records.write_text(json.dumps(self.run_record(self.manifest)))
            done = subprocess.run([sys.executable, str(SCRIPT), '--observations', str(records)], capture_output=True, text=True)
            self.assertEqual(done.returncode, 1, done.stderr)
            self.assertGreater(json.loads(done.stdout)['outcomes']['pending_review'], 0)

    def test_cli_rejects_duplicate_keys_nonfinite_and_oversize_without_echoing_data(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'manifest.json'
            for raw in ('{"schema_version":1,"schema_version":1}', '{"PRIVATE":NaN}', 'x' * (2 * 1024 * 1024 + 1)):
                path.write_text(raw)
                done = subprocess.run([sys.executable, str(SCRIPT), '--manifest', str(path)], capture_output=True, text=True)
                self.assertEqual(done.returncode, 2)
                self.assertNotIn('PRIVATE', done.stderr)
