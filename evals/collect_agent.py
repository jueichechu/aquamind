"""Collect the fixed development cohorts locally; execution requires an explicit flag.

Only the pinned fictional media may be sent. No positive goal approval is performed.
Answers and tool evidence are private artifacts, never console output.
"""

import argparse
import asyncio
import base64
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from unittest.mock import patch

from agent_contract import DEFAULT_MANIFEST, Manifest, Observation, RecordedRun, _read, confirmation_pin, grade, plan

ROOT = Path(__file__).resolve().parents[1]
PROTOCOLS = {name: ROOT / f'evals/fixtures/agent-{name}.json'
             for name in ('development-v1', 'development-v2', 'answer-regressions-v1', 'verification-wording-v1', 'confirmation-v1', 'weather-volume-regressions-v1', 'weather-volume-units-v1', 'host-rate-regressions-v1')}
MEDIA = {
    'image': ('16249570f778a700bf9349040374dec0cf4d1036185a6bd6814926618240153f', 70588),
    'voice': ('4cff39f74ce0858ea48925867c424a35aa1b52c18c90278aeca4c2d6ca19d1d3', 95568),
}
BILL = {'period_start': '2026-06-01', 'period_end_exclusive': '2026-07-01',
        'usage': '8.5', 'usage_unit': 'ccf'}
METER = {'csv_text': 'interval_start,volume\n2026-06-01T00:00:00+00:00,15\n2026-06-01T00:15:00+00:00,12\n',
         'volume_unit': 'us_gallons', 'interval_minutes': 15, 'timezone': 'UTC',
         'reading_type': 'actual', 'consent_to_process': True}
ENV = {'AQUAMIND_AGENT_ENABLED': '0', 'AQUAMIND_INFERENCE_ENABLED': '0',
       'AQUAMIND_DETECTOR_PATH': '', 'AQUAMIND_PUBLIC_MODE': '0',
       'AQUAMIND_RELAY_REQUIRED': '0', 'AQUAMIND_METER_IMPORT_ENABLED': '1'}


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def write_new(path, value):
    with path.open('xb') as stream:
        os.chmod(path, 0o600)
        stream.write(encoded(value))


def fingerprint():
    paths = sorted((ROOT / 'ml/aquamind_ml').glob('*.py')) + [
        ROOT / 'ml/data/demo/meter-v1.json', Path(__file__), ROOT / 'evals/agent_contract.py', *PROTOCOLS.values()]
    inventory = {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest() for p in paths}
    return sha256(encoded(inventory)).hexdigest(), inventory


def application_fingerprint():
    paths = sorted((ROOT / 'ml/aquamind_ml').glob('*.py')) + [ROOT / 'ml/data/demo/meter-v1.json']
    inventory = {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest() for p in paths}
    return sha256(encoded(inventory)).hexdigest(), inventory


def verify_confirmation(manifest):
    """Fail before provider work when application/artifacts differ from the sealed protocol."""
    if manifest.split != 'confirmation':
        return
    if application_fingerprint()[0] != manifest.runtime_sha256:
        raise ValueError('Confirmation application source differs from its pin')
    for name, digest in manifest.detector_files_sha256.items():
        if sha256((ROOT / 'ml/artifacts/detector-v1' / name).read_bytes()).hexdigest() != digest:
            raise ValueError('Confirmation detector differs from its pin')


def claim_confirmation(manifest, digest):
    if manifest.split != 'confirmation':
        return None
    directory = ROOT / 'evals/reports'
    directory.mkdir(parents=True, exist_ok=True)
    receipt = {'manifest_sha256': digest, 'confirmation_pin_sha256': confirmation_pin(manifest),
               'claimed_at': datetime.now(timezone.utc).isoformat()}
    # A new output directory must not silently replay the same confirmation protocol.
    write_new(directory / ('.confirmation-' + digest + '.started'), receipt)
    return sha256(encoded(receipt)).hexdigest()


def validate_confirmation_inputs(manifest):
    if manifest.split != 'confirmation':
        return
    from aquamind_ml.evidence_question import EvidenceQuestionRequest, prepare_evidence
    from aquamind_ml.meter_import import parse_meter_csv
    from aquamind_ml.sessions import DemoSessions
    sessions = DemoSessions()
    try:
        for case in manifest.cases:
            data = case.inputs
            if data.meter is None:
                continue
            token = sessions.create()
            try:
                meters = sessions.meters(token)
                ref = meters.replace(parse_meter_csv(data.meter)).context.evidence_id
                prepare_evidence(EvidenceQuestionRequest.model_validate({
                    'text': case.question, 'bill': data.bill.model_dump(mode='json'),
                    'bill_timezone': data.bill_timezone, 'bill_input_method': 'manual_entry',
                    'bill_reading_type': data.bill_reading_type, 'meter_evidence_id': ref,
                    'bill_reviewed': True, 'meter_reviewed': True, 'same_household': True, 'share_with_ai': True}), meters)
            finally:
                sessions.revoke(token)
    finally:
        sessions.close()


