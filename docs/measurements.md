# Running measurements

All commands run from the repository root. Choose new output paths for every
declared run; existing reports and collection directories must be preserved,
including failures. The commands below describe available runners, not new results.

| Measurement | Runner | Main output |
| --- | --- | --- |
| End-to-end agent cases | `evals/collect_agent.py`, then `evals/agent_contract.py` | Case outcomes, pending/missing cases and `case_pass_rate` |
| MCP/tool execution | The same collector and grader, with separate cohorts | Attempts, successful reads, approval requests, denials, errors and `tools.completion_rate` |
| Model classification | `aquamind_ml.evaluate` or `aquamind_ml.confirm` | Confusion counts, precision, recall and F1 |
| FastAPI prediction latency | `aquamind_ml.benchmark` | Request/failure counts and p50/p95/p99 in milliseconds |

## Setup and prerequisites

Use the Node.js, pnpm and Python versions in the [README](../README.md#requirements).
Install the locked frontend and Python dependencies:

```sh
pnpm install --frozen-lockfile
python3 -m venv ml/.venv
ml/.venv/bin/python -m pip install -r ml/requirements-agent.txt
```

Offline case planning, scripted host checks, model evaluation and local latency
measurement need no OpenAI key or Redis service. Model operations require PyTorch.
Provider collection additionally needs `OPENAI_API_KEY` and `OPENAI_MODEL` in the
ignored root `.env.local`, the pinned synthetic media described below and the
verified `ml/artifacts/detector-v1` artifact. Never put credentials in reports.

Datasets, checkpoints and detector artifacts are generated locally and ignored by
Git. Follow [dataset export](development.md#exporting-a-dataset-for-python),
[training](development.md#pytorch-model) and
[detector freezing](development.md#frozen-detector-and-fresh-seed-confirmation)
when setting up a checkout that lacks them. Keep the exact source, dataset,
normalizer, model weights and artifact manifest together. Do not overwrite an
existing detector, recalibrate it on inspected test outcomes or silently replace
the model used in an earlier result.

## Agent and tool measurements

### Plan and exercise host contracts without paid calls

```sh
PYTHONPATH=ml ml/.venv/bin/python evals/collect_agent.py --protocol development-v2
PYTHONPATH=ml ml/.venv/bin/python evals/collect_agent.py --execute --protocol development-v2 --cohort host_contract --output-dir evals/reports/host-check-1
```

The first command only prints a plan. The second executes the declared scripted
host cohort through real local MCP/host contracts; it does not measure model
reasoning, call OpenAI or apply a goal. Its private directory contains the
collection plan, per-case artifacts, `observations.json` and
`grade-unreviewed.json`. Keep scripted host results separate from provider cases.

### Collect actual provider workflows when wanted

The [provider fixture table](agent-evaluation.md#bounded-local-collection) identifies
the exact fictional PNG and synthetic WAV hashes and sizes. These media are
operator-maintained local files, not repository assets. Without matching files,
the fixed multimodal protocol cannot run; arbitrary personal bills or recordings
cannot substitute for them. Existing fixtures may be reused as inputs for a new
declared development run, but an uncertain or failed collection must not be retried
by deleting its output directory. Other media require a separately declared
protocol, not an edit to an inspected historical run.

After verifying those prerequisites, an explicitly requested paid collection is:

```sh
PYTHONPATH=ml ml/.venv/bin/python evals/collect_agent.py --execute --protocol development-v2 --cohort agent_workflow --max-provider-calls 80 --fictional-image /absolute/path/fictional-water-bill.png --synthetic-wav /absolute/path/question.wav --output-dir evals/reports/provider-check-1
```

This is a whole declared cohort, not a one-request smoke test. The cap includes
topic checks, image extraction, voice transcription and all agent stages. SDK
retries are disabled. Collection uses the local FastAPI ASGI application and MCP
with real provider requests; it does not measure browser behavior or public-site
availability. It does not modify hosted quotas. Keep raw artifacts private.

Read every answer against its requested rubric. Create a **new**
`observations-reviewed.json` from the original record, adding the artifact-bound
reviews described in the [review contract](agent-evaluation.md#observation-contract).
Use honest `human` or `assistant` sources; never fill reviews with automatic passes.
Then grade the reviewed record:

```sh
PYTHONPATH=ml ml/.venv/bin/python evals/agent_contract.py --manifest evals/fixtures/agent-development-v2.json --observations evals/reports/provider-check-1/observations-reviewed.json --output evals/reports/provider-check-1/grade-reviewed.json
```

`case_pass_rate` stays `null` until all planned cases are observed and all required
quality reviews are present. Exit code 1 after collection can mean pending review
or a measured failure; inspect retained artifacts rather than rerunning requests.
Grading is offline and does not call the provider.

Tool completion is `(successful_reads + approval_requests) / attempts`. Denials,
errors, unconfirmed outcomes and invalid results remain in the attempt count.
An approval request is not an applied goal; tool completion is not answer
correctness. Host, provider and human-approval cohorts have separate denominators.
The collector cannot execute the positive human-approval cohort. A user must make
that decision through the trusted UI; manually recorded observations must satisfy
the grader's browser-recorded/human-review contract.

Historical confirmation protocols pin their application and artifacts and have
first-attempt receipts. They are retained evidence, not commands to replay against
current code. Do not change old pins or delete receipts to make them run again.
See [the evaluation guide](agent-evaluation.md) for contracts and existing results.

## Model precision, recall and F1

For a completed baseline checkpoint and its original training dataset:

```sh
PYTHONPATH=ml ml/.venv/bin/python -m aquamind_ml.evaluate --dataset ml/data/generated/meter-experiment.json --checkpoint ml/artifacts/lstm-baseline-v1 --output evals/reports/reconstruction-check-1.json
```

This evaluates the reconstruction-MSE baseline, not the calibrated served
detector. It verifies weights/dataset/normalization, selects a threshold on
validation, then emits `validation`, `test` and per-scenario results. Each metric
block contains `count`, `tp`, `fp`, `fn`, `tn`, `precision`, `recall` and `f1`.
Test outcomes must not drive threshold or training changes.

For the frozen served detector, use a disjoint synthetic seed export and a new
output report. This example declares a new input range; it does not replay the
historical confirmation report:

```sh
pnpm data:export --seed-start 20000 --seed-count 30 --output ml/data/generated/detector-check-1.json
PYTHONPATH=ml ml/.venv/bin/python -m aquamind_ml.confirm --dataset ml/data/generated/detector-check-1.json --detector ml/artifacts/detector-v1 --output evals/reports/detector-check-1.json
```

The runner rejects development-seed overlap and does not refit the detector. Its
`test` and `by_scenario` blocks contain metrics, with model/dataset/weight hashes
and `refitted: false`. Thirty seeds are a bounded execution example, not a
representative study or a required sample size. Inspecting outcomes makes them
development evidence for any subsequent changes.

Both workflows measure daily synthetic windows. They do not establish real leak
diagnosis, unseen-household generalization or interval localization. Imported user
CSV readings are not automatically scored by this model. Experimental AMPds2
workflows remain separate; see the [dataset guide](datasets/ampds2.md).

## FastAPI latency

With the exported dataset and verified frozen detector available:

```sh
PYTHONPATH=ml ml/.venv/bin/python -m aquamind_ml.benchmark --dataset ml/data/generated/meter-experiment.json --detector ml/artifacts/detector-v1 --requests 24 --concurrency 2 --warmup 2 --port 8002 --output evals/reports/http-check-1.json
```

The runner starts a local Uvicorn server, checks readiness, performs warmup, times
actual HTTP requests to `/v1/anomaly/predict` and closes its server afterward. Port
8002 must be unused. It records successful/failed request counts, error types,
per-attempt samples, throughput, model version, environment and warmup/concurrency.
`latency` contains nearest-rank `p50_ms`, `p95_ms`, `p99_ms` over successful requests;
`all_attempt_latency` also includes failures. No slow samples are discarded, no
failed request is retried, and any measured request failure produces exit code 1.

Twenty-four requests only check execution. Choose and record an appropriate larger
sample when making performance claims. This measures the full warm local FastAPI
HTTP path, not just a Python function. It excludes startup/model loading, public
network latency and free-host idle wake. It is not a hosted latency guarantee.

## Bounded runner validation

```sh
PYTHONPATH=ml:ml/tests ml/.venv/bin/python -m unittest -v test_evaluate test_benchmark test_agent_evaluation test_agent_collection
```

These tests check metric denominators, percentile calculation, failure accounting,
training/evaluation provenance, collection budgets, review binding and approval
boundaries. They include scripted and mocked inputs; passing them validates runner
behavior, not model accuracy. Existing scoped measurements are recorded separately
under `evals/baselines/`. Do not pool those results or relabel them as new runs.
