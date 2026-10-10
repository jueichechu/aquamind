# AquaMind

AquaMind is a household water-intelligence project. The current implementation is a local Next.js demo backed by a deterministic synthetic water-meter simulator.

## Run locally

Use Node.js 22 or newer and pnpm 12.5.1 (the version pinned in `package.json`). From the repository root:

```sh
pnpm install --frozen-lockfile
pnpm dev
```

Open `http://localhost:3000` for the landing page or `http://localhost:3000/demo` for the interactive dashboard. Stop the development server with `Ctrl+C` in its terminal. The current demo needs no API keys, database, or external service credentials.

## Current demo

The four scenario buttons update the usage summary, chart, anomaly state, explanatory text, and synthetic weather context:

- **Normal:** ordinary household fixture usage without injected anomalies.
- **Overnight leak:** constant extra flow from 01:15 to 06:00 on the final simulated day.
- **Running toilet:** intermittent refill events during the final day's overnight and early-morning hours.
- **Irrigation after rain:** extra watering with recent rainfall context, modeled as a conservation opportunity rather than evidence of a physical leak.

The chart shows the final day's 96 readings. Amber bars mark simulator-defined anomalous intervals; the expandable table provides interval volumes and excess usage.

All meter readings and weather context are **synthetic**. Dashboard anomaly flags are injected by the simulator, not predicted by a trained model. The assistant panel is an inactive placeholder. A PyTorch autoencoder, training commands, local FastAPI inference, and read-only MCP anomaly/meter/utility/weather tools are implemented separately; LLMs, image analysis, and voice interaction are not implemented yet. The landing-page preview is illustrative and is separate from the generated demo dashboard.

## Water-data model

The public API lives in `apps/web/src/lib/water/index.ts`:

```ts
import { generateHouseholdDataset } from "@/lib/water";

const dataset = generateHouseholdDataset("overnight-leak", 42);
```

The same scenario and seed reproduce the same dataset. The default seed is `42`. Each dataset contains seven days beginning June 15, 2026 at midnight UTC: 672 readings at 15-minute intervals, with gallons, interval-average flow, fixture attribution, anomaly flags, and excess gallons. The simulated household has three occupants and includes baseline usage, showers, toilets, faucets, dishwasher and washer cycles, and occasional irrigation.

Summary calculations use the final simulated day as “today” and the preceding six days' mean daily volume as the baseline. Percentage change is calculated before display rounding. Excess gallons represent injected anomaly volume, not the difference from the historical baseline. Peak excess flow is the maximum anomalous interval's excess gallons divided by 15 minutes; it is not a live flow measurement. All displayed meter times use UTC.

These are transparent simulation assumptions, not a scientifically validated household model or an evaluated leak detector.

## Preparing meter sequences

`createMeterWindows(dataset.readings)` produces seven non-overlapping 96-reading windows by default. Optional `windowSize` and `stride` arguments allow shorter or overlapping sequences. Incomplete tails are dropped, and missing, duplicate, or out-of-order intervals and invalid flow rates are rejected. Window timestamps identify the first and last included readings.

Each window contains only interval-average flow values in `flowRatesGpm`, with synthetic `hasAnomaly` ground truth stored separately. This label includes irrigation conservation opportunities; it must not be treated as a physical-leak label. Values are not normalized yet. Before training, split households/seeds into train, validation, and test groups **before** creating windows, keep scenario variants of the same seed together, and fit any normalization only on training data to avoid evaluation leakage.

`splitHouseholdSeeds(seeds)` returns sorted, deduplicated `train`, `validation`, and `test` seed lists. A fixed integer hash assigns approximately 70%/15%/15%; assignments stay stable when seeds are reordered or added. Small collections can have empty splits. Only unsigned 32-bit integers are accepted, avoiding aliases introduced by the simulator's seed coercion.

