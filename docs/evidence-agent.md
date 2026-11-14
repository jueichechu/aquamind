# Bill-and-meter questions

The `/meter` workspace can answer household-water questions using a reviewed bill
and the session's selected interval readings. This is a separate workflow from
the tool-free bill assistant at `/analyze` and the synthetic-data demo.

## Use the workspace

Enable `AQUAMIND_METER_IMPORT_ENABLED=1` and `AQUAMIND_AGENT_ENABLED=1` on the Python
service, with the existing server-side `OPENAI_API_KEY` and `OPENAI_MODEL`.
The combined-service Blueprint already enables meter import. No new credentials,
database, detector artifact or hosting upgrade is required for this integration.
Existing public usage limits and free-service availability limits still apply.

1. [Import interval CSV](meter-import.md) and review its period, units and total.
2. Enter the bill, or explicitly consent to reading a PDF/photo into editable
   candidates. Document extraction uses the same temporary session; it does not
   replace the meter selection. Check every candidate against the original.
3. Supply the bill's IANA calendar timezone and reading type. Confirm bill review
   and that both sources concern the same household. These are user assertions,
   not independent verification or proof of ownership.
4. Enter a household-water question and separately allow AI to read the bill
   fields, selected meter readings and question. This consent starts unchecked.

The original bill file is not sent again for a question. The server supplies
normalized bill fields and meter summary; the assistant can retrieve the selected
interval volumes through MCP. Editing evidence invalidates review, sharing and the
old answer. Sharing resets after every attempted question. Inputs and meter
replacement/clear controls are locked during extraction and answering. Loading,
failure and answer states are announced accessibly; failures are not retried.
Only the latest answer remains in the mounted workspace. Reload clears local state.

An optional [short WAV voice clip](voice-input.md) can supply the question text.
Transcription has separate sharing consent and produces an editable candidate;
reviewing it and explicitly asking the question are separate actions.

## HTTP contract and source binding

`POST /v1/agent/evidence` requires a bearer session and JSON up to 16 KiB:

```json
{
  "text": "What can these readings tell me about my bill?",
  "bill": {
    "period_start": "2026-06-01",
    "period_end_exclusive": "2026-07-01",
    "usage": "8.5",
    "usage_unit": "ccf"
  },
  "bill_timezone": "UTC",
  "bill_input_method": "manual_entry",
  "bill_reading_type": "unknown",
  "meter_evidence_id": "meter_reference_from_import",
  "bill_reviewed": true,
  "meter_reviewed": true,
  "same_household": true,
  "share_with_ai": true
}
```

The `bill` follows the existing `ManualBill` schema, including optional USD charges.
Input method is `manual_entry` or `document_import`; reading type is `actual`,
`estimated`, `mixed` or `unknown`. Every confirmation must be the literal JSON
boolean `true`. Unknown fields, client-computed totals, household IDs, paths,
tool permissions and synthetic scenario selections are rejected.

The host resolves the exact reference through the authenticated session and
normalizes original bill fields again. The meter period must fit wholly inside
the bill's calendar period in its declared timezone. Incompatible periods fail
before paid-stage reservation. Partial coverage is allowed but explicitly cannot
support whole-bill total comparison or extrapolation. Only identical complete
periods receive a host-calculated meter-minus-bill difference, based on displayed
six-decimal totals. Both sources remain unverified.

Replacement, clear, expiry and revocation invalidate the pinned source. The host
checks liveness before provider work, on tool execution and before releasing an
answer. A response for an invalidated selection is never displayed as current.
Revocation cannot undo data already sent to a provider.

The response retains the existing `AgentTurnResponse` schema. Validation uses
401/413/415/422, missing or foreign selection 404, changed selection 409, and
existing 429/503 admission/unavailability responses. The same-origin relays allow
only POST for this route, enforce actual-byte limits and use the existing 135-second
upstream deadline; the browser deadline is 150 seconds. Responses are not cached.

## Tool and privacy boundaries

Each question first uses the existing tool-free topic check. Only the question and
trusted workflow mode reach that classifier. The host then binds `meter:read`
and exposes only `get_meter_summary` and `get_meter_series`, with no selection
arguments. The first answering request forces `get_meter_summary`. An answer
without a successful summary, a different first tool or a failed tool stops the
turn. Meter evidence is read through the actual MCP server, not a model-supplied
reference or client-submitted reading array.

There are at most four provider calls including the topic check, three tool calls,
and the existing time/token limits. Existing shared session/process/daily attempt
budgets apply. A pending demo goal must be resolved before another workflow starts.
No continuation checkpoint or goal proposal is created here. No weather, utility
tariff, anomaly detector, savings or state-changing tool is available. The frozen
synthetic detector and demo approval workflow are unchanged.

Source IDs and checksums are omitted from provider-facing meter context. Bill
values, questions, raw CSV/readings and hidden provider protocol items stay out of
application logs and public execution traces. Bills/questions are not durably
stored. Meter data retains its existing session-only lifetime. Provider requests
use `store=False` and automatic retries disabled; this does not assert zero
provider retention. See [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data).
Model output is escaped text. Instructions require uncertainty and prohibit
invented diagnoses or evidence; this policy is not a guarantee of answer accuracy.

## Validation

Run the normal checks in the [development reference](development.md), or focus on:

```sh
PYTHONPATH=ml ml/.venv/bin/python -m unittest discover -s ml/tests -p test_evidence_agent_http.py -v
pnpm --filter web test src/app/meter/meter-workspace.test.tsx
```

HTTP tests exercise the real SDK with a simulated provider and actual in-process
MCP: complete/partial periods, required confirmations, foreign/stale references,
replacement/revocation/expiry during a turn, unsupported questions, ignored forced
tools, write attempts, bounded JSON, privacy and shared budgets. Frontend tests
cover review/sharing reset, captured payload, loading locks, failure without retry,
stale selection recovery and document candidates. Cloud CI runs these without
PyTorch; the combined-service smoke checks invalid consent and disjoint periods
before any external request under the existing offline 512-MB limit.

These are integration and regression checks, not a representative accuracy or
availability benchmark. Live-model checks should use explicitly consented or
fictional data and bounded attempts, without automatic retries.
