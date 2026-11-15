# Agent evaluation contracts

`evals/agent_contract.py` validates a versioned development-case manifest and grades
supplied observations offline. It does not run an agent, open a browser, transcribe
audio, upload images, make provider requests or approve proposals. The separate
[collector](../evals/collect_agent.py) executes the two non-human cohorts only
when explicitly requested; its default is also an offline plan.

The initial [development manifest](../evals/fixtures/agent-development-v1.json)
specifies the existing eight tools, bill-only isolation, partial/disjoint meter
coverage, image candidates, voice review, cross-modal reasoning, topic redirection,
expiry, expected denials, uncertain outcomes and approval continuation. These are
inspected development specifications, not held-out cases or a representative
speech, vision or reasoning benchmark. There is no confirmation split yet.

## Plan without execution

Run from the repository root using the existing Python environment:

```sh
PYTHONPATH=ml ml/.venv/bin/python evals/agent_contract.py
PYTHONPATH=ml ml/.venv/bin/python evals/agent_contract.py --output evals/reports/agent-plan.json
```

The default output is a plan with `execution_performed: false` and
`measurements: null`. It lists case identities, workflows, modalities, rubric
criteria and manual gates. Tool coverage means the tool is specified, not tested.
No credentials are loaded or required. Reports include the exact manifest-byte
SHA-256, grader-source SHA-256 and Python version. Existing output files are never
overwritten; generated reports belong in ignored `evals/reports/` or private storage.

## Observation contract

`RecordedRun` in [the evaluator](../evals/agent_contract.py) is a strict schema for
a normalized collection record. Its top-level fields are:

| Field | Meaning |
| --- | --- |
| `schema_version`, `suite_id`, `manifest_sha256` | Bind the record to the exact case specification before grading |
| `cohort` | A fixed manifest group: `agent_workflow`, `host_contract` or `human_approval` |
| `source` | Declared `scripted`, `live_provider` or `browser_recording`; never pool these as equivalent evidence |
| `runtime_source_sha256` | Collector-declared fingerprint of the code actually exercised, separate from the grader's hash |
| `models` | Declared reasoning/transcription model identities; required for non-scripted records with provider calls |
| `observations` | One record per observed case; omitted cases remain missing |
| `reviews` | Optional explicit quality verdicts, bound to the exact observed artifact hash |

Each observation records its case/artifact identity, HTTP and result status,
provider-call count, automatic-retry count, sanitized tool names/outcomes, goal
change and decision origin. `values` supports only bounded, named facts such as
billing days, normalized volume, coverage, transcript and required review. A
collector must obtain facts from the actual returned artifacts or independently
normalized evidence, rather than converting expectations into observed results.
This schema is deliberately narrower than an entire API response. Do not insert
credentials, raw prompts, provider errors, hidden reasoning or arbitrary tool data.
Provider-call bounds include every case stage and any proposal preparation, not just
the final answer. Scripted records count simulated provider-request attempts and
remain explicitly labeled scripted; these counts are not billed provider usage.

Cohort membership is fixed in the hashed manifest before collecting outcomes.
Agent workflows are reported separately from scripted adapter/fault cases and the
human-approved continuation. A run cannot supply observations from another cohort
or pick individual case IDs to score. Reports show the whole suite count and list
the other-cohort IDs explicitly. Host-contract collection must be declared scripted;
human-approval collection must be declared browser-recorded. Scripted observations
may also test agent-workflow contracts, but cannot be described as live quality.

Only one observation per case is accepted. Duplicate or unplanned cases fail
validation, rather than silently selecting the best attempt. The collector must
preserve failures and unknown outcomes. This version does not aggregate repeated
trials or choose a favorable rerun. Freeze a new explicit protocol before adding
repetitions or a confirmation split.

Each review contains `case_id`, the observation's `artifact_sha256`, `criterion`,
`verdict` (`pass`/`fail`), a pseudonymous `reviewer_id` and `source` (`human`,
`assistant` or `scripted_fixture`). Non-scripted records reject scripted fixture
reviews. Assistant assessments are permitted for development answers and explicitly
counted in `review_sources_declared`; they are not independent human evaluations.
The human-approval cohort still requires human review sources. Review the
actual answer against the manifest's rubric; matching a keyword is insufficient.
Unrequested, duplicate, stale-artifact or mismatched reviews are rejected.
Keep original answer/media artifacts private unless their publication is explicitly
authorized; this grader emits neither answers, fact values, transcripts nor reviewer IDs.