```ts
import { splitHouseholdSeeds } from "@/lib/water";

const split = splitHouseholdSeeds(Array.from({ length: 1000 }, (_, seed) => seed));
// Generate every scenario for a seed within that seed's assigned split.
```

Persist the returned seed lists with future experiment artifacts. All current seeds still use the same household assumptions, so holding out seeds tests unseen simulated usage, not generalization to real households.

This is data preparation for future sequence-model experiments, not a trained model or an evaluation result.

`createMeterExperimentDataset(seeds)` assembles JSON-serializable daily sequences using those seed splits. Training contains seven normal days per training seed. Validation and test each contain seven normal days plus the final day of each of the three anomaly scenarios per seed; shared history is included only once. The output records the seed manifest, schema version, interval length, and synthetic source. Small seed collections may yield empty splits, which a training workflow must check before fitting or evaluating.

Only `flowRatesGpm` is a model input. Seed, scenario, timestamps, `hasAnomaly`, and `hasLeak` are provenance or synthetic ground truth, never input features. `hasLeak` covers the injected overnight leak and running toilet; irrigation after rain remains an anomaly/conservation opportunity but is not a physical leak. No normalization is applied. Fit future preprocessing on training data only. Scenario variants within each evaluation split are correlated, and the scenario mix is a designed benchmark rather than an estimate of real-world leak prevalence.

## Exporting a dataset for Python

From the repository root, run:

```sh
pnpm data:export
# Optional: choose a seed range and a different artifact path.
pnpm data:export --seed-start 1000 --seed-count 1000 --output ml/data/generated/alternate.json
```

The default exports seeds 0–999 to the ignored `ml/data/generated/meter-experiment.json`. The command compiles the existing TypeScript generator using the workspace TypeScript dependency; it does not reimplement the simulator in Python or require new dependencies. It rejects empty splits, invalid seed ranges, and existing output files. Custom output paths are relative to the repository root; keep generated data in the ignored directory. Export is in memory and limited to 10,000 seeds per run.

The JSON contains the dataset schema version, synthetic disclosure, seed assignments, and raw sequences with separate labels. Standard Python can read it with `json.load`. The command prints the SHA-256 of the exact file bytes and window counts for each split. Identical source code and seed arguments produce identical bytes, without timestamps or machine-specific paths inside the artifact. Record the Git commit, export arguments, and printed checksum alongside future experiment results. This export is not a trained model or an evaluation metric.

```sh
python3 -c 'import json; from pathlib import Path; d = json.loads(Path("ml/data/generated/meter-experiment.json").read_text()); print({s: len(d[s]) for s in ("train", "validation", "test")})'
```

## Python loading and normalization

The dependency-free Python module in `ml/aquamind_ml/data.py` loads schema-v1 exports, validates nonempty disjoint seed groups, 96-value sequences, UTC window boundaries, and synthetic labels, and rejects anomalous training windows. Use Python 3.12 or newer. From the repository root:

```sh
PYTHONPATH=ml python3 -m unittest discover -s ml/tests -v
```

For a Python script run with `PYTHONPATH=ml`:

```python
from dataclasses import asdict
from aquamind_ml.data import FlowNormalizer, load_dataset

dataset = load_dataset("ml/data/generated/meter-experiment.json")
normalizer = FlowNormalizer.fit(dataset)
train_features = normalizer.transform(dataset.train)
validation_features = normalizer.transform(dataset.validation)
test_features = normalizer.transform(dataset.test)
parameters = asdict(normalizer)  # JSON-serializable; save with future model artifacts.
```

The global mean and population standard deviation use only training flow values. Constant training data uses a scale of one. The same frozen parameters apply to every split without clipping; held-out outliers may exceed the training range. Transform results contain only numerical flow features, with labels and provenance retained separately in the immutable loaded windows. Parameters include the source file's SHA-256 and training value count. This module does not train a model or calculate evaluation metrics.

## PyTorch model

