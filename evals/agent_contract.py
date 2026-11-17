"""Plan or grade declared agent observations offline; never executes cases or calls AI."""

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import platform
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from aquamind_ml.bills import ManualBill
from aquamind_ml.meter_import import MeterImportRequest

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / 'evals/fixtures/agent-development-v1.json'
Id = Annotated[str, Field(pattern=r'^[a-z][a-z0-9_-]{0,63}$')]
Digest = Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]
ToolName = Literal['get_meter_summary', 'get_meter_series', 'detect_water_anomaly',
    'get_weather_context', 'get_utility_rate', 'estimate_water_cost',
    'estimate_conservation_savings', 'set_conservation_goal', 'unrecognized_tool']
ToolStatus = Literal['success', 'approval_required', 'error', 'unconfirmed']
Workflow = Literal['demo_agent', 'bill_agent', 'evidence_agent', 'bill_import',
    'voice_transcription', 'tool_adapter', 'continuation']
ResultStatus = Literal['answer', 'approval_required', 'refused', 'unavailable',
    'unconfirmed', 'limit_reached', 'http_error', 'imported', 'transcript', 'error', 'tool_result']
Criterion = Literal['grounding', 'uncertainty', 'coverage_limits', 'model_limits',
    'conservation_guidance', 'topic_boundary']
Cohort = Literal['agent_workflow', 'host_contract', 'human_approval']
Fact = Literal['billing_days', 'bill_total_us_gallons', 'daily_us_gallons',
    'meter_total_us_gallons', 'coverage', 'transcript', 'needs_review', 'source',
    'estimated_cost_usd', 'estimated_savings_usd', 'goal_daily_gallons']
Value = Annotated[str, Field(max_length=2000)] | int | bool | None


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True, hide_input_in_errors=True)


class Versioned(StrictModel):
    schema_version: Literal[1]

    @field_validator('schema_version', mode='before')
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError('Expected integer version')
        return value


class ToolRule(StrictModel):
    tool_name: ToolName
    status: ToolStatus
    minimum: int = Field(ge=0, le=16)
    maximum: int = Field(ge=1, le=16)
    expected_denial: bool = False

    @model_validator(mode='after')
    def consistent(self):
        if self.minimum > self.maximum or (self.expected_denial and self.status != 'error'):
            raise ValueError('Invalid tool expectation')
        if self.tool_name in ('set_conservation_goal', 'unrecognized_tool') and self.status == 'success':
            raise ValueError('A goal tool requests approval; it never applies a goal')
        if self.status == 'approval_required' and self.tool_name != 'set_conservation_goal':
            raise ValueError('Only the goal tool can request approval')
        return self


class Expected(StrictModel):
    http_status: int | None = Field(ge=100, le=599)
    status: ResultStatus
    provider_calls_min: int = Field(ge=0, le=16)
    provider_calls_max: int = Field(ge=0, le=16)
    tools: list[ToolRule] = Field(max_length=16)
    first_tool: ToolName | None = None
    goal_changed: bool = False
    decision_origin: Literal['none', 'human_browser', 'scripted_host'] = 'none'
    values: dict[Fact, Value] = Field(default_factory=dict, max_length=16)

    @field_validator('tools')
    @classmethod
    def unique_rules(cls, rules):
        if len({(r.tool_name, r.status) for r in rules}) != len(rules):
            raise ValueError('Duplicate tool rule')
        return rules

    @model_validator(mode='after')
    def valid_budget(self):
        if self.provider_calls_min > self.provider_calls_max:
            raise ValueError('Invalid provider call range')
        if self.first_tool and not any(r.tool_name == self.first_tool and r.minimum for r in self.tools):
            raise ValueError('First tool must be required')
        return self


class CaseInputs(StrictModel):
    scenario_id: Literal['normal', 'overnight-leak', 'running-toilet', 'irrigation-after-rain'] | None = None
    bill: ManualBill | None = None
    meter: MeterImportRequest | None = None
    bill_timezone: Annotated[str, Field(min_length=1, max_length=64)] = 'UTC'
    bill_reading_type: Literal['actual', 'estimated', 'mixed', 'unknown'] = 'unknown'