def media_bytes(path, kind):
    digest, size = MEDIA[kind]
    if path.stat().st_size != size:
        raise ValueError('Only the pinned fictional media are allowed')
    data = path.read_bytes()
    if sha256(data).hexdigest() != digest:
        raise ValueError('Only the pinned fictional media are allowed')
    return data


def private_output(path):
    target = path.resolve()
    if not any(target.is_relative_to(ROOT / parent) for parent in ('evals/reports', '.codex-local')):
        raise ValueError('Use ignored local report storage')
    target.mkdir(mode=0o700, parents=True, exist_ok=False)
    return target


class CountedProvider:
    """Count real SDK method attempts before awaiting, across with_options clones."""

    def __init__(self, client, ledger):
        self.client, self.ledger = client, ledger
        self.responses = SimpleNamespace(create=self.response)
        self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=self.transcribe))

    def with_options(self, **kwargs):
        if kwargs.get('max_retries') != 0:
            raise ValueError('Automatic retries are forbidden')
        return CountedProvider(self.client.with_options(**kwargs), self.ledger)

    async def request(self, kind, method, kwargs):
        ledger = self.ledger
        if ledger['total'] >= ledger['maximum'] or len(ledger['events']) >= ledger['case_maximum']:
            raise ValueError('Predeclared provider budget exhausted')
        event = {'kind': kind, 'requested_model': kwargs['model'], 'outcome': 'unconfirmed'}
        ledger['total'] += 1
        ledger['events'].append(event)
        started = monotonic()
        try:
            result = await method(**kwargs)
            event.update(outcome='received', model=getattr(result, 'model', None) or kwargs['model'])
            return result
        finally:
            event['elapsed_ms'] = round((monotonic() - started) * 1000, 3)

    async def response(self, **kwargs):
        if kwargs.get('store') is not False:
            raise ValueError('Responses storage must be disabled')
        return await self.request('reasoning', self.client.responses.create, kwargs)

    async def transcribe(self, **kwargs):
        return await self.request('transcription', self.client.audio.transcriptions.create, kwargs)


def clean(value):
    """Discard credentials/opaque IDs; retain only fictional answer/evidence content."""
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items() if k not in {
            'session_token', 'approval_id', 'request_id', 'response_id', 'call_id',
            'evidence_id', 'household_id', 'dataset_sha256'}}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


def normalized_values(fields):
    from aquamind_ml.bills import ManualBill, normalize_bill
    bill = normalize_bill(ManualBill.model_validate(fields))
    return {'billing_days': bill.billing_days, 'bill_total_us_gallons': bill.total_us_gallons,
            'daily_us_gallons': bill.us_gallons_per_day}


async def host_case(case, sessions, token):
    from mcp import Client
    from aquamind_ml.agent_tools import McpAgentTools
    from aquamind_ml.meter_import import MeterImportRequest, parse_meter_csv
    from aquamind_ml.meter_mcp import create_imported_meter_server
    store = sessions.meters(token)
    ref = store.replace(parse_meter_csv(MeterImportRequest.model_validate(METER))).context.evidence_id
    async with Client(create_imported_meter_server(store, ref, frozenset({'meter:read'}))) as client:
        adapter = McpAgentTools(client, frozenset({'get_meter_summary', 'get_meter_series'}), timeout_seconds=.02)
        await adapter.discover()
        if case.case_id == 'adapter-forbidden-tool':
            result = await adapter.execute('denied', 'set_conservation_goal', '{"request":{"daily_gallons":150}}')
        elif case.case_id == 'adapter-uncertain-timeout':
            class SlowTransport:
                async def call_tool(self, *args, **kwargs):
                    await asyncio.sleep(.1)
            adapter.client = SlowTransport()
            result = await adapter.execute('slow', 'get_meter_summary', '{}')
        else:
            result = await adapter.execute('summary', 'get_meter_summary', '{}')
            await adapter.execute('series', 'get_meter_series', '{}')
        values = ({'meter_total_us_gallons': result.data['result']['total_us_gallons']}
                  if result.status == 'success' else {})
        return None, 'tool_result' if result.status == 'success' else result.status, values, {'tool_trace': adapter.trace}