`ml/aquamind_ml/model.py` implements an LSTM autoencoder: a 32-unit encoder compresses a sequence into an 8-value latent vector; an LSTM decoder reconstructs the flow sequence from that vector. Input and output shapes are `[batch, time, 1]` with normalized float32 flow values. The decoder does not receive the original observations. `reconstruction_errors` returns squared errors per interval and mean squared error per window, not leak probabilities or classifications. No threshold or validated production model exists yet.

Create an isolated environment and run all Python tests from the repository root:

```sh
python3 -m venv ml/.venv
ml/.venv/bin/python -m pip install -r ml/requirements-mcp.txt
PYTHONPATH=ml ml/.venv/bin/python -m unittest discover -s ml/tests -v
```

The model tests check gradients, sequence reconstruction learning on a simple fixture, and saved-weight round trips. These tests do not establish held-out leak accuracy.

Train on the exported dataset:

```sh
PYTHONPATH=ml ml/.venv/bin/python -m aquamind_ml.train --dataset ml/data/generated/meter-experiment.json --output ml/artifacts/lstm-v1 --epochs 20
```

Training uses one CPU thread, seed 42 by default, deterministic PyTorch algorithms, Adam, and shuffled normal training windows. The saved checkpoint is the epoch with lowest normal-validation reconstruction MSE; test windows are never transformed or scored during training. Validation anomalies are reserved for future threshold calibration. The command refuses an existing output directory. It writes `weights.pt` and then `training.json`, the completion marker containing configuration, normalization, epoch losses, selected epoch, environment, and dataset/source/weight checksums. Keep both files together. Incomplete directories without the report are not usable artifacts.

Use the same source, dataset, configuration, and environment to reproduce a run. Cross-platform or cross-version bitwise reproducibility is not promised. Training tests verify identical weights on repeated CPU runs and independence from test windows. Reconstruction loss alone does not establish held-out leak-detection accuracy.

Calibrate and evaluate a completed training run:

```sh
PYTHONPATH=ml ml/.venv/bin/python -m aquamind_ml.evaluate --dataset ml/data/generated/meter-experiment.json --checkpoint ml/artifacts/lstm-v1 --output evals/reports/lstm-v1.json
```

The evaluator verifies dataset and weight checksums and training-only normalization. It selects a daily-window reconstruction-MSE threshold by maximizing physical-leak F1 on validation windows, using the higher threshold to break ties and `score >= threshold` for classification. Only then does it score test windows. Overnight leaks and running toilets are positives; normal days and irrigation conservation opportunities are negatives. Undefined precision/recall/F1 denominators produce zero.

The generated JSON records validation and test precision/recall/F1, confusion counts, per-scenario breakdowns, individual test predictions, the frozen threshold, a weight-derived model version, and training provenance. Output files cannot overwrite earlier reports. The report is synthetic seed-holdout evidence, not field validation, a plumbing diagnosis, or an interval-level detection benchmark. Validation results are optimistic because validation selects both the checkpoint and threshold. Once inspected, test results must not drive hyperparameter selection; use validation for development and reserve fresh unseen seeds for a later confirmatory evaluation.

The first 20-epoch baseline is recorded in the generated [baseline summary](evals/baselines/lstm-v1.json): test precision 0.2420, recall 0.6905, and F1 0.3583 across 1,470 daily windows. This baseline does **not** provide adequate leak discrimination. There are 636 false positives and 91 missed leak windows. Treat this as an initial measured baseline requiring improvement, not a validated leak detector. Reproduction commands in the summary assume fresh output paths; full per-window reports and weights remain in ignored local artifact directories.

### Validation-only scoring development

```sh
PYTHONPATH=ml ml/.venv/bin/python -m aquamind_ml.validate_scoring --dataset ml/data/generated/meter-experiment.json --checkpoint ml/artifacts/lstm-baseline-v1 --output evals/reports/calibrated-validation.json
```

