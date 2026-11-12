# Shared evidence context

The backend [evidence types](../ml/aquamind_ml/evidence.py) provide a bounded,
read-only compatibility contract for bill facts, meter-window metadata and a
reviewed voice query. This foundation has no HTTP endpoint, storage or provider
calls. Existing website routes and API contracts are unchanged. A separate,
opt-in [meter import API](meter-import.md) now binds parsed CSV data to host-owned
session references. There is no upload UI, voice recording or combined assistant yet.

## Validation and association

- Every item has an opaque evidence reference and household reference. Bill and
  meter sources explicitly distinguish synthetic from user-provided data.
- Bill facts reuse the existing ManualBill dates, quantities, unit and optional
  charge validation. An explicit IANA timezone maps exclusive calendar boundaries
  to instants; timezone is never inferred from an address or account.
- Meter metadata requires a dataset checksum, offset-aware minute-aligned instants,
  explicit volume unit and reading type. Cadence and count must match its duration.
  The initial bound is 672 readings, with a 1–60 minute cadence.
- Context assessment blocks different households, mixed synthetic/user sources,
  disjoint or cross-boundary periods and unreviewed bill/query input. Missing bill
  or meter evidence produces an incomplete assessment.
- A contained partial meter window is related context, but its total cannot be
  compared with the full bill total. Equal complete periods permit a later numeric
  comparison; the assessment itself does not calculate a meter total.
- A voice transcript is a question, not a measured water-use fact. A person can
  ask about a synthetic example. Its household reference and review status must
  still be compatible, and text is bounded to 2,000 characters.
- References must be distinct. Extra fields, unsupported units, naive timestamps,
  boolean counts/versions, unknown timezones and inconsistent durations are rejected.

The ready status means only that the supplied metadata permits association. It
does not verify source facts, establish a leak, authorize a tool, grant sharing
consent, approve a goal, or establish suitability for model inference. The frozen
detector still has its separate input/alignment and training-domain restrictions.

Matching supplied IDs is not authentication or proof of household ownership. A
host API must resolve references from the authenticated session and construct
trusted provenance before using this contract. Meter ingestion must verify the
actual sequence, checksum and gaps; matching count/duration metadata alone does
not prove that readings are contiguous. No media or arbitrary file paths belong
in this context. The demo_meter_context adapter copies existing host-selected
synthetic summary metadata without simulator anomaly or fixture labels.

## Offline measurements

Run from the repository root:

~~~sh
PYTHONPATH=ml ml/.venv/bin/python -m unittest discover -s ml/tests -p 'test_evidence*.py' -v
PYTHONPATH=ml ml/.venv/bin/python evals/evidence_contract.py \
  --output evals/reports/evidence-context-run-1.json
~~~

The [fictional manifest](../evals/fixtures/evidence-context-v1.json) declares a base
context, recursive per-case patches and expected decisions before execution. It
covers full/partial periods, household and origin mismatch, review requirements,
missing data, unsupported scale, incomplete counts, naive timestamps, forbidden
file fields and a daylight-saving boundary. Case IDs must be unique; an empty
suite, unknown grading fields and duplicate JSON keys are rejected.

The runner records counts, case decisions, a computed case pass rate, observed
status counts and nearest-rank p50/p95 elapsed time. It also records manifest/source
hashes and Python/Pydantic/environment metadata. Every declared case stays in the
denominator. Expected invalid inputs are listed separately: a successful rejection
is not a successful analysis, and a runtime crash never passes a rejection case.
Any failed case produces a nonzero exit status. Existing reports are not replaced.

Timing covers only in-process context validation and assessment, including initial
work in manifest order. These inspected regressions do not measure model accuracy,
tool execution success, end-to-end multimodal reasoning, transcription quality,
ML F1 or inference/API/browser latency. Those require separate runners and datasets
when the corresponding features are implemented. This command does not load API
credentials, access a provider or retry a request.

Reports omit bill values, household references, transcript text and validation
messages. Keep manifests fictional and generated reports in ignored local paths;
do not turn this fixture file into a repository of household data.