class Case(StrictModel):
    case_id: Id
    cohort: Cohort
    workflow: Workflow
    category: Literal['valid_execution', 'expected_rejection', 'failure_recovery', 'multimodal']
    modalities: list[Literal['text', 'image', 'voice', 'meter']] = Field(min_length=1, max_length=4)
    setup: str = Field(min_length=1, max_length=2000)
    question: str | None = Field(default=None, min_length=1, max_length=2000)
    manual_gate: bool = False
    expected: Expected
    quality_rubric: list[Criterion] = Field(max_length=6)
    inputs: CaseInputs | None = None

    @model_validator(mode='after')
    def consistent(self):
        if len(set(self.modalities)) != len(self.modalities) or len(set(self.quality_rubric)) != len(self.quality_rubric):
            raise ValueError('Duplicate case tag or criterion')
        if self.expected.goal_changed and not (self.manual_gate and self.expected.decision_origin == 'human_browser'):
            raise ValueError('A changed goal requires a human browser gate')
        if self.manual_gate != (self.cohort == 'human_approval'):
            raise ValueError('Human gates belong in their separate cohort')
        if self.cohort == 'host_contract' and self.expected.provider_calls_max:
            raise ValueError('Host contract cases do not make provider calls')
        if self.expected.status == 'answer' and not self.quality_rubric:
            raise ValueError('Answers require explicit quality review')
        if self.inputs is not None:
            data = self.inputs
            if self.workflow not in {'demo_agent', 'bill_agent', 'evidence_agent'}:
                raise ValueError('Explicit inputs require a supported read-only workflow')
            if self.workflow == 'demo_agent':
                if data.bill is not None or data.meter is not None:
                    raise ValueError('Demo input cannot include a bill or imported readings')
            elif data.scenario_id is not None or data.bill is None:
                raise ValueError('Bill workflows need bill input, not a demo selection')
            if (self.workflow == 'evidence_agent') != (data.meter is not None):
                raise ValueError('Imported readings belong only to evidence workflows')
            if data.meter is not None and data.meter.consent_to_process is not True:
                raise ValueError('Fixture processing consent is required')
        return self


class Manifest(Versioned):
    suite_id: Id
    split: Literal['development', 'confirmation']
    runtime_sha256: Digest | None = None
    detector_files_sha256: dict[Literal['detector.json', 'weights.pt'], Digest] | None = None
    provider_calls_cap: int | None = Field(default=None, ge=1, le=80)
    rubric: dict[Criterion, Annotated[str, Field(min_length=1, max_length=1000)]]
    cases: list[Case] = Field(min_length=1, max_length=200)

    @model_validator(mode='after')
    def consistent(self):
        if len({c.case_id for c in self.cases}) != len(self.cases):
            raise ValueError('Duplicate case identity')
        if any(set(c.quality_rubric) - self.rubric.keys() for c in self.cases):
            raise ValueError('Undefined quality criterion')
        if self.split == 'confirmation':
            if self.runtime_sha256 is None or self.detector_files_sha256 is None or set(self.detector_files_sha256) != {'detector.json', 'weights.pt'}:
                raise ValueError('Confirmation requires pinned application and detector hashes')
            if self.provider_calls_cap is None or self.provider_calls_cap < sum(c.expected.provider_calls_max for c in self.cases):
                raise ValueError('Confirmation requires a predeclared whole-suite provider cap')
            if any(c.inputs is None or not c.question or c.cohort != 'agent_workflow' or
                   c.expected.goal_changed or c.manual_gate or
                   any(r.tool_name == 'set_conservation_goal' for r in c.expected.tools)
                   for c in self.cases):
                raise ValueError('This confirmation protocol requires explicit read-only agent cases')
        elif self.runtime_sha256 is not None or self.detector_files_sha256 is not None or self.provider_calls_cap is not None:
            raise ValueError('Runtime pins belong to the confirmation split')
        return self


class ToolEvent(StrictModel):
    tool_name: ToolName
    status: ToolStatus


class Observation(StrictModel):
    case_id: Id
    artifact_sha256: Digest
    http_status: int | None = Field(ge=100, le=599)
    status: ResultStatus
    provider_calls: int = Field(ge=0, le=32)
    automatic_retries: int = Field(ge=0, le=32)
    tool_trace: list[ToolEvent] = Field(max_length=32)
    goal_changed: bool
    decision_origin: Literal['none', 'human_browser', 'scripted_host', 'agent']
    values: dict[Fact, Value] = Field(default_factory=dict, max_length=16)


class Review(StrictModel):
    case_id: Id
    artifact_sha256: Digest
    criterion: Criterion
    verdict: Literal['pass', 'fail']
    reviewer_id: Id
    source: Literal['human', 'assistant', 'scripted_fixture']


class RecordedRun(Versioned):
    suite_id: Id
    cohort: Cohort
    manifest_sha256: Digest
    source: Literal['scripted', 'live_provider', 'browser_recording']
    runtime_source_sha256: Digest
    confirmation_pin_sha256: Digest | None = None
    confirmation_claim_sha256: Digest | None = None
    models: dict[Literal['reasoning', 'transcription'], Annotated[str, Field(pattern=r'^(gpt-[a-z0-9][a-z0-9.-]{0,63}|whisper-1|o[134](?:-[a-z0-9.-]+)?)$')]] = Field(default_factory=dict)
    observations: list[Observation] = Field(max_length=200)
    reviews: list[Review] = Field(default_factory=list, max_length=1200)

    @model_validator(mode='after')
    def provider_identity(self):
        if (self.confirmation_pin_sha256 is None) != (self.confirmation_claim_sha256 is None):
            raise ValueError('Confirmation pin and claim must be declared together')
        if self.source != 'scripted' and any(o.provider_calls for o in self.observations) and not self.models:
            raise ValueError('Provider observations require model identity')
        if self.cohort == 'host_contract' and self.source != 'scripted':
            raise ValueError('Host contract collection is a scripted test')
        if self.cohort == 'human_approval' and self.source != 'browser_recording':
            raise ValueError('Human approval requires browser evidence')
        return self


