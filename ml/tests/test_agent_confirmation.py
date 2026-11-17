"""Prospective-protocol contracts, not provider quality or human-review evidence."""

from copy import deepcopy
from hashlib import sha256
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx

EVALS = Path(__file__).resolve().parents[2] / 'evals'
sys.path.insert(0, str(EVALS))
collection = importlib.import_module('collect_agent')
evaluation = importlib.import_module('agent_contract')


class ConfirmationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.path = collection.PROTOCOLS['confirmation-v1']
        self.manifest, self.digest = evaluation._read(self.path, evaluation.Manifest)

    def test_plan_is_offline_and_keeps_confirmation_separate(self):
        result = evaluation.plan(self.manifest)
        self.assertEqual(result['split'], 'confirmation')
        self.assertFalse(result['execution_performed'])
        self.assertIsNone(result['measurements'])
        self.assertEqual(result['planned_cases'], 12)
        self.assertEqual(result['provider_calls_cap'], 49)
        self.assertEqual(result['cohorts'], {'agent_workflow': 12})
        self.assertEqual(len(result['tool_coverage']), 7)
        self.assertNotIn('set_conservation_goal', result['tool_coverage'])
        self.assertNotIn('csv_text', json.dumps(result))
        self.assertEqual(collection.fingerprint()[1]['evals/agent_contract.py'],
                         sha256((EVALS / 'agent_contract.py').read_bytes()).hexdigest())

    def test_confirmation_rejects_missing_pins_inputs_and_write_expectations(self):
        original = json.loads(self.path.read_bytes())
        for mutation in ('source', 'weights', 'budget', 'inputs', 'write', 'foreign_key', 'scenario_bill'):
            raw = deepcopy(original)
            if mutation == 'source': raw['runtime_sha256'] = None
            elif mutation == 'weights': raw['detector_files_sha256'].pop('weights.pt')
            elif mutation == 'budget': raw['provider_calls_cap'] = 1
            elif mutation == 'inputs': raw['cases'][0]['inputs'] = None
            elif mutation == 'write': raw['cases'][0]['expected']['tools'] = [dict(
                tool_name='set_conservation_goal', status='approval_required', minimum=1, maximum=1)]
            elif mutation == 'foreign_key': raw['cases'][0]['inputs']['session_token'] = 'not-allowed'
            else: raw['cases'][5]['inputs']['scenario_id'] = 'normal'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                evaluation.Manifest.model_validate(raw)

    async def test_source_mismatch_stops_before_provider_access_or_artifact_creation(self):
        provider = AsyncMock()
        with tempfile.TemporaryDirectory() as directory, patch.object(collection, 'application_fingerprint', return_value=('0' * 64, {})):
            out = Path(directory)
            with self.assertRaisesRegex(ValueError, 'source differs'):
                await collection.collect(self.manifest, self.digest, 'agent_workflow', out, provider, maximum=49)
            self.assertEqual(provider.mock_calls, [])
            self.assertEqual(list(out.iterdir()), [])

    async def test_whole_suite_cap_cannot_be_reduced_to_select_a_partial_run(self):
        provider = AsyncMock()
        with tempfile.TemporaryDirectory() as directory, patch.object(collection, 'verify_confirmation'), \
                patch.object(collection, 'claim_confirmation') as claim:
            for maximum in (48, 49):  # Reduced cap, then missing loaded detector.
                with self.subTest(maximum=maximum), self.assertRaises(ValueError):
                    await collection.collect(self.manifest, self.digest, 'agent_workflow', Path(directory), provider, maximum=maximum)
            claim.assert_not_called()
            self.assertEqual(provider.mock_calls, [])

    async def test_pin_change_between_cases_stops_next_request_and_retains_first_artifact(self):
        import os
        import httpx2
        from openai import AsyncOpenAI
        from test_agent import is_topic_request, message, response, topic_response
        raw = json.loads(self.path.read_bytes())
        raw['cases'] = [c for c in raw['cases'] if c['case_id'] in {'confirm-leap-liters', 'confirm-year-cubic-meters'}]
        manifest = evaluation.Manifest.model_validate(raw)
        requests = []

        async def handle(request):
            body = json.loads(request.content); requests.append(body)
            result = topic_response('water_bill') if is_topic_request(body) else response([message('Scripted bill explanation.')])
            result['model'] = 'gpt-test-snapshot'
            return httpx2.Response(200, json=result)

        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'OPENAI_MODEL': 'gpt-test'}), \
                patch.object(collection, 'verify_confirmation', side_effect=[None, None, ValueError('source changed')]), \
                patch.object(collection, 'claim_confirmation', return_value='c' * 64):
            async with AsyncOpenAI(api_key='test-placeholder', max_retries=0,
                    http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle))) as provider:
                with self.assertRaisesRegex(ValueError, 'source changed'):
                    await collection.collect(manifest, self.digest, 'agent_workflow', Path(directory), provider, maximum=49)
            self.assertEqual(len(requests), 2)
            self.assertTrue((Path(directory) / 'confirm-leap-liters.observation.json').exists())
            self.assertFalse((Path(directory) / 'confirm-year-cubic-meters.json').exists())
            self.assertFalse((Path(directory) / 'observations.json').exists())

    def test_artifact_checks_and_global_claim_prevent_accidental_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = root / 'ml/artifacts/detector-v1'; artifacts.mkdir(parents=True)
            hashes = {}
            for name in ('detector.json', 'weights.pt'):
                (artifacts / name).write_bytes(name.encode())
                hashes[name] = sha256(name.encode()).hexdigest()
            fixture = self.manifest.model_copy(update={'detector_files_sha256': hashes})
            with patch.object(collection, 'ROOT', root), patch.object(collection, 'application_fingerprint', return_value=(fixture.runtime_sha256, {})):
                collection.verify_confirmation(fixture)
                claim = collection.claim_confirmation(fixture, self.digest)
                self.assertEqual(len(claim), 64)
                marker = root / 'evals/reports' / ('.confirmation-' + self.digest + '.started')
                before = marker.read_bytes()
                self.assertEqual(marker.stat().st_mode & 0o777, 0o600)
                with self.assertRaises(FileExistsError):
                    collection.claim_confirmation(fixture, self.digest)
                self.assertEqual(marker.read_bytes(), before)
                (artifacts / 'weights.pt').write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'detector differs'):
                    collection.verify_confirmation(fixture)

    def test_all_evidence_inputs_are_preflighted_before_paid_work(self):
        collection.validate_confirmation_inputs(self.manifest)
        raw = json.loads(self.path.read_bytes())
        case = next(c for c in raw['cases'] if c['case_id'] == 'confirm-estimated-liters')
        case['inputs']['meter']['csv_text'] = case['inputs']['meter']['csv_text'].replace('00:15:00', '00:30:00')
        invalid = evaluation.Manifest.model_validate(raw)
        with self.assertRaises(ValueError):
            collection.validate_confirmation_inputs(invalid)

    async def test_collector_sends_explicit_bill_and_complete_timezone_inputs(self):
        from aquamind_ml.meter_import import MeterImportRequest, parse_meter_csv
        from aquamind_ml.sessions import DemoSessions
        sessions = DemoSessions(); self.addCleanup(sessions.close)
        token = sessions.create()
        bodies = []

        async def handle(request):
            body = json.loads(request.content); bodies.append((request.url.path, body))
            if request.url.path == '/v1/meters/import':
                selected = sessions.meters(token).replace(parse_meter_csv(MeterImportRequest.model_validate(body)))
                return httpx.Response(201, json=selected.model_dump(mode='json'))
            return httpx.Response(200, json={'status': 'answer', 'answer': 'Scripted response; not model quality.'})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url='http://test') as http:
            leap = next(c for c in self.manifest.cases if c.case_id == 'confirm-leap-liters')
            _, status, values, _ = await collection.workflow_case(leap, http, sessions, token, None, None, {})
            self.assertEqual(status, 'answer')
            self.assertEqual(bodies[-1][1]['bill']['usage_unit'], 'liters')
            self.assertEqual(bodies[-1][1]['bill']['period_end_exclusive'], '2024-03-01')
            self.assertEqual(values['billing_days'], 29)
            self.assertEqual(values['bill_total_us_gallons'], '1000.000000')
            whole = next(c for c in self.manifest.cases if c.case_id == 'confirm-complete-new-york')
            _, _, values, artifact = await collection.workflow_case(whole, http, sessions, token, None, None, {})
            self.assertEqual(bodies[-1][1]['bill_timezone'], 'America/New_York')
            self.assertEqual(bodies[-2][1]['interval_minutes'], 60)
            self.assertEqual(values['coverage'], 'same_period')
            self.assertEqual(values['meter_total_us_gallons'], '48.000000')
            facts = next(s['normalized_evidence'] for s in artifact['steps'] if 'normalized_evidence' in s)
            self.assertEqual(facts['meter']['context']['start'], '2026-08-03T04:00:00Z')
            self.assertFalse(facts['verification']['physical_water_use_independently_verified'])
            self.assertEqual(collection.BILL['usage_unit'], 'ccf')

    def test_grading_requires_matching_declared_pin_claim_and_live_source(self):
        record = dict(schema_version=1, suite_id=self.manifest.suite_id, cohort='agent_workflow',
            manifest_sha256=self.digest, source='live_provider', runtime_source_sha256='a' * 64,
            confirmation_pin_sha256=evaluation.confirmation_pin(self.manifest),
            confirmation_claim_sha256='b' * 64, observations=[], reviews=[])
        report = evaluation.grade(self.manifest, self.digest, evaluation.RecordedRun.model_validate(record))
        self.assertEqual(report['outcomes']['missing'], 12)
        self.assertIsNone(report['case_pass_rate'])
        for mutation in ('source', 'pin', 'claim'):
            invalid = dict(record)
            if mutation == 'source': invalid['source'] = 'scripted'
            elif mutation == 'pin': invalid['confirmation_pin_sha256'] = 'c' * 64
            else: invalid['confirmation_claim_sha256'] = None
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                evaluation.grade(self.manifest, self.digest, evaluation.RecordedRun.model_validate(invalid))


if __name__ == '__main__':
    unittest.main()
