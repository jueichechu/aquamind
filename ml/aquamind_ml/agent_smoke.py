"""Explicit paid, local ASGI smoke check. Never used by the automatic unit suite."""

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from time import perf_counter

from dotenv import load_dotenv
from fastapi.testclient import TestClient

from .agent_cli import ENV_FILE
from .api import create_app

UTILITY_QUESTION = ('Estimate the water-only cost of 1,000 gallons using the demo rate. '
                    'Use the utility tool and explain whether this is my actual utility tariff.')
GOAL_QUESTION = 'Propose a daily conservation goal of 150 gallons. Do not approve or execute it.'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--with-continuation', action='store_true',
                        help='Also check rejected/approved follow-ups; makes additional paid requests')
    args = parser.parse_args()
    load_dotenv(ENV_FILE, override=False)
    if not all(os.environ.get(name, '').strip() for name in ('OPENAI_API_KEY', 'OPENAI_MODEL')):
        parser.error('Configure OPENAI_API_KEY and OPENAI_MODEL in the ignored root .env.local')
    os.environ['AQUAMIND_AGENT_ENABLED'] = '1'  # Opt in for this smoke process only.
    checks, turns = {}, []
    with TestClient(create_app()) as client:
        token = client.post('/v1/sessions').json()['session_token']
        headers = {'Authorization': 'Bearer ' + token}

        def agent_request(name, path, payload):
            started = perf_counter()
            response = client.post(path, headers=headers, json=payload)
            body = response.json()
            turns.append({'case': name, 'http_status': response.status_code,
                          'elapsed_ms': round((perf_counter() - started) * 1000, 3), 'result': body})
            return body

        try:
            for name, question in (('utility', UTILITY_QUESTION), ('goal', GOAL_QUESTION)):
                agent_request(name, '/v1/agent/turn', {'text': question})
            utility, goal = [turn['result'] for turn in turns]
            checks['utility_answer'] = utility.get('status') == 'answer'
            checks['cost_tool_success'] = any(item['tool_name'] == 'estimate_water_cost' and
                item['status'] == 'success' for item in utility.get('tool_trace', []))
            checks['expected_amount_in_answer'] = '$5.00' in utility.get('answer', '')
            answer = utility.get('answer', '').lower()
            checks['rate_qualification_in_answer'] = 'illustrative' in answer or 'demo rate' in answer
            pending = goal.get('pending_approval') or {}
            checks['pending_goal_only'] = (goal.get('status') == 'approval_required' and
                goal.get('answer') == '' and pending.get('status') == 'approval_required' and
                pending.get('arguments') == {'daily_gallons': 150})
            checks['goal_unchanged'] = client.get('/v1/goals/current', headers=headers).json() == {'goal': None}
            if checks['pending_goal_only']:
                decision = client.post('/v1/approvals/' + pending['approval_id'] + '/decision',
                                       headers=headers, json={'decision': 'reject'})
                checks['trusted_host_rejection'] = decision.json().get('status') == 'rejected'
            else:
                checks['trusted_host_rejection'] = False
            if args.with_continuation:
                rejected = agent_request('rejected_followup', '/v1/agent/continue',
                                         {'approval_id': pending.get('approval_id', '')})
                checks['rejected_followup_answer'] = rejected.get('status') == 'answer'
                checks['rejected_goal_unchanged'] = client.get('/v1/goals/current', headers=headers).json() == {'goal': None}
                proposed = agent_request('approval_proposal', '/v1/agent/turn', {'text': GOAL_QUESTION})
                proposed_id = (proposed.get('pending_approval') or {}).get('approval_id', '')
                decision = client.post('/v1/approvals/' + proposed_id + '/decision',
                                       headers=headers, json={'decision': 'approve'})
                checks['trusted_host_approval'] = decision.json().get('status') == 'approved'
                approved = agent_request('approved_followup', '/v1/agent/continue', {'approval_id': proposed_id})
                checks['approved_followup_answer'] = approved.get('status') == 'answer' and '150' in approved.get('answer', '')
                checks['approved_goal_preserved'] = client.get('/v1/goals/current', headers=headers).json() == {'goal': {'daily_gallons': 150}}
                before = client.app.state.agent_host._total
                cached = client.post('/v1/agent/continue', headers=headers, json={'approval_id': proposed_id}).json()
                checks['cached_followup_without_new_attempt'] = (cached.get('answer') == approved.get('answer') and
                    cached.get('model_trace') == approved.get('model_trace') and client.app.state.agent_host._total == before)
        finally:
            client.delete('/v1/session', headers=headers)
    sources = ('agent.py', 'agent_http.py', 'agent_tools.py', 'agent_smoke.py', 'api.py',
               'sessions.py', 'mcp_server.py', 'approvals.py')
    report = {'schema_version': 2, 'with_continuation': args.with_continuation,
              'recorded_at_utc': datetime.now(timezone.utc).isoformat(),
              'transport': 'local FastAPI ASGI with live OpenAI Responses and in-process MCP',
              'source_sha256': {name: sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                for name in sources},
              'questions': {'utility': UTILITY_QUESTION, 'goal': GOAL_QUESTION},
              'checks': checks, 'passed': all(checks.values()), 'turns': turns,
              'limitations': ['Development smoke checks, not an agent benchmark or pass-rate estimate.',
                              'Illustrative utility data; no meter, bill, image or voice inputs.',
                              'ASGI test client; no browser, public network or production deployment.',
                              'Text checks are narrow assertions, not a full answer-quality grader.',
                              'Decisions are sent by the trusted test host, not human browser clicks.']}
    serialized = json.dumps(report, indent=2, allow_nan=False) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized)
    print(serialized, end='')
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