The collector and review metadata are **declared**, not independently attested by
this offline program. Hashes identify exact bytes and detect accidental mixing;
they do not prove a provider call, a human action, honest collection or correctness.

## Grade a collected record

```sh
PYTHONPATH=ml ml/.venv/bin/python evals/agent_contract.py --observations evals/reports/agent-observations.json --output evals/reports/agent-grade.json
```

Manifest expectations cover status, provider-call bounds, allowed tool outcomes
and counts, first-tool ordering where required, unchanged goals and exact typed
facts. Fact comparison is exact, including transcript spelling/case/punctuation;
it is not a word-error-rate or semantic transcript metric. Answer cases additionally
need every required quality criterion reviewed. Failures are retained even if
other criteria have not yet been reviewed.

Case outcomes are `passed`, `failed`, `pending_review` or `missing`. Every planned
case in the selected, predeclared cohort remains in the denominator. `case_pass_rate` stays null until no cases are
missing or awaiting review; once complete it is passed cases divided by all planned
cases in that cohort, including expected rejection and failure-recovery cases. A correct refusal
can pass a case without being a successful analysis. Workflow and modality coverage
in the plan do not establish measured performance in those categories.

Tool accounting is separate: successful permitted read outcomes and valid pending
approval requests are completions. A pending proposal is not an applied goal.
Expected denials, other errors, unconfirmed results and invalid/unexpected successful
outcomes remain in the attempt denominator. The tool completion fraction is null
when no tool attempts exist. Case failures for wrong ordering, extra calls or unsafe
actions remain failures even when another read returned successfully. This is trace
accounting, not an independent check of the tool's numerical correctness.

The human-approved continuation case has its own cohort and a manual gate. A scripted
run cannot collect it; it requires a browser-recording source and artifact-bound human reviews.
The agent must never approve its own proposal to fill that slot. Declaring the
required metadata alone does not attest that a human actually clicked approval.

Exit codes: `0` for a validated plan or complete all-passing grade, `1` for failed
or incomplete grading, and `2` for invalid inputs/options. JSON is bounded to 2 MiB
per input; unknown fields, duplicate keys, non-finite numbers and malformed identities
are rejected without echoing input contents. Invalid inputs do not yield a score.

## Bounded local collection

```sh
PYTHONPATH=ml ml/.venv/bin/python evals/collect_agent.py
PYTHONPATH=ml ml/.venv/bin/python evals/collect_agent.py --execute --cohort host_contract --output-dir evals/reports/host-run-1
```

The host cohort uses actual session-bound MCP reads and adapter permission checks,
plus an explicitly simulated slow transport for uncertain timeout behavior. It
does not use OpenAI or approve a goal. The timeout is fault injection, not an
observed provider outage.

The provider cohort requires the existing ignored root `.env.local` OpenAI
configuration, a verified frozen `ml/artifacts/detector-v1`, and these exact
locally maintained, synthetic fixtures:

| Fixture | SHA-256 | Content/provenance |
| --- | --- | --- |
| Fictional PNG, 70,588 bytes | `16249570f778a700bf9349040374dec0cf4d1036185a6bd6814926618240153f` | Clearly marked test bill: June 1–30 inclusive, 2026; 8.5 CCF; actual readings; USD 45.12 water and 30.00 sewer |
| Synthetic WAV, 95,568 bytes | `4cff39f74ce0858ea48925867c424a35aa1b52c18c90278aeca4c2d6ca19d1d3` | macOS Samantha text-to-speech, 16-kHz PCM16 mono: “What can these meter readings tell me about my water bill?”; no recorded customer audio |

The media bytes remain local and are not bundled with the repository; the paid
protocol cannot be reproduced without these matching fixtures. Other media require
a separately declared protocol before collection. Arbitrary customer uploads are
rejected by size/hash before provider configuration is loaded.

```sh
PYTHONPATH=ml ml/.venv/bin/python evals/collect_agent.py --execute --cohort agent_workflow --max-provider-calls 80 --fictional-image /absolute/path/fictional-water-bill.png --synthetic-wav /absolute/path/question.wav --output-dir evals/reports/provider-run-1
```