This compares daily MSE with positive standardized reconstruction residuals, using the same trained LSTM weights. For each of 96 daily slots, calibration fits residual mean and population standard deviation on normal training windows only. The standard deviation has a fixed 0.01 floor in normalized-flow units. The daily score is the mean squared positive standardized residual. This reduces the influence of naturally variable fixture-use periods without using scenario labels as input features. Windows must align to midnight UTC; adapting the daily baseline to local household schedules remains future work.

The generated [validation comparison](evals/baselines/calibrated-validation.json) reports F1 improving from 0.3545 to 1.0000 on 1,440 validation windows. This is **development evidence, not held-out accuracy**. Threshold selection uses validation labels, all seeds share simple fixed simulator schedules, and the test split is never scored by this command. The prior held-out result remains unchanged. Freeze the scoring method, calibration, and threshold before a confirmatory evaluation on fresh unseen seeds.

### Frozen detector and fresh-seed confirmation

After reproducing the baseline training run, freeze its calibrated scoring parameters before generating confirmation data:

```sh
PYTHONPATH=ml ml/.venv/bin/python -m aquamind_ml.detector --dataset ml/data/generated/meter-experiment.json --checkpoint ml/artifacts/lstm-baseline-v1 --output ml/artifacts/detector-v1
pnpm data:export --seed-start 10000 --seed-count 1000 --output ml/data/generated/confirm-v1.json
PYTHONPATH=ml ml/.venv/bin/python -m aquamind_ml.confirm --dataset ml/data/generated/confirm-v1.json --detector ml/artifacts/detector-v1 --output evals/reports/confirm-v1.json
```

The detector directory contains `weights.pt` and `detector.json`: model dimensions, training-only normalization and residual calibration, the validation-selected threshold, development seed exclusions, and source/weight checksums. Its version hashes the manifest, so changing calibration or the threshold also changes the version. `FrozenDetector.predict` loads these parameters and never fits them; it uses flow values and UTC window alignment, not scenario or anomaly labels. Keep both files together. This is a local inference interface, not yet a deployed API.

Confirmation rejects overlap with any original training, validation, or previously inspected test seed. Only the new export's test split is scored. The generated [confirmation summary](evals/baselines/confirm-v1.json) records **precision 1.0000, recall 0.9897, and F1 0.9948** across **1,450 daily windows from 145 unseen synthetic seeds**, using a frozen threshold of 7.725719451904297. There were 287 true positives, 1,160 true negatives, no false positives, and three false negatives. No refitting occurred.

This supports a PyTorch LSTM autoencoder **with training-calibrated reconstruction scores on a synthetic seed holdout**. It does not demonstrate generalization to different household schedules or real-world meters. Interpret these results only as synthetic evaluation, with the dataset and protocol qualifications above. Earlier baseline results remain recorded for comparison; confirmation results must not be used to retune this detector.

## Local inference API

After creating `ml/artifacts/detector-v1`, install the API dependencies and start the server from the repository root:

```sh
ml/.venv/bin/python -m pip install -r ml/requirements-api.txt
PYTHONPATH=ml AQUAMIND_DETECTOR_PATH=ml/artifacts/detector-v1 ml/.venv/bin/python -m uvicorn aquamind_ml.api:app --host 127.0.0.1 --port 8001
```

Open `http://127.0.0.1:8001/docs` for the typed API contract. `GET /health` reports process liveness; `GET /ready` returns 503 if the model could not load. `POST /v1/anomaly/predict` accepts `start_timestamp` (midnight UTC) and `flow_rates_gpm` (exactly 96 finite numeric values from 0 to 1,000 GPM, representing consecutive 15-minute intervals). Unknown fields, numeric strings, booleans, negative values, and misaligned windows are rejected. Labels are neither required nor accepted.