async def workflow_case(case, http, sessions, token, image, voice, artifact):
    from aquamind_ml.evidence_question import EvidenceQuestionRequest, prepare_evidence
    auth = {'Authorization': 'Bearer ' + token}
    steps, values = [], {}
    artifact['steps'] = steps

    async def post(path, body):
        r = await http.post(path, headers=auth, json=body)
        data = r.json()
        steps.append({'path': path, 'http_status': r.status_code, 'result': clean(data)})
        return r, data

    async def imported_image():
        return await post('/v1/bills/import', {'media_type': 'image/png',
            'data_base64': base64.b64encode(image).decode(), 'share_with_ai': True})

    async def transcript(share=True):
        return await post('/v1/audio/transcribe', {'media_type': 'audio/wav',
            'data_base64': base64.b64encode(voice).decode(), 'share_with_ai': share})

    cid, question = case.case_id, case.question
    inputs = case.inputs
    entered_bill = inputs.bill.model_dump(mode='json') if inputs and inputs.bill else dict(BILL)
    if case.workflow == 'demo_agent':
        scenario = {'demo-summary': 'normal', 'demo-series': 'normal',
                    'demo-anomaly': 'overnight-leak', 'demo-weather': 'irrigation-after-rain'}.get(cid)
        if inputs is not None:
            scenario = inputs.scenario_id
        r, data = await post('/v1/agent/turn', {'text': question, **({'scenario_id': scenario} if scenario else {})})
        if cid == 'goal-proposal-only':
            values['goal_daily_gallons'] = (await http.get('/v1/goals/current', headers=auth)).json()['goal']
    elif case.workflow == 'continuation':
        # Reject only: a collector has no authority to grant positive human approval.
        r, data = await post('/v1/agent/turn', {'text': 'Propose a daily water goal of 150 gallons; do not apply it.'})
        pending = data.get('pending_approval')
        if pending:
            _, decision = await post('/v1/approvals/' + pending['approval_id'] + '/decision', {'decision': 'reject'})
            if decision.get('status') == 'rejected':
                r, data = await post('/v1/agent/continue', {'approval_id': pending['approval_id']})
    elif case.workflow == 'bill_agent':
        values.update(normalized_values(entered_bill))
        r, data = await post('/v1/agent/bill', {'text': question, 'bill': entered_bill, 'is_example': True, 'share_with_ai': True})
    elif case.workflow == 'bill_import':
        r, data = await imported_image()
        if r.status_code == 200:
            values.update(needs_review=data.get('needs_review'), source=data.get('source'))
            try:
                values.update(normalized_values(data['fields']))
            except ValueError:
                pass  # Missing/invalid candidates remain a recorded failure, never filled from expectations.
    elif case.workflow == 'voice_transcription':
        r, data = await transcript(cid != 'voice-without-sharing')
        if r.status_code == 200:
            values.update(needs_review=data.get('needs_review'), source=data.get('source'), transcript=data.get('text'))
    else:
        meter_body = inputs.meter.model_dump(mode='json') if inputs and inputs.meter else METER
        r, meter = await post('/v1/meters/import', meter_body)
        r.raise_for_status()
        bill, method, reading_type = entered_bill, 'manual_entry', inputs.bill_reading_type if inputs else 'actual'
        if cid == 'image-voice-meter':
            r, imported = await imported_image()
            r.raise_for_status()
            bill, method, reading_type = imported['fields'], 'document_import', imported['evidence']['reading_type']
            r, spoken = await transcript()
            r.raise_for_status()
            question = spoken['text']  # Actual returned transcript, never the expected text.
        if cid == 'evidence-disjoint-period':
            bill.update(period_start='2024-06-01', period_end_exclusive='2024-07-01')
        body = {'text': question, 'bill': bill, 'bill_timezone': inputs.bill_timezone if inputs else 'UTC', 'bill_input_method': method,
                'bill_reading_type': reading_type, 'meter_evidence_id': meter['context']['evidence_id'],
                'bill_reviewed': True, 'meter_reviewed': True, 'same_household': True, 'share_with_ai': True}
        if cid not in {'evidence-disjoint-period', 'expired-evidence-session'}:
            facts = prepare_evidence(EvidenceQuestionRequest.model_validate(body), sessions.meters(token))
            values.update(normalized_values(bill), meter_total_us_gallons=facts['meter']['total_us_gallons'],
                          coverage=facts['assessment']['coverage'])
            steps.append({'normalized_evidence': clean(facts)})
        if cid == 'expired-evidence-session':
            sessions.revoke(token)
        r, data = await post('/v1/agent/evidence', body)
    status = ('http_error' if r.status_code >= 400 else 'imported' if case.workflow == 'bill_import'
              else 'transcript' if case.workflow == 'voice_transcription' else data.get('status', 'error'))
    return r.status_code, status, values, artifact