This executes all 19 fixed agent cases sequentially using local FastAPI ASGI,
real OpenAI requests and in-process MCP. It is not public-site/browser evidence.
Each case gets a fresh session which is revoked afterward. The cap (1–80 requests)
includes image, voice, topic classification, proposal preparation and continuation;
per-case caps also apply. Counts are recorded before awaiting SDK methods, including
uncertain attempts. SDK retries are zero; Responses use `store: false`. Audio uses
the existing transcription endpoint without a storage option or Files API upload.
The collector does not change hosted quotas or admission settings.

Outputs require a **new** directory inside ignored `evals/reports/` or
`.codex-local/`. An existing directory is a replay guard, including after failure;
never delete it to retry uncertain paid work. No automatic resume or rerun selects
a better outcome. Private JSON files use mode 0600 and newly created run directories
0700. Keep that directory private: it contains fictional answers and tool evidence.
Console output contains case IDs/status/counts only (plus existing sanitized service
logs). Provider exceptions are reduced to their class, not their message.

The collection plan records manifest/runtime/media/detector hashes before requests.
The runtime fingerprint covers Python application sources, the demo dataset and
collector; runtime changes during collection prevent finalization. Per-case artifacts
include returned answers, actual tool outcomes, provider model identities/timings and
sanitized staged responses. Opaque session/evidence/approval/response IDs and raw
provider reasoning are omitted. Partial staged artifacts and per-case observations
survive ordinary later-case failures. Normalized fact observations come from returned
tool artifacts and independently normalized input/candidates, never copied expected
facts. The original manifest remains unchanged after inspected outcomes.

`observations.json` and `grade-unreviewed.json` deliberately leave answer quality
pending. Read the artifacts against every requested rubric, then write a **new**
reviewed record with the exact artifact hashes and honest reviewer source. Do not
label assistant review as human. Grade that record with `agent_contract.py`.
Exit 1 for pending/failed grading is expected after initial provider collection;
it does not authorize an automatic rerun. Host and provider reports stay separate.
The manual human approval case is neither executed nor credited by this collector.

## Recorded development run

The [first collected run](../evals/baselines/agent-development-run-v1.json) retains
all first attempts from November 15, 2026: 19 agent workflows, 43 provider requests
under an 80-request cap, zero automatic retries, and 26 explicitly labeled assistant
quality verdicts. Fifteen agent cases passed and four failed. The separate three-case
host cohort passed; the human-approval cohort was not collected. These are inspected
development results, not independent human or held-out accuracy measurements.

Two answers inferred steadiness from aggregate statistics without reading a series.
The anomaly answer correctly withheld a diagnosis/probability but omitted frozen
model identity and synthetic training provenance required by its rubric. The rejection
continuation respected the rejected decision and left the goal unset, but the frozen
v1 manifest lists no allowed preparation tool while requiring an agent-created
proposal. Its actual preparation trace is retained as a protocol failure. Expectations
were not changed after observing these outcomes. Revise a future protocol explicitly
before collecting new runs; do not silently erase this failure or rerun for a better score.

The fictional image candidates, exact synthetic transcript and combined bill/meter
facts matched their predeclared checks in this run. That does not establish reliability
across other bill layouts, voices or repeated attempts. Raw artifacts remain local;
the public summary contains hashes, scoped counts, outcomes and limitations only.

## Verification

```sh
PYTHONPATH=ml ml/.venv/bin/python -m unittest discover -s ml/tests -p test_agent_evaluation.py -v
PYTHONPATH=ml:ml/tests ml/.venv/bin/python -m unittest -v test_agent_collection
```

The tests supply explicitly scripted records to check denominators, missing cases,
pending reviews, exact facts, tool ordering/budgets, retries, invalid tool success,
artifact binding, manual gates, strict input and exclusive report creation. They
exercise the grader, not the live agent. Collector tests additionally execute real
MCP host contracts and a mocked-SDK ASGI/tool flow, check uncertain request accounting,
caps, privacy, partial failures and replay guards. Cloud CI runs both without PyTorch.

Collected development runs and reviewed answers support only their declared scope.
Expand fixtures and add a separately frozen confirmation split before broader quality
claims. Do not relabel inspected development runs, assistant reviews or scripted host
tests as independent human, held-out, public-site or population accuracy measurements.