The response includes `score`, `is_leak`, `threshold`, `model_version`, `request_id`, and synthetic training-data disclosure. Scores are calibrated reconstruction errors, not probabilities. They classify a whole day and do not localize individual leak intervals. Model loading occurs once at startup; inference uses one PyTorch CPU thread and serialized model access. Validation errors omit raw input, and structured log events contain identifiers/status/timing or error types, not meter readings. Responses include `X-Request-ID` and disable caching.

This service is local-only at this stage. Public request-size/rate limits and deployment configuration remain future work. No cross-origin browser access is enabled, and the dashboard is not yet connected to this API. No API keys are needed for local inference.

### HTTP latency benchmark

```sh
PYTHONPATH=ml ml/.venv/bin/python -m aquamind_ml.benchmark --dataset ml/data/generated/meter-experiment.json --detector ml/artifacts/detector-v1 --requests 1000 --concurrency 4 --warmup 50 --output evals/reports/api-latency-v1.json
```

The command starts and stops its own Uvicorn process on loopback port 8002 (change with `--port`). It waits for readiness, sends sequential warm-up requests, then uses concurrent HTTP clients to submit one 96-reading window per request to `POST /v1/anomaly/predict`. Payloads cycle through validation windows in export order. Timings cover the client POST call through receipt of the full response, including JSON encoding, TCP, server validation, queueing, inference, and response serialization. Startup/model loading and client-side response-schema checks are outside the latency timer. Server JSON request logging remains enabled, with output captured to a temporary file.

Percentiles use nearest rank. The report records all timed samples, failures without retries, warm-up count, concurrency, throughput, source hashes, model version, and environment. Failures cause a nonzero exit after the report is saved; successful-request and all-attempt percentiles are reported separately. Existing report files cannot be overwritten.

The generated [local latency baseline](evals/baselines/api-latency-v1.json) measured **p50 7.85 ms, p95 15.36 ms, p99 38.62 ms**, with **1,000/1,000 successful requests**, concurrency 4, and 50 warm-up requests. This supports a local warm-server p95 below 100 ms through the actual FastAPI HTTP path. It does not establish deployed internet latency, cold-start behavior, or performance on different hardware; client and server shared the same macOS ARM machine with one server worker and one PyTorch CPU thread.

## Local MCP tools

Install `ml/requirements-mcp.txt` to use the official MCP Python SDK 2.3.0. The server uses the SDK's `MCPServer` and stdio transport. From the repository root, an MCP host can launch:

```sh
PYTHONPATH=ml AQUAMIND_DETECTOR_PATH=ml/artifacts/detector-v1 AQUAMIND_MCP_SCOPES=anomaly:read ml/.venv/bin/python -m aquamind_ml.mcp_server
```

The tool `detect_water_anomaly` accepts a `request` object with the same `start_timestamp` and `flow_rates_gpm` fields as the HTTP API. Its advertised input and output schemas are generated from the shared Pydantic contracts. It returns real frozen-model predictions with model version, threshold, request ID, and synthetic-training disclosure. Tool annotations identify it as read-only, non-destructive, and closed-world. Standard output is reserved for MCP protocol messages.

Scopes are fixed by the trusted host's startup configuration; an empty `AQUAMIND_MCP_SCOPES` denies calls. Tool arguments cannot grant `anomaly:read`, `meter:read`, `utility:read`, `weather:read`, or `goals:write`. This process-level permission boundary is for local stdio use, not remote user authentication. Model failures produce tool errors, never fabricated predictions. The goal tool below creates an approval proposal; goal execution is reserved for a separate trusted host decision.

Tests negotiate an actual MCP session with a subprocess, discover the tool and output schema, and compare its result with direct PyTorch inference. Additional protocol tests cover denied permissions, malformed requests, and unavailable models. These are development checks, not an end-to-end agent evaluation.

### Meter reads

`get_meter_series` and `get_meter_summary` require the separate `meter:read` scope. They read a host-selected snapshot from the existing TypeScript simulator export; they do not regenerate data in Python. To enable them, run `pnpm data:export` and launch:

