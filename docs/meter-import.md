# Session meter import API

The `/meter` workspace imports and reviews interval volumes. The Python feature
is disabled by default outside configured deployments. Set
`AQUAMIND_METER_IMPORT_ENABLED=1` in the Python service environment to exercise it.
The combined-service Blueprint enables it for `aqua` when that configuration is
synced and deployed. No setting changes on other services are required. Existing
bill analysis and the synthetic demo retain their behavior. No new credentials,
storage service, provider calls or detector changes are required. Agent reasoning
over imported readings is a separate integration, not enabled by this workspace.

## Website workflow

Open `/meter` directly or choose **Meter readings** from `/analyze`. Select a CSV,
choose its volume unit, cadence, IANA timezone and reading type, then explicitly
consent to processing the entire file on the application server. Selecting a file
alone performs no upload. Personal columns must be removed before selection.

Review the returned period, count, original unit, reading type and converted total.
The review checkbox is a local acknowledgement for this selection; it does not
verify the values, authorize AI sharing or approve a goal. Replacing, editing or
clearing resets review and processing consent. It is not a server-side approval
record and must not be treated as one by a future agent workflow.

Invalid replacements preserve the previously confirmed selection. An interrupted
or malformed response hides stale results and offers an explicit read-back or
clear action. There is no automatic upload or clear retry. If read-back is busy,
the selection remains unconfirmed. Session expiry requires a fresh import and
consent; it never silently replays the file into another session.

Use **Clear selected readings** when finished. Closing the workspace attempts to
revoke its session once; network failures can prevent immediate cleanup, in which
case normal expiry applies. Credentials and data are never put in cookies, URLs or
browser storage. Reloading does not restore uploads or review state.

## Input and semantics

Create a session with the existing `POST /v1/sessions` and use its bearer token.
Send `POST /v1/meters/import` with `Content-Type: application/json`:

```json
{
  "csv_text": "interval_start,volume\n2026-06-01T00:00:00+00:00,15\n2026-06-01T00:15:00+00:00,12\n",
  "volume_unit": "us_gallons",
  "interval_minutes": 15,
  "timezone": "UTC",
  "reading_type": "actual",
  "consent_to_process": true
}
```

The CSV has exactly `interval_start,volume` columns. Every value is the volume
used during the interval beginning at that timestamp. Cumulative meter-register
values and flow rates are unsupported; they need an explicit conversion workflow.
The host never guesses their meaning. Units are `us_gallons`, `ccf`, `cubic_meters`
or `liters`; `kgal`, imperial gallons and unspecified units are rejected.

Declare a cadence of 1–60 whole minutes, an IANA timezone and a reading type of
`actual`, `estimated`, `mixed` or `unknown`. Reading type is the user's assertion,
not independently verified. Timestamps must use ISO dates with `T`, whole minutes
and explicit `Z` or `±HH:MM` offsets consistent with the declared timezone.
Both occurrences of a repeated daylight-saving hour must have their correct
offsets. UTC continuity, rather than naive local clock arithmetic, determines gaps.
Missing, duplicate, overlapping or out-of-order intervals are rejected. Readings
are never silently sorted, interpolated or filled with zeros.

Volumes are nonnegative decimal strings in CSV, at most nine integer digits and
six decimal places, without thousands separators, suffixes or scientific notation.
At most 672 intervals, 64 KiB of UTF-8 CSV and 96 KiB of the entire JSON body are
accepted. The first limit reached applies, including escaping in JSON. The maximum
normalized flow is 1,000 US gallons/minute and the maximum total is 1,000,000 US
gallons. Zero is valid. All-invalid or partial imports fail atomically.

## Session ownership and lifetime

A successful import returns 201 with a host-generated evidence/household reference,
`user_provided` origin, input CSV SHA-256, validated period/cadence/count/unit,
timezone, six-decimal US-gallon total and limitations. The checksum identifies the
exact CSV bytes encoded as UTF-8, including line endings. It is not verification,
an access credential or a cross-session lookup key. Reading arrays and raw CSV
are not returned. Full-precision converted interval volumes remain in server RAM.