async def collect(manifest, digest, cohort, out, provider=None, maximum=0, image=None, voice=None, detector=None):
    import httpx
    from aquamind_ml.agent import AgentConfig
    from aquamind_ml.agent_http import AgentHost
    from aquamind_ml.agent_tools import McpAgentTools
    from aquamind_ml.api import create_app
    from aquamind_ml.sessions import DemoSessions

    verify_confirmation(manifest)
    validate_confirmation_inputs(manifest)
    if manifest.split == 'confirmation' and (provider is None or cohort != 'agent_workflow' or maximum != manifest.provider_calls_cap):
        raise ValueError('Confirmation collection requires a live-provider workflow cohort')
    if manifest.split == 'confirmation' and detector is None and any(
            rule.tool_name == 'detect_water_anomaly' for case in manifest.cases for rule in case.expected.tools):
        raise ValueError('Confirmation requires its loaded frozen detector')
    runtime, inventory = fingerprint()
    ledger = {'maximum': maximum, 'total': 0, 'case_maximum': 0, 'events': []}
    wrapped = CountedProvider(provider, ledger) if provider is not None else None
    sessions = DemoSessions()
    host = AgentHost(wrapped, AgentConfig(model=os.environ.get('OPENAI_MODEL', 'gpt-unconfigured')),
                     detector=detector) if wrapped else None
    claim = claim_confirmation(manifest, digest)
    run = {'schema_version': 1, 'suite_id': manifest.suite_id, 'manifest_sha256': digest,
           'cohort': cohort, 'source': 'live_provider' if wrapped else 'scripted',
           'runtime_source_sha256': runtime, 'models': {}, 'observations': [], 'reviews': []}
    if claim is not None:
        run.update(confirmation_pin_sha256=confirmation_pin(manifest), confirmation_claim_sha256=claim)
    write_new(out / 'collection-plan.json', {'manifest_sha256': digest, 'runtime_source_sha256': runtime,
        'runtime_inventory': inventory, 'cohort': cohort, 'maximum_provider_attempts': maximum,
        'split': manifest.split, 'pinned_application_sha256': manifest.runtime_sha256,
        'reasoning_model_requested': host.config.model if host else None,
        'confirmation_pin_sha256': confirmation_pin(manifest), 'confirmation_claim_sha256': claim,
        'media_sha256': {k: v[0] for k, v in MEDIA.items()} if wrapped else {},
        'detector_files': {p.name: sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT / 'ml/artifacts/detector-v1').glob('*')) if p.is_file()} if detector else {},
        'started_at': datetime.now(timezone.utc).isoformat(), 'automatic_retries': 0})
    app = create_app(sessions=sessions, agent_host=host)
    original = McpAgentTools.execute
    captured = []

    async def capture(adapter, call_id, name, arguments):
        result = await original(adapter, call_id, name, arguments)
        captured.append({'tool_name': adapter.trace[-1]['tool_name'], 'status': result.status,
                         'data': clean(result.data)})
        return result

    with patch.dict(os.environ, ENV), patch.object(McpAgentTools, 'execute', capture):
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://local-evaluation') as http:
            for case in manifest.cases:
                if case.cohort != cohort:
                    continue
                verify_confirmation(manifest)
                token = sessions.create()
                ledger.update(events=[], case_maximum=case.expected.provider_calls_max)
                captured.clear()
                started = monotonic()
                artifact, values, status, http_status = {}, {}, 'error', None
                decision, changed = 'none', False
                try:
                    if cohort == 'host_contract':
                        http_status, status, values, artifact = await host_case(case, sessions, token)
                    else:
                        http_status, status, values, artifact = await workflow_case(case, http, sessions, token, image, voice, artifact)
                    if case.case_id == 'rejected-continuation' and any(
                        s.get('result', {}).get('status') == 'rejected' for s in artifact.get('steps', [])):
                        decision = 'scripted_host'
                except Exception as error:
                    artifact['collection_error_type'] = type(error).__name__
                    # Error messages can contain provider request material. Never persist them.
                finally:
                    if case.case_id != 'expired-evidence-session':
                        goal = sessions.approvals(token).goal
                        changed = goal is not None
                        artifact['goal_after'] = goal.model_dump() if goal else None
                    sessions.revoke(token)
                for item in captured:
                    result = item['data'].get('result', {})
                    for source, dest in (('estimated_water_cost_usd', 'estimated_cost_usd'),
                                         ('estimated_water_savings_usd', 'estimated_savings_usd')):
                        if source in result:
                            values[dest] = result[source]
                artifact.update(case_id=case.case_id, tools=list(captured), provider_attempts=list(ledger['events']),
                    elapsed_ms=round((monotonic() - started) * 1000, 3), session_revoked=True)
                write_new(out / (case.case_id + '.json'), artifact)
                for event in ledger['events']:
                    run['models'][event['kind']] = event.get('model', event['requested_model'])
                observation = Observation(case_id=case.case_id, artifact_sha256=sha256(encoded(artifact)).hexdigest(),
                    http_status=http_status, status=status, provider_calls=len(ledger['events']), automatic_retries=0,
                    tool_trace=[{'tool_name': t['tool_name'], 'status': t['status']} for t in captured],
                    goal_changed=changed, decision_origin=decision, values=values)
                run['observations'].append(observation.model_dump())
                write_new(out / (case.case_id + '.observation.json'), observation.model_dump())
                print(json.dumps({'case_id': case.case_id, 'status': status, 'provider_attempts': len(ledger['events'])}), flush=True)
    if fingerprint()[0] != runtime:
        raise ValueError('Runtime changed during collection; artifacts retained, run not finalized')
    verify_confirmation(manifest)
    record = RecordedRun.model_validate(run)
    report = grade(manifest, digest, record)
    write_new(out / 'observations.json', run)
    write_new(out / 'grade-unreviewed.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--protocol', choices=list(PROTOCOLS), default='development-v1',
                        help='Explicit version; original v1 remains the default')
    parser.add_argument('--cohort', choices=['host_contract', 'agent_workflow'], default='host_contract')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--max-provider-calls', type=int, default=0)
    parser.add_argument('--fictional-image', type=Path)
    parser.add_argument('--synthetic-wav', type=Path)
    args = parser.parse_args()
    manifest, digest = _read(PROTOCOLS[args.protocol], Manifest)
    if not args.execute:
        print(json.dumps(plan(manifest), indent=2))
        return
    try:
        if args.output_dir is None:
            raise ValueError('A new private output directory is required')
        verify_confirmation(manifest)
        validate_confirmation_inputs(manifest)
        if args.cohort == 'agent_workflow':
            if manifest.split == 'confirmation' and args.max_provider_calls != manifest.provider_calls_cap:
                raise ValueError('Use the exact predeclared confirmation budget')
            if not 1 <= args.max_provider_calls <= 80 or not args.fictional_image or not args.synthetic_wav:
                raise ValueError('Supply pinned fictional media and a provider cap from 1 to 80')
            image, voice = media_bytes(args.fictional_image, 'image'), media_bytes(args.synthetic_wav, 'voice')
            from dotenv import load_dotenv
            load_dotenv(ROOT / '.env.local')
            if not os.environ.get('OPENAI_API_KEY') or not os.environ.get('OPENAI_MODEL'):
                raise ValueError('Existing local OpenAI configuration is required')
            from aquamind_ml.detector import FrozenDetector
            import torch
            torch.set_num_threads(1)
            detector = FrozenDetector(ROOT / 'ml/artifacts/detector-v1')
            out = private_output(args.output_dir)  # Exclusive guard before any paid request; no resume/replay.
            from openai import AsyncOpenAI
            async def run():
                async with AsyncOpenAI(api_key=os.environ['OPENAI_API_KEY'], base_url='https://api.openai.com/v1', max_retries=0, timeout=30) as provider:
                    return await collect(manifest, digest, args.cohort, out, provider,
                        args.max_provider_calls, image, voice, detector)
            report = asyncio.run(run())
        else:
            if args.max_provider_calls or args.fictional_image or args.synthetic_wav:
                raise ValueError('Host contracts need no provider budget or media')
            report = asyncio.run(collect(manifest, digest, args.cohort, private_output(args.output_dir)))
        print(json.dumps({'cohort': report['cohort'], 'outcomes': report['outcomes'], 'complete': report['complete']}))
        if report['outcomes']['failed'] or not report['complete']:
            raise SystemExit(1)
    except (OSError, ValueError):
        parser.error('Collection configuration or output invalid; any started directory must be preserved')


if __name__ == '__main__':
    main()