```sh
PYTHONPATH=ml AQUAMIND_METER_DATASET_PATH=ml/data/generated/meter-experiment.json AQUAMIND_MCP_SCOPES=meter:read ml/.venv/bin/python -m aquamind_ml.mcp_server
```

Supply a window identity from the export, for example the first normal training day for seed 0:

```json
{"request":{"seed":0,"scenario_id":"normal","start_timestamp":"2026-06-15T00:00:00Z"}}
```

Both tools return the synthetic-source disclosure, dataset SHA-256, window identity, exclusive end time, reading count, total gallons, mean GPM, and peak fifteen-minute average GPM. Series also returns the 96 readings in chronological order. Gallons are calculated as the sum of average GPM × 15 minutes. Simulator anomaly/leak labels are omitted; a usage summary is not a model diagnosis. UTC timestamp spellings normalize to the same instant.

The dataset is loaded once at startup. Missing windows, absent files, and invalid exports produce tool errors. Callers cannot select filesystem paths. Grant both scopes as `anomaly:read,meter:read` and configure both artifact paths to enable model inference alongside meter reads. These are local synthetic-window tools; household authentication, window discovery, and dashboard/agent integration are not implemented yet. The export's test split remains ML evaluation data, not an independent agent benchmark.

### Utility estimates

Three read-only tools require `utility:read`: `get_utility_rate`, `estimate_water_cost`, and `estimate_conservation_savings`. Enable them with `AQUAMIND_MCP_SCOPES=utility:read` (or add that scope to the comma-separated list). They need no model artifact, dataset, or API key.

The versioned `demo-flat-usd-v1` rate is an **illustrative assumption of $5.00 per 1,000 gallons**, not a real utility tariff. Every result discloses the rate and excludes sewer, fixed fees, taxes, and tiered pricing. Money is returned as a decimal string, rounded half-up to cents after calculation.

Example tool arguments:

```json
{}
```

for `get_utility_rate`, and:

```json
{"request":{"gallons":1000}}
```

for `estimate_water_cost` (returns $5.00). To project savings:

```json
{"request":{"baseline_daily_gallons":200,"proposed_daily_gallons":150,"days":30}}
```

`estimate_conservation_savings` returns 1,500 saved gallons and $7.50 estimated water-only savings. It assumes the 50-gallon daily reduction persists for all 30 days; this is not measured or guaranteed savings. Inputs are caller-supplied, so an agent must obtain meter evidence separately and explain proposed reductions. Volumes must be finite non-negative numbers at most 1,000,000 gallons; durations are integer days from 1 to 366; proposed usage cannot exceed baseline usage. Caller-supplied rates and extra fields are rejected. These tools do not change goals, alerts, or household equipment. Real provider tariffs and billing integration remain unimplemented.

### Synthetic weather context

`get_weather_context` requires `weather:read`. Enable it with `AQUAMIND_MCP_SCOPES=weather:read` (or add the scope to the comma-separated list). Example arguments:

```json
{"request":{"scenario_id":"irrigation-after-rain"}}
```

The response includes 0.68 inches of scenario rainfall over the prior 24 hours, 69°F, `source: "synthetic"`, and the shared snapshot's SHA-256. These are static scenario assumptions, not observations, current weather, or a forecast for a real location/date. Rainfall context alone does not establish whether irrigation is needed.

The frontend and Python tool both read `apps/web/src/lib/water/scenario-weather.json`; there is no duplicate Python weather table. The server loads this repository-relative snapshot once at startup. Keep it available when packaging the server. A missing or malformed snapshot returns an unavailable tool error; unknown scenarios and extra request fields are rejected. No provider credentials are needed for this synthetic pathway. Live weather integration remains future work.

### Conservation-goal approval boundary

`set_conservation_goal` requires `goals:write` and accepts `{"request":{"daily_gallons":150}}`. It returns an `approval_required` proposal containing an opaque approval ID, exact arguments, human-readable summary, expected goal revision, and a ten-minute expiry. **This response does not mean the goal was set.** Invalid values and extra arguments such as `approved: true` are rejected.