`GET /v1/meters/current` returns that session's summary or JSON `null`.
`DELETE /v1/meters/current` clears the selected dataset and returns 204.
A successful new import atomically replaces the previous dataset; its old evidence
reference stops resolving. A failed import preserves the previous selection.
Each of the existing maximum 100 sessions can hold only one bounded dataset.

The existing one-hour session deadline applies; uploads do not extend it. Expired
or revoked sessions cannot read, clear, replace or resolve cached references. Data
is removed on clear, replacement, revocation, expiry cleanup, shutdown or process
restart. Expired idle data can remain in RAM until the next store access/session
creation; no background timer or durable store is introduced. Sessions and uploads
are process-local and cannot survive restarts or move across service replicas.

Only the authenticated host can resolve an evidence reference in its bound store.
Supplied household IDs, origin flags, checksums and filesystem paths are rejected.
Matching CSV checksums across sessions confer no access to either dataset.
This binds evidence to a session, not independently proven household ownership.

## Scoped MCP read tools

The host can call `create_imported_meter_server(store, evidence_id, scopes)` from
`aquamind_ml.meter_mcp`, using the repository resolved through an active session.
Only `meter:read` is accepted. The server exposes `get_meter_summary` and
`get_meter_series`, with no tool arguments for changing selection. Each call
atomically checks the session and the original selected reference. Replacement,
clear, revocation and expiry make the old server fail rather than follow new data.

Series include up to 672 `interval_volumes_us_gallons`, rounded to six decimals.
These are converted interval volumes, not GPM or cumulative registers;
`context.volume_unit` still identifies the original CSV unit. Totals use the
unrounded normalized values, so rounded individual values need not sum exactly
to the displayed total. The existing bounded agent-tool adapter can discover and
execute these two tools, but the current text and bill-only assistants do not
bind this server or transmit imported readings to a provider.

No weather, utility, detector, goal proposal or approval tool is registered on the
imported-data server. The existing synthetic MCP server and tools are unchanged.

## Transport, privacy and limitations

Both application relays expose only the three method/path pairs above at
`/api/aquamind/v1/meters/...`. Existing relay authentication, actual-byte body limits,
public admission/concurrency limits, body deadlines and no-store responses apply.
The combined site still exposes no raw `/v1/` routes. Import is not a paid AI stage.
Consent to process readings must be explicitly true. This does not authorize sending
the readings to an external AI service or approving a conservation goal.

Raw CSV, readings, session tokens, evidence references and dataset checksums stay
out of application request logs. No file is written and no provider is called.
The public response says `not_enabled_for_imported_data`: the synthetic-trained
detector is not automatically applied to unfamiliar households. This API does not
fabricate weather, tariffs, a household baseline or a leak/fixture diagnosis.
The frozen model and its independent alignment restrictions remain unchanged.

## Validation

Run from the repository root:

```sh
PYTHONPATH=ml ml/.venv/bin/python -m unittest discover -s ml/tests -p 'test_meter*.py' -v
PYTHONPATH=ml ml/.venv/bin/python -m unittest discover -s ml/tests -p 'test_web.py' -v
pnpm test
```

Tests cover conversions, offsets/DST, gaps/duplicates/order, limits, session
isolation, expiry/revocation during body streaming, replacement, cleanup, privacy,
default-off configuration and both relays. UI checks cover consent, review reset,
loading, duplicate submission, uncertain-request read-back, rejection, expiry and
cleanup. Actual MCP execution checks scope, source identity, bounded series and
invalidation, including the existing agent adapter. Combined-service CI serves
`/meter` and imports the maximum 672 readings through HTTP under its existing
offline 512-MB limit. These checks
are inspected regressions, not measurements of field accuracy or AI performance.
