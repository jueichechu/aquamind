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
    args = parser.parse_args()
    load_dotenv(ENV_FILE, override=False)
    if not all(os.environ.get(name, '').strip() for name in ('OPENAI_API_KEY', 'OPENAI_MODEL')):
        parser.error('Configure OPENAI_API_KEY and OPENAI_MODEL in the ignored root .env.local')
    os.environ['AQUAMIND_AGENT_ENABLED'] = '1'  # Opt in for this smoke process only.
    checks, turns = {}, []
    with TestClient(create_app()) as client:
        token = client.post('/v1/sessions').json()['session_token']
        headers = {'Authorization': 'Bearer ' + token}
        try:
            for name, question in (('utility', UTILITY_QUESTION), ('goal', GOAL_QUESTION)):
                started = perf_counter()
                response = client.post('/v1/agent/turn', headers=headers, json={'text': question})
                body = response.json()
                turns.append({'case': name, 'http_status': response.status_code,
                              'elapsed_ms': round((perf_counter() - started) * 1000, 3),
                              'result': body})
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
        finally:
            client.delete('/v1/session', headers=headers)
    sources = ('agent.py', 'agent_http.py', 'agent_tools.py', 'agent_smoke.py', 'api.py',
               'sessions.py', 'mcp_server.py', 'approvals.py')
    report = {'schema_version': 1, 'recorded_at_utc': datetime.now(timezone.utc).isoformat(),
              'transport': 'local FastAPI ASGI with live OpenAI Responses and in-process MCP',
              'source_sha256': {name: sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                for name in sources},
              'questions': {'utility': UTILITY_QUESTION, 'goal': GOAL_QUESTION},
              'checks': checks, 'passed': all(checks.values()), 'turns': turns,
              'limitations': ['Two development smoke cases, not an agent benchmark or pass-rate estimate.',
                              'Illustrative utility data; no meter, bill, image or voice inputs.',
                              'ASGI test client; no browser, public network or production deployment.',
                              'Text checks are narrow assertions, not a full answer-quality grader.',
                              'Rejection is sent by the trusted test host, not a human browser click.']}
    serialized = json.dumps(report, indent=2, allow_nan=False) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized)
    print(serialized, end='')
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