An embedded trusted host supplies one `GoalApprovals` instance to `create_server(..., goal_approvals=store)`. After displaying the exact proposal and receiving a human choice, the host calls `store.decide(approval_id, "approve")` or `"reject"`. There is deliberately no MCP approval/execution tool, so the agent cannot grant itself approval. The host must bind each store to its own user/session; these Python methods are not authentication endpoints.

Approval atomically sets the session's goal. Rejection and expiry do not change it. Retries return the original outcome without executing again. If another goal was approved since a proposal was created, the stale proposal returns `conflict` and requires a new proposal and approval. Each session retains at most 100 proposal/outcome records; reaching capacity rejects further proposals. State is in memory and disappears on restart.

This is the tested backend approval boundary, **not a completed human-approval product flow**. The standalone stdio server can propose but has no approval UI or decision transport. The frontend Approve/Reject controls, persistent goals/audit storage, and agent continuation with the decision result remain to be implemented. No database or API credentials are needed for this local implementation.

### Session-bound approval API

FastAPI now exposes anonymous, ephemeral demo sessions and human-decision endpoints:

- `POST /v1/sessions`: returns a random `session_token` valid for one hour.
- `GET /v1/approvals/{approval_id}`: reviews the exact stored proposal and remaining expiry.
- `POST /v1/approvals/{approval_id}/decision`: accepts only `{"decision":"approve"}` or `{"decision":"reject"}`.
- `GET /v1/goals/current`: returns the session's approved goal, or null.
- `DELETE /v1/session`: revokes the session credential.

All except creation require `Authorization: Bearer <session_token>`. Responses use `Cache-Control: no-store`; request logs omit credentials and bodies. A different session receives 404 for a proposal, and missing, expired, or revoked credentials receive 401. Browser cookies are not used and cross-origin access is not enabled. Use HTTPS and a same-origin host/proxy when connecting the browser; keep the credential out of agent prompts, tool arguments, traces, and URLs.

The trusted host obtains the session store via `app.state.sessions.approvals(token)` and injects it into `create_server(..., goal_approvals=store)`. There is no HTTP endpoint that lets the agent grant itself consent. The decision endpoint is for the human UI; it must never be registered as an agent tool. Bearer possession authenticates the demo session, not a real-world identity or proof of a physical click. The host must stop using cached stores/MCP servers when a session expires or is revoked.

The API retains at most 100 sessions, evicts expired sessions on creation, and returns 503 at capacity. State is process-local: use one worker for this local prototype. Production rate limiting, shared storage, browser approval UI, and agent/session lifecycle integration remain outstanding. Tests run an actual MCP proposal followed by HTTP review/approval and cover cross-session denial, rejection, malformed decisions, expiry, revocation, and capacity recovery.

## Checks

Run from the repository root:

```sh
pnpm test
pnpm lint
pnpm typecheck
pnpm build
```

Tests use Vitest and cover time spacing, reproducibility, non-negative volumes, fixture attribution, scenario patterns, summary calculations, and scenario metadata isolation.

The build uses Next.js's default Turbopack bundler. If a restricted environment blocks Turbopack worker ports, the alternative production build is:

```sh
pnpm build --webpack
```

The existing `next/font` configuration fetches Google Fonts during builds, so an uncached build needs network access. After building, run `pnpm --filter web start` to serve the production app.

## Code layout

- `apps/web/src/app/page.tsx`: landing page.
- `apps/web/src/app/demo/`: demo shell and interactive household dashboard.
- `apps/web/src/lib/water/`: domain types, scenario definitions, generator, and tests.

The repository is a pnpm workspace. Python data preparation, the LSTM autoencoder, training, evaluation, and local FastAPI serving live in `ml/`. The current runnable web application is `apps/web`.