def _read(path, schema):
    raw = path.read_bytes()
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError('Input exceeds limit')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('Non-finite JSON number')
    return schema.model_validate(json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)), sha256(raw).hexdigest()


def confirmation_pin(manifest):
    if manifest.split != 'confirmation':
        return None
    payload = {'runtime_sha256': manifest.runtime_sha256, 'detector_files_sha256': manifest.detector_files_sha256}
    return sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def plan(manifest):
    return {'kind': 'agent_evaluation_plan', 'execution_performed': False, 'measurements': None,
        'suite_id': manifest.suite_id, 'split': manifest.split, 'planned_cases': len(manifest.cases),
        'confirmation_pin_sha256': confirmation_pin(manifest),
        'provider_calls_cap': manifest.provider_calls_cap,
        'cohorts': dict(Counter(c.cohort for c in manifest.cases)),
        'workflows': dict(Counter(c.workflow for c in manifest.cases)),
        'tool_coverage': sorted({r.tool_name for c in manifest.cases for r in c.expected.tools if r.tool_name != 'unrecognized_tool'}),
        'manual_cases': [c.case_id for c in manifest.cases if c.manual_gate],
        'cases': [{'case_id': c.case_id, 'cohort': c.cohort, 'workflow': c.workflow, 'modalities': c.modalities,
                   'quality_rubric': c.quality_rubric,
                   'provider_calls_min': c.expected.provider_calls_min,
                   'provider_calls_max': c.expected.provider_calls_max} for c in manifest.cases],
        'limitations': ['Collection specifications only; no cases, tools, media or provider calls executed.',
                        ('Prospectively specified confirmation cases, not independent or representative evidence.'
                         if manifest.split == 'confirmation' else 'Inspected development cases; no held-out or accuracy claim.')]}


