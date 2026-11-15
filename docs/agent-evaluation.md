# Agent evaluation contracts

`evals/agent_contract.py` validates a versioned development-case manifest and grades
supplied observations offline. It does not run an agent, open a browser, transcribe
audio, upload images, make provider requests or approve proposals. A bounded
observation collector and authored media artifacts are separate follow-up work.

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
`verdict` (`pass`/`fail`), a pseudonymous `reviewer_id` and `source` (`human` or
`scripted_fixture`). Non-scripted records require human review sources. Review the
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

## Verification and next collection work

```sh
PYTHONPATH=ml ml/.venv/bin/python -m unittest discover -s ml/tests -p test_agent_evaluation.py -v
```

The tests supply explicitly scripted records to check denominators, missing cases,
pending reviews, exact facts, tool ordering/budgets, retries, invalid tool success,
artifact binding, manual gates, strict input and exclusive report creation. They
exercise the grader, not the live agent. Cloud CI also runs them without PyTorch.

A later collector must bind model snapshots, runtime/artifact hashes and all actual
attempts, generate or obtain the declared fictional media, preserve privacy, impose
explicit paid budgets, disable automatic retries and hand human approvals to the
user. Only then can collected runs and reviewed answers support scoped model-quality
results. Do not relabel these development specifications or scripted tests as live,
held-out, public-site or multimodal accuracy measurements.
