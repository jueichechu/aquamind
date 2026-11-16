import asyncio
from hashlib import sha256
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

EVALS = Path(__file__).resolve().parents[2] / 'evals'
sys.path.insert(0, str(EVALS))
collection = importlib.import_module('collect_agent')


class AgentCollectionTests(unittest.IsolatedAsyncioTestCase):
    def ledger(self, maximum=2):
        return {'maximum': maximum, 'total': 0, 'case_maximum': 2, 'events': []}

    async def test_counts_uncertain_attempt_once_and_never_persists_exception_contents(self):
        sdk = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(side_effect=TimeoutError('PRIVATE secret'))))
        ledger = self.ledger()
        provider = collection.CountedProvider(sdk, ledger)
        with self.assertRaises(TimeoutError):
            await provider.responses.create(model='gpt-test', store=False)
        self.assertEqual(sdk.responses.create.await_count, 1)
        self.assertEqual(ledger['total'], 1)
        self.assertEqual(ledger['events'][0]['outcome'], 'unconfirmed')
        self.assertNotIn('PRIVATE', json.dumps(ledger))

    async def test_cloned_sdk_preserves_aggregate_budget_for_both_endpoints(self):
        result = SimpleNamespace(model='gpt-test-snapshot')
        sdk = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(return_value=result)),
            audio=SimpleNamespace(transcriptions=SimpleNamespace(create=AsyncMock(return_value=SimpleNamespace(text='test')))))
        sdk.with_options = lambda **kwargs: sdk
        ledger = self.ledger()
        provider = collection.CountedProvider(sdk, ledger).with_options(max_retries=0)
        await provider.responses.create(model='gpt-test', store=False)
        await provider.audio.transcriptions.create(model='gpt-transcribe')
        with self.assertRaises(ValueError):
            await provider.responses.create(model='gpt-test', store=False)
        self.assertEqual(ledger['total'], 2)
        self.assertEqual(ledger['events'][0]['model'], 'gpt-test-snapshot')
        self.assertEqual(sdk.responses.create.await_count, 1)
        with self.assertRaises(ValueError):
            provider.with_options(max_retries=1)

    async def test_storage_and_case_cap_fail_before_outbound_method(self):
        sdk = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock()))
        ledger = self.ledger(); ledger['case_maximum'] = 0
        provider = collection.CountedProvider(sdk, ledger)
        for kwargs in ({'model': 'gpt-test', 'store': True}, {'model': 'gpt-test', 'store': False}):
            with self.assertRaises(ValueError):
                await provider.responses.create(**kwargs)
        sdk.responses.create.assert_not_awaited()
        self.assertEqual(ledger['total'], 0)

    async def test_actual_host_cohort_is_complete_and_artifacts_are_bound(self):
        manifest, digest = collection._read(collection.DEFAULT_MANIFEST, collection.Manifest)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            report = await collection.collect(manifest, digest, 'host_contract', path)
            self.assertEqual(report['outcomes']['passed'], 3)
            self.assertEqual(report['tools']['attempts'], 4)
            run = json.loads((path / 'observations.json').read_text())
            self.assertEqual(run['source'], 'scripted')
            self.assertEqual(run['models'], {})
            for o in run['observations']:
                raw = (path / (o['case_id'] + '.json')).read_bytes()
                self.assertEqual(sha256(raw).hexdigest(), o['artifact_sha256'])
                self.assertEqual(o['provider_calls'], 0)
                self.assertFalse(o['goal_changed'])
                self.assertNotIn('house_', raw.decode())
                self.assertEqual((path / (o['case_id'] + '.json')).stat().st_mode & 0o777, 0o600)

    async def test_real_sdk_mock_runs_a_demo_case_without_filling_other_cases(self):
        import httpx2
        from openai import AsyncOpenAI
        from test_agent import call, is_topic_request, message, response, topic_response
        manifest, digest = collection._read(collection.DEFAULT_MANIFEST, collection.Manifest)
        manifest = manifest.model_copy(update={'cases': [c for c in manifest.cases if c.case_id in ('demo-summary', 'bill-off-topic')]})
        requests = []
        async def handle(request):
            body = json.loads(request.content); requests.append(body)
            if is_topic_request(body):
                result = topic_response('household_usage' if len(requests) == 1 else 'unsupported')
            elif len(requests) == 2:
                result = response([call(name='get_meter_summary', arguments='{}')])
            else:
                result = response([message('Synthetic readings describe a day, not a fixture diagnosis.')])
            result['model'] = 'gpt-test-snapshot'
            return httpx2.Response(200, json=result)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'OPENAI_MODEL': 'gpt-test'}):
            async with AsyncOpenAI(api_key='test-placeholder', max_retries=0,
                    http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle))) as sdk:
                await collection.collect(manifest, digest, 'agent_workflow', Path(directory), sdk, maximum=4)
            run = json.loads((Path(directory) / 'observations.json').read_text())
            first = run['observations'][0]
            self.assertEqual(first['status'], 'answer')
            self.assertEqual(first['provider_calls'], 3)
            self.assertEqual(first['tool_trace'], [{'tool_name': 'get_meter_summary', 'status': 'success'}])
            self.assertEqual(first['values'], {})
            artifact = json.loads((Path(directory) / 'demo-summary.json').read_text())
            self.assertTrue(artifact['tools'][0]['data']['result'])
            self.assertEqual(len(requests), 4)
            self.assertTrue(all(r['store'] is False for r in requests))

    async def test_partial_artifacts_survive_stage_failure_without_fabricated_facts(self):
        import httpx
        from aquamind_ml.sessions import DemoSessions
        manifest, _ = collection._read(collection.DEFAULT_MANIFEST, collection.Manifest)
        case = next(c for c in manifest.cases if c.case_id == 'image-voice-meter')
        sessions = DemoSessions(); token = sessions.create()
        artifact = {}
        async def handle(request):
            if request.url.path.endswith('/meters/import'):
                return httpx.Response(201, json={'context': {'evidence_id': 'meter_fixture'}})
            return httpx.Response(503, json={'detail': 'Unavailable'})
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url='http://test') as http:
                with self.assertRaises(httpx.HTTPStatusError):
                    await collection.workflow_case(case, http, sessions, token, b'fictional', b'audio', artifact)
            self.assertEqual([s['http_status'] for s in artifact['steps']], [201, 503])
            self.assertNotIn('data_base64', json.dumps(artifact))
            self.assertIsNone(sessions.approvals(token).goal)
        finally:
            sessions.close()

    def test_default_is_offline_and_outputs_and_media_cannot_be_reused(self):
        run = subprocess.run([sys.executable, str(EVALS / 'collect_agent.py')], capture_output=True, text=True,
            env={**os.environ, 'OPENAI_API_KEY': '', 'OPENAI_MODEL': ''})
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertFalse(json.loads(run.stdout)['execution_performed'])
        with tempfile.TemporaryDirectory(dir=EVALS / 'reports') as directory:
            with self.assertRaises(FileExistsError):
                collection.private_output(Path(directory))
            wrong = Path(directory) / 'image.png'; wrong.write_bytes(b'PRIVATE')
            with self.assertRaises(ValueError):
                collection.media_bytes(wrong, 'image')
            with self.assertRaises(FileExistsError):
                collection.write_new(wrong, {})
            self.assertEqual(wrong.read_bytes(), b'PRIVATE')
        with self.assertRaises(ValueError):
            collection.private_output(EVALS / 'fixtures/new-public-artifacts')

    def test_v2_protocol_is_an_explicit_offline_selection_and_fingerprinted(self):
        run = subprocess.run([sys.executable, str(EVALS / 'collect_agent.py'), '--protocol', 'development-v2'],
            capture_output=True, text=True, env={**os.environ, 'OPENAI_API_KEY': '', 'OPENAI_MODEL': ''})
        self.assertEqual(run.returncode, 0, run.stderr)
        value = json.loads(run.stdout)
        self.assertEqual(value['suite_id'], 'water-agent-development-v2')
        self.assertFalse(value['execution_performed'])
        self.assertEqual(value['cohorts'], {'agent_workflow': 19, 'host_contract': 3, 'human_approval': 1})
        _, inventory = collection.fingerprint()
        for path in collection.PROTOCOLS.values():
            self.assertEqual(inventory[str(path.relative_to(collection.ROOT))], sha256(path.read_bytes()).hexdigest())

    def test_answer_regression_protocol_is_separate_and_has_fixed_expected_cost_and_boundaries(self):
        manifest, _ = collection._read(collection.PROTOCOLS['answer-regressions-v1'], collection.Manifest)
        self.assertEqual(manifest.suite_id, 'water-answer-regressions-v1')
        self.assertEqual(len(manifest.cases), 7)
        self.assertTrue(all(c.cohort == 'agent_workflow' and not c.manual_gate for c in manifest.cases))
        cases = {c.case_id: c for c in manifest.cases}
        self.assertEqual(cases['cost-tool-shorthand'].expected.values['estimated_cost_usd'], '5.00')
        self.assertEqual(cases['bill-exclusive-dates'].expected.values['billing_days'], 30)
        for name in ('cost-mixed-task', 'cost-other-fluid'):
            self.assertEqual(cases[name].expected.status, 'refused')
            self.assertEqual(cases[name].expected.provider_calls_max, 1)
            self.assertEqual(cases[name].expected.tools, [])
        self.assertEqual(set(cases['meter-verification-pressure'].quality_rubric),
                         {'grounding', 'uncertainty', 'coverage_limits'})


if __name__ == '__main__':
    unittest.main()