def grade(manifest, manifest_digest, run):
    if run.suite_id != manifest.suite_id or run.manifest_sha256 != manifest_digest:
        raise ValueError('Run does not match the frozen manifest')
    if manifest.split == 'confirmation':
        if run.source != 'live_provider' or run.confirmation_pin_sha256 != confirmation_pin(manifest) or run.confirmation_claim_sha256 is None:
            raise ValueError('Confirmation requires declared live observations bound to its pin and claim')
    elif run.confirmation_pin_sha256 is not None:
        raise ValueError('Development observations cannot claim a confirmation pin')
    cases = {c.case_id: c for c in manifest.cases if c.cohort == run.cohort}
    if not cases:
        raise ValueError('Cohort has no planned cases')
    observed = {o.case_id: o for o in run.observations}
    if len(observed) != len(run.observations) or observed.keys() - cases.keys():
        raise ValueError('Duplicate or unplanned observation')
    reviews = {}
    for review in run.reviews:
        key = (review.case_id, review.criterion)
        if (key in reviews or review.case_id not in observed or review.criterion not in cases[review.case_id].quality_rubric or
                review.artifact_sha256 != observed[review.case_id].artifact_sha256 or
                (run.source != 'scripted' and review.source == 'scripted_fixture') or
                (run.cohort == 'human_approval' and review.source != 'human')):
            raise ValueError('Review is duplicated or not bound to this observed artifact')
        reviews[key] = review
    rows, outcomes = [], Counter()
    tools = Counter(attempts=0, successful_reads=0, approval_requests=0, expected_denials=0, other_errors=0, unconfirmed=0, invalid_outcomes=0)
    for case in cases.values():
        row = {'case_id': case.case_id, 'workflow': case.workflow, 'category': case.category, 'modalities': case.modalities}
        o = observed.get(case.case_id)
        if o is None:
            rows.append(row | {'outcome': 'missing', 'issues': ['not_observed']})
            outcomes['missing'] += 1
            continue
        expected, issues = case.expected, []
        for field in ('http_status', 'status', 'goal_changed', 'decision_origin'):
            if getattr(o, field) != getattr(expected, field):
                issues.append(field + '_mismatch')
        if not expected.provider_calls_min <= o.provider_calls <= expected.provider_calls_max:
            issues.append('provider_call_count_mismatch')
        if o.automatic_retries:
            issues.append('automatic_retry_observed')
        if case.manual_gate and run.source != 'browser_recording':
            issues.append('human_browser_evidence_required')
        if expected.first_tool and (not o.tool_trace or o.tool_trace[0].tool_name != expected.first_tool):
            issues.append('first_tool_mismatch')
        rules = {(r.tool_name, r.status): r for r in expected.tools}
        counts = Counter((t.tool_name, t.status) for t in o.tool_trace)
        if counts.keys() - rules.keys():
            issues.append('unexpected_tool_outcome')
        if any(not r.minimum <= counts[k] <= r.maximum for k, r in rules.items()):
            issues.append('tool_count_mismatch')
        for event in o.tool_trace:
            tools['attempts'] += 1
            rule = rules.get((event.tool_name, event.status))
            if ((event.status in ('success', 'approval_required') and rule is None) or
                    (event.status == 'success' and event.tool_name in ('set_conservation_goal', 'unrecognized_tool')) or
                    (event.status == 'approval_required' and event.tool_name != 'set_conservation_goal')):
                tools['invalid_outcomes'] += 1
            elif event.status == 'success':
                tools['successful_reads'] += 1
            elif event.status == 'approval_required':
                tools['approval_requests'] += 1
            elif event.status == 'unconfirmed':
                tools['unconfirmed'] += 1
            else:
                tools['expected_denials' if rule and rule.expected_denial else 'other_errors'] += 1
        for key, value in expected.values.items():
            if key not in o.values or type(o.values[key]) is not type(value) or o.values[key] != value:
                issues.append('fact_mismatch:' + key)
        pending = [r for r in case.quality_rubric if (case.case_id, r) not in reviews]
        if any(reviews[(case.case_id, r)].verdict == 'fail' for r in case.quality_rubric if (case.case_id, r) in reviews):
            issues.append('quality_review_failed')
        outcome = 'failed' if issues else 'pending_review' if pending else 'passed'
        outcomes[outcome] += 1
        rows.append(row | {'outcome': outcome, 'issues': issues, 'pending_criteria': pending})
    complete = not outcomes['missing'] and not outcomes['pending_review']
    attempts = tools['attempts']
    return {'kind': 'agent_observation_grading', 'execution_performed': False,
        'observation_source_declared': run.source, 'runtime_source_sha256_declared': run.runtime_source_sha256,
        'models_declared': run.models,
        'confirmation_pin_sha256_declared': run.confirmation_pin_sha256,
        'confirmation_claim_sha256_declared': run.confirmation_claim_sha256,
        'review_sources_declared': dict(Counter(r.source for r in run.reviews)),
        'suite_id': manifest.suite_id, 'split': manifest.split, 'cohort': run.cohort, 'complete': complete,
        'suite_cases': len(manifest.cases),
        'other_cohort_case_ids': [c.case_id for c in manifest.cases if c.cohort != run.cohort],
        'planned_cases': len(cases), 'observed_cases': len(observed),
        'outcomes': {key: outcomes[key] for key in ('passed', 'failed', 'pending_review', 'missing')},
        'case_pass_rate': outcomes['passed'] / len(cases) if complete else None,
        'tools': dict(tools) | {'completion_rate': (tools['successful_reads'] + tools['approval_requests']) / attempts if attempts else None},
        'cases': rows,
        'limitations': ['Grades supplied observations; does not execute or independently attest their origin.',
            ('Predeclared confirmation on a pinned runtime; not independent human or representative benchmark evidence.'
             if manifest.split == 'confirmation' else 'Inspected development cases, not a held-out or representative benchmark.'),
            'Scripted observations and reviews are contract checks, not live model quality.',
            'Assistant reviews are explicitly labeled, not independent human assessments.',
            'Missing cases stay planned; unreviewed answers cannot pass. No final case rate until complete.',
            'Tool completion includes reads and approval requests, never applied goals; all attempts including expected denials remain in its denominator.',
            'No raw answers, transcripts, fact values, reviewer names or provider errors are emitted.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument('--observations', type=Path, help='Optional declared observation/review JSON; no execution')
    parser.add_argument('--output', type=Path, help='New report path; never overwrite')
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error('Report already exists')
    try:
        manifest, digest = _read(args.manifest, Manifest)
        if args.observations:
            run, run_digest = _read(args.observations, RecordedRun)
            report = grade(manifest, digest, run)
            report['observations_sha256'] = run_digest
        else:
            report = plan(manifest)
    except (OSError, ValueError, RecursionError):
        parser.error('Evaluation inputs could not be validated')
    report.update(schema_version=1, manifest_sha256=digest,
                  grader_sha256=sha256(Path(__file__).read_bytes()).hexdigest(), python=platform.python_version())
    serialized = json.dumps(report, indent=2, allow_nan=False) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x') as stream:
            stream.write(serialized)
    print(serialized, end='')
    if args.observations and (not report['complete'] or report['outcomes']['failed']):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
