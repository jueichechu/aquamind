"""Offline evidence-contract measurements; no model, network, credentials or media."""

import argparse
from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
from math import ceil
from pathlib import Path
import platform
from time import perf_counter
from typing import Literal

from pydantic import VERSION as PYDANTIC_VERSION, Field, ValidationError, field_validator

from aquamind_ml.evidence import EvidenceContext, EvidenceModel, Reason, assess_evidence

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / 'evals/fixtures/evidence-context-v1.json'


class ExpectedOutcome(EvidenceModel):
    status: Literal['ready', 'blocked', 'incomplete', 'invalid']
    reasons: tuple[Reason, ...]
    coverage: Literal['same_period', 'partial_period', 'none']
    can_compare_period_totals: bool

    @field_validator('reasons', mode='before')
    @classmethod
    def json_array(cls, value):
        return tuple(value) if type(value) is list else value


class Case(EvidenceModel):
    case_id: str = Field(pattern=r'^[a-z][a-z0-9_-]{0,63}$')
    patch: dict
    expected: ExpectedOutcome


class Manifest(EvidenceModel):
    schema_version: Literal[1]
    base_context: dict
    cases: tuple[Case, ...] = Field(min_length=1, max_length=2000)

    @field_validator('schema_version', mode='before')
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError('Expected integer version')
        return value

    @field_validator('cases', mode='before')
    @classmethod
    def json_array(cls, value):
        return tuple(value) if type(value) is list else value

    @field_validator('cases')
    @classmethod
    def distinct_cases(cls, value):
        if len({case.case_id for case in value}) != len(value):
            raise ValueError('Case identities must be distinct')
        return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def _patch(base, patch):
    if isinstance(base, dict) and isinstance(patch, dict):
        return {**deepcopy(base), **{key: _patch(base.get(key), value) for key, value in patch.items()}}
    return deepcopy(patch)


def evaluate(manifest: Manifest) -> dict:
    rows = []
    for case in manifest.cases:
        started = perf_counter()
        try:
            context = EvidenceContext.model_validate(_patch(manifest.base_context, case.patch))
        except ValidationError:
            observed = dict(status='invalid', reasons=[], coverage='none', can_compare_period_totals=False)
        except Exception:
            observed = {'status': 'error'}
        else:
            try:
                result = assess_evidence(context)
                observed = result.model_dump(mode='json', exclude={'limitations'})
            except Exception:
                # A runtime defect is never a successful expected rejection.
                observed = {'status': 'error'}
        rows.append({'case_id': case.case_id,
            'passed': observed == case.expected.model_dump(mode='json'),
            'observed': observed, 'elapsed_ms': round((perf_counter() - started) * 1000, 6)})
    latencies = sorted(row['elapsed_ms'] for row in rows)
    passed = sum(row['passed'] for row in rows)
    return {'schema_version': 1, 'kind': 'evidence_contract_evaluation',
        'case_count': len(rows), 'passed_cases': passed, 'failed_cases': len(rows) - passed,
        'case_pass_rate': passed / len(rows),
        'expected_invalid_cases': sum(case.expected.status == 'invalid' for case in manifest.cases),
        'observed_status_counts': dict(Counter(row['observed']['status'] for row in rows)),
        'timing': {'scope': 'in-process context validation and assessment only',
            'p50_ms': latencies[ceil(.5 * len(rows)) - 1],
            'p95_ms': latencies[ceil(.95 * len(rows)) - 1]},
        'cases': rows, 'limitations': [
            'Fictional inspected contract regressions, not a representative accuracy benchmark.',
            'Expected invalid inputs count as successful rejection cases, not successful analysis.',
            'No agent/tool execution, transcription, vision, ML F1, API latency or browser performance is measured.',
            'No source values, household references, transcript text or validation messages are written.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument('--output', type=Path, help='Optional new report path; existing reports are never replaced')
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error('Report already exists; choose a new path')
    try:
        raw = args.manifest.read_bytes()
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError('Manifest exceeds limit')
        manifest = Manifest.model_validate(json.loads(raw, object_pairs_hook=_unique_object))
    except (OSError, ValueError, RecursionError):
        parser.error('Manifest could not be validated')
    report = evaluate(manifest)
    report['environment'] = {'python': platform.python_version(), 'pydantic': PYDANTIC_VERSION,
                             'system': platform.system(), 'machine': platform.machine()}
    report['manifest_sha256'] = sha256(raw).hexdigest()
    report['source_sha256'] = {str(path.relative_to(ROOT)): sha256(path.read_bytes()).hexdigest()
        for path in (Path(__file__).resolve(), ROOT / 'ml/aquamind_ml/evidence.py', ROOT / 'ml/aquamind_ml/bills.py')}
    serialized = json.dumps(report, indent=2, allow_nan=False) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x') as stream:
            stream.write(serialized)
    print(serialized, end='')
    if report['failed_cases']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
