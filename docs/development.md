# Development reference

Setup commands in this guide run from the repository root. See the [README](../README.md) for the quick start, required configuration and current limitations.

## Water-data model

The public API lives in `apps/web/src/lib/water/index.ts`:

```ts
import { generateHouseholdDataset } from "@/lib/water";

const dataset = generateHouseholdDataset("overnight-leak", 42);
```

The same scenario and seed reproduce the same dataset. The default seed is `42`. Each dataset contains seven days beginning June 15, 2026 at midnight UTC: 672 readings at 15-minute intervals, with gallons, interval-average flow, fixture attribution, anomaly flags, and excess gallons. The simulated household has three occupants and includes baseline usage, showers, toilets, faucets, dishwasher and washer cycles, and occasional irrigation.

Summary calculations use the final simulated day as “today” and the preceding six days' mean daily volume as the baseline. Percentage change is calculated before display rounding. Excess gallons represent injected anomaly volume, not the difference from the historical baseline. Peak excess flow is the maximum anomalous interval's excess gallons divided by 15 minutes; it is not a live flow measurement. All displayed meter times use UTC.

These are transparent simulation assumptions, not a scientifically validated household model or an evaluated leak detector.

## Manual bill normalization

`ml/aquamind_ml/bills.py` adds the Python contract for manually entered aggregate bills, available through a session-gated HTTP endpoint and the `/analyze` form. There is no upload/OCR or persistence yet. Optional bill-only AI questions are described below. Entries contain a start date, an **exclusive** end date, usage and an explicit unit. Supported units are `us_gallons` (US liquid gallons), `ccf` (100 cubic feet), `cubic_meters`, and `liters`. Ambiguous `gallons`, imperial gallons, unit suffixes and thousands separators are rejected.

Example from a Python process started with `PYTHONPATH=ml`:

```python
from aquamind_ml.bills import ManualBill, normalize_bill

bill = ManualBill.model_validate_json('''{
  "period_start": "2026-06-01",
  "period_end_exclusive": "2026-07-01",
  "usage": "8.5",
  "usage_unit": "ccf",
  "water_charge": "45.12",
  "currency": "USD"
}''')
result = normalize_bill(bill)
print(result.model_dump_json(indent=2))
```

The result preserves the entry and reports billing days, total US gallons and US gallons/day as six-decimal strings. Calendar subtraction handles leap years without timezone assumptions; periods must cover 1–366 days. Usage must be non-negative and at most 1,000,000 normalized US gallons, with up to six input decimal places. Decimal arithmetic uses a local 40-digit context and half-up output rounding; daily volume is calculated before rounding the total.

Optional `water_charge` and `sewer_charge` accept non-negative amounts up to 1,000,000 with at most two decimal places. Charges require an explicit `currency: "USD"`; currency conversion, credits and other currencies are not supported. Missing charges stay unknown. A water/sewer subtotal is returned only when both line items are supplied, including explicit zero amounts; it is not a verified invoice total or a utility tariff. The illustrative demo rate is never applied to these entries.

Results disclose `source: "manual_entry"`, `evidence_level: "bill_only"`, and limited confidence for diagnostic conclusions. Values are unverified. One bill does not establish a usage trend, precise leak timing or a fixture diagnosis, and no leak score, tariff or savings prediction is produced. No account number, address, original document or free-text bill content is collected by this contract.

Conversions use the [NIST Handbook 44 unit definitions](https://www.nist.gov/system/files/documents/2024/01/14/NIST%20HB%2044%202024%20Appendix%20C%20General%20Tables%20of%20Units%20of%20Measurement.pdf): 1 US liquid gallon = 231 cubic inches = 3.785411784 liters, and 1 cubic foot = 1728 cubic inches. [EPA defines CCF as 100 cubic feet](https://www.epa.gov/watersense/understanding-your-water-bill); the implementation uses the exact ratio `172800 / 231` gallons per CCF rather than rounding the factor to 748. The supported unit labels do not imply that a utility's bill itself has this precision.

`POST /v1/bills/normalize` accepts the flat JSON entry shown above with the bearer credential from `POST /v1/sessions`. It returns the normalized result plus a `request_id` matching the backend's `X-Request-ID` header. The request and response schemas are included in OpenAPI. The same-origin web relay exposes this route at `/api/aquamind/v1/bills/normalize`, forwarding the bearer credential without browser cookies.

The endpoint requires `application/json` and limits the actual streamed UTF-8 body to 1 KiB. Duplicate keys, unknown fields, invalid dates, unsupported units and non-finite numbers are rejected. Missing, expired or revoked sessions return 401; oversized bodies return 413, unsupported content types 415, and invalid entries 422 with a generic error that does not echo the submitted values. Session liveness is checked again before returning a bill. Responses use `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`, and no cross-origin access is enabled.

Normalization is stateless: the entered fields return only to the caller, with no bill history, changes to conservation goals, model calls or bill values in application request logs. It works with the agent and detector disabled and needs no new API keys. The `/analyze` form uses its own mounted, in-memory session client and stays independent of the synthetic demo. It requires explicit units and exclusive end dates, preserves decimal strings, keeps missing charges distinct from zero, and requires explicit USD for entered charges. Result parsing checks the evidence labels and echoed bill against the submitted entry. Editing a field or clearing the form removes the previous result; invalid entries, expired sessions and unavailable services show bounded errors without echoing backend details or automatically retrying. No browser storage, assistant calls or model configuration is used for bill normalization. The page includes labeled example values that require an explicit calculation. After calculation, the optional bill-only question form requires a separate sharing checkbox and explicit submission.

Run the bill checks without credentials or a listening server:

```sh
PYTHONPATH=ml ml/.venv/bin/python -m unittest discover -s ml/tests -p test_bills.py -v
PYTHONPATH=ml ml/.venv/bin/python -m unittest discover -s ml/tests -p test_bill_http.py -v
```

## Comparing manually entered bills in Python

`BillComparisonRequest` and `compare_bills` in `ml/aquamind_ml/bills.py` compare
2–12 supplied bills. This calculation is currently a Python interface; the HTTP
API and `/analyze` still accept one bill at a time.

```python
from aquamind_ml.bills import BillComparisonRequest, compare_bills

request = BillComparisonRequest.model_validate({"bills": [
    {"period_start": "2026-02-01", "period_end_exclusive": "2026-03-01",
     "usage": "2800", "usage_unit": "us_gallons"},
    {"period_start": "2026-03-01", "period_end_exclusive": "2026-04-01",
     "usage": "3100", "usage_unit": "us_gallons"},
]})
result = compare_bills(request)
assert result.latest_percent_change == "0.00"  # Both periods average 100 gallons/day.
```

The contract sorts entries by start date without changing the caller's collection.
Duplicate, corrected-but-overlapping and other overlapping periods are rejected;
adjacent exclusive-end periods are valid. Gaps are allowed and reported as
`gap_days`; no consumption is assumed for missing days. All entries must describe
the same household and meter, an assumption the application cannot verify.

The latest period is compared with **all supplied earlier periods**, excluding the
latest from its own baseline. The baseline is the sum of earlier converted volumes
divided by their total billing days, not an unweighted mean of bill averages or an
average over the entire calendar span. The result includes chronologically ordered
normalized entries, covered days, gap days and the baseline bill/day counts.
Mixed supported units retain their original entries. Unknown charges and explicit
zeros stay distinct; no cost trend, tariff or savings calculation is inferred.

Calculations use unrounded converted volumes in an isolated 40-digit decimal
context. Baseline and absolute daily change are rounded half-up to six decimal
places; percentage change is rounded to two. Percentage is `null` when the exact
baseline is zero, including zero-to-zero comparisons. A very small positive
baseline can display as zero while still producing a defined percentage. These
are comparisons of unverified aggregate averages, not a seasonal model, a judgment
that usage is unusually high or evidence of a particular leak or fixture.
The calculation has no model calls, persistence or changes to session goals.

Run the comparison checks without credentials or a listening server:

```sh
PYTHONPATH=ml ml/.venv/bin/python -m unittest discover -s ml/tests -p test_bill_comparison.py -v
```

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

This preparation stage produces sequences; model training and evaluation are separate stages below.

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

`ml/aquamind_ml/model.py` implements an LSTM autoencoder: a 32-unit encoder compresses a sequence into an 8-value latent vector; an LSTM decoder reconstructs the flow sequence from that vector. Input and output shapes are `[batch, time, 1]` with normalized float32 flow values. The decoder does not receive the original observations. `reconstruction_errors` returns squared errors per interval and mean squared error per window, not leak probabilities or classifications. Reconstruction error alone is not a classification. Frozen experimental detectors are described below.

Create an isolated environment and run all Python tests from the repository root:

```sh
python3 -m venv ml/.venv
ml/.venv/bin/python -m pip install -r ml/requirements-agent.txt
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

The first 20-epoch baseline is recorded in the generated [baseline summary](../evals/baselines/lstm-v1.json): test precision 0.2420, recall 0.6905, and F1 0.3583 across 1,470 daily windows. This baseline does **not** provide adequate leak discrimination. There are 636 false positives and 91 missed leak windows. Treat this as an initial measured baseline requiring improvement, not a validated leak detector. Reproduction commands in the summary assume fresh output paths; full per-window reports and weights remain in ignored local artifact directories.

### Validation-only scoring development

```sh
PYTHONPATH=ml ml/.venv/bin/python -m aquamind_ml.validate_scoring --dataset ml/data/generated/meter-experiment.json --checkpoint ml/artifacts/lstm-baseline-v1 --output evals/reports/calibrated-validation.json
```

This compares daily MSE with positive standardized reconstruction residuals, using the same trained LSTM weights. For each of 96 daily slots, calibration fits residual mean and population standard deviation on normal training windows only. The standard deviation has a fixed 0.01 floor in normalized-flow units. The daily score is the mean squared positive standardized residual. This reduces the influence of naturally variable fixture-use periods without using scenario labels as input features. Windows must align to midnight UTC; adapting the daily baseline to local household schedules remains future work.

The generated [validation comparison](../evals/baselines/calibrated-validation.json) reports F1 improving from 0.3545 to 1.0000 on 1,440 validation windows. This is **development evidence, not held-out accuracy**. Threshold selection uses validation labels, all seeds share simple fixed simulator schedules, and the test split is never scored by this command. The prior held-out result remains unchanged. Freeze the scoring method, calibration, and threshold before a confirmatory evaluation on fresh unseen seeds.

### Frozen detector and fresh-seed confirmation

After reproducing the baseline training run, freeze its calibrated scoring parameters before generating confirmation data:

```sh
PYTHONPATH=ml ml/.venv/bin/python -m aquamind_ml.detector --dataset ml/data/generated/meter-experiment.json --checkpoint ml/artifacts/lstm-baseline-v1 --output ml/artifacts/detector-v1
pnpm data:export --seed-start 10000 --seed-count 1000 --output ml/data/generated/confirm-v1.json
PYTHONPATH=ml ml/.venv/bin/python -m aquamind_ml.confirm --dataset ml/data/generated/confirm-v1.json --detector ml/artifacts/detector-v1 --output evals/reports/confirm-v1.json
```

The detector directory contains `weights.pt` and `detector.json`: model dimensions, training-only normalization and residual calibration, the validation-selected threshold, development seed exclusions, and source/weight checksums. Its version hashes the manifest, so changing calibration or the threshold also changes the version. `FrozenDetector.predict` loads these parameters and never fits them; it uses flow values and UTC window alignment, not scenario or anomaly labels. Keep both files together. This is the frozen inference interface used by the local API described below; no public deployment is provided.

Confirmation rejects overlap with any original training, validation, or previously inspected test seed. Only the new export's test split is scored. The generated [confirmation summary](../evals/baselines/confirm-v1.json) records **precision 1.0000, recall 0.9897, and F1 0.9948** across **1,450 daily windows from 145 unseen synthetic seeds**, using a frozen threshold of 7.725719451904297. There were 287 true positives, 1,160 true negatives, no false positives, and three false negatives. No refitting occurred.

This supports a PyTorch LSTM autoencoder **with training-calibrated reconstruction scores on a synthetic seed holdout**. It does not demonstrate generalization to different household schedules or real-world meters. Interpret these results only as synthetic evaluation, with the dataset and protocol qualifications above. Earlier baseline results remain recorded for comparison; confirmation results must not be used to retune this detector.

## Local inference API

After creating `ml/artifacts/detector-v1`, install the API dependencies and start the server from the repository root:

```sh
ml/.venv/bin/python -m pip install -r ml/requirements-api.txt
PYTHONPATH=ml AQUAMIND_DETECTOR_PATH=ml/artifacts/detector-v1 ml/.venv/bin/python -m uvicorn aquamind_ml.api:app --host 127.0.0.1 --port 8001
```

Open `http://127.0.0.1:8001/docs` for the typed API contract. `GET /health` reports process liveness; `GET /ready` returns 503 if the model could not load. `POST /v1/anomaly/predict` accepts `start_timestamp` (midnight UTC) and `flow_rates_gpm` (exactly 96 finite numeric values from 0 to 1,000 GPM, representing consecutive 15-minute intervals). Unknown fields, numeric strings, booleans, negative values, and misaligned windows are rejected. Labels are neither required nor accepted.

The response includes `score`, `is_leak`, `threshold`, `model_version`, `request_id`, and synthetic training-data disclosure. Scores are calibrated reconstruction errors, not probabilities. They classify a whole day and do not localize individual leak intervals. Model loading occurs once at startup; inference uses one PyTorch CPU thread and serialized model access. Validation errors omit raw input, and structured log events contain identifiers/status/timing or error types, not meter readings. Responses include `X-Request-ID` and disable caching.

This service is local-only at this stage. Public request-size/rate limits and deployment configuration remain future work. No cross-origin browser access is enabled. The assistant uses the frozen detector through MCP; chart highlights remain simulator-defined. No API keys are needed for local inference.

### HTTP latency benchmark

```sh
PYTHONPATH=ml ml/.venv/bin/python -m aquamind_ml.benchmark --dataset ml/data/generated/meter-experiment.json --detector ml/artifacts/detector-v1 --requests 1000 --concurrency 4 --warmup 50 --output evals/reports/api-latency-v1.json
```

The command starts and stops its own Uvicorn process on loopback port 8002 (change with `--port`). It waits for readiness, sends sequential warm-up requests, then uses concurrent HTTP clients to submit one 96-reading window per request to `POST /v1/anomaly/predict`. Payloads cycle through validation windows in export order. Timings cover the client POST call through receipt of the full response, including JSON encoding, TCP, server validation, queueing, inference, and response serialization. Startup/model loading and client-side response-schema checks are outside the latency timer. Server JSON request logging remains enabled, with output captured to a temporary file.

Percentiles use nearest rank. The report records all timed samples, failures without retries, warm-up count, concurrency, throughput, source hashes, model version, and environment. Failures cause a nonzero exit after the report is saved; successful-request and all-attempt percentiles are reported separately. Existing report files cannot be overwritten.

The generated [local latency baseline](../evals/baselines/api-latency-v1.json) measured **p50 7.85 ms, p95 15.36 ms, p99 38.62 ms**, with **1,000/1,000 successful requests**, concurrency 4, and 50 warm-up requests. This supports a local warm-server p95 below 100 ms through the actual FastAPI HTTP path. It does not establish deployed internet latency, cold-start behavior, or performance on different hardware; client and server shared the same macOS ARM machine with one server worker and one PyTorch CPU thread.

## Local MCP tools

Install `ml/requirements-mcp.txt` to use the official MCP Python SDK 2.3.0. The server uses the SDK's `MCPServer` and stdio transport. From the repository root, an MCP host can launch:

```sh
PYTHONPATH=ml AQUAMIND_DETECTOR_PATH=ml/artifacts/detector-v1 AQUAMIND_MCP_SCOPES=anomaly:read ml/.venv/bin/python -m aquamind_ml.mcp_server
```

The tool `detect_water_anomaly` accepts a `request` object with the same `start_timestamp` and `flow_rates_gpm` fields as the HTTP API. Its advertised input and output schemas are generated from the shared Pydantic contracts. It returns real frozen-model predictions with model version, threshold, request ID, and synthetic-training disclosure. Tool annotations identify it as read-only, non-destructive, and closed-world. Standard output is reserved for MCP protocol messages.

Scopes are fixed by the trusted host's startup configuration; an empty `AQUAMIND_MCP_SCOPES` denies calls. Tool arguments cannot grant `anomaly:read`, `meter:read`, `utility:read`, `weather:read`, or `goals:write`. This process-level permission boundary is for local stdio use, not remote user authentication. Model failures produce tool errors, never fabricated predictions. The goal tool below creates an approval proposal; goal execution is reserved for a separate trusted host decision.

Tests negotiate an actual MCP session with a subprocess, discover the tool and output schema, and compare its result with direct PyTorch inference. Additional protocol tests cover denied permissions, malformed requests, and unavailable models. These are protocol and integration checks, not an end-to-end agent evaluation.

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

The dataset is loaded once at startup. Missing windows, absent files, and invalid exports produce tool errors. Callers cannot select filesystem paths. Grant both scopes as `anomaly:read,meter:read` and configure both artifact paths to enable model inference alongside meter reads. These are local synthetic-window tools; household authentication and window discovery remain outstanding. The agent API's selected-demo mode below uses a separate snapshot rather than the ML experiment export. The export's test split remains ML evaluation data, not an independent agent benchmark.

### Dashboard meter snapshot

The committed 16 KB `ml/data/demo/meter-v1.json` is generated directly from the same TypeScript simulator as the dashboard, using seed 42. It contains seven days of interval gallons for each of the four scenarios, with no fixture identities, excess-volume labels or anomaly ground truth. It is separate from the ML experiment export; no experiment splits or frozen detector artifacts are changed.

`DemoMeterStore` validates and loads this snapshot once. Its summary gives the final UTC day's gallons, mean/peak interval-average GPM, and comparison with the preceding six-day baseline. Series adds 96 GPM values derived from interval gallons divided by 15; the simulator's separately rounded GPM field is not used, so volumes match the chart's underlying gallons. Dashboard cards round totals to one decimal place. Returned source, seed, timestamps and SHA-256 identify the synthetic snapshot; these readings are not real observations or a leak diagnosis.

Regenerate or check the snapshot from the repository root after simulator changes:

```sh
pnpm data:demo
pnpm data:demo --check
```

The TypeScript check compares all four snapshot scenarios and rounded daily/baseline totals with the dashboard generator. Python checks cover strict snapshot validation, units/provenance, copy isolation and an undefined percentage when the baseline is zero.

In-process hosts may pass `demo_meter=DemoMeterStore()` and a validated `demo_scenario` to `create_server`, rather than an experiment dataset path. In this mode, `get_meter_summary`, `get_meter_series`, and `get_weather_context` take no model-supplied arguments and read the same host-selected scenario. The meter reads still require `meter:read`, and weather requires `weather:read`. Invalid or ambiguous bindings are rejected. MCP checks cover these bindings, read-only annotations and scope denial. Bindings alone do not grant anomaly inference or goal approval.

With both `meter:read` and `anomaly:read`, the selected-demo `detect_water_anomaly` tool also takes no arguments. It feeds only the snapshot's final-day GPM values and neutral window metadata into the frozen model; the model cannot choose readings, a threshold, a path or a different scenario. Results add synthetic-source disclosure, snapshot SHA-256 and UTC boundaries to the existing score, threshold, model version and training-data disclosure. The legacy `is_leak` field is a daily threshold flag, not proof of a physical leak or a fixture diagnosis. Scores are not probabilities, and an unflagged day does not rule out a leak. The model is trained on synthetic data and is not field-validated. Direct frozen-model and MCP predictions are compared for all four demo scenarios; this is integration coverage, not a new accuracy evaluation.

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

This is the tested backend approval boundary. The browser flow below adds session-bound review, decisions and agent follow-up; the standalone stdio server still has no decision transport. Persistent goals/audit storage remains to be implemented. No database or API credentials are needed for the approval store itself.

### Session-bound approval API

FastAPI now exposes anonymous, ephemeral demo sessions and human-decision endpoints:

- `POST /v1/sessions`: returns a random `session_token` valid for one hour.
- `GET /v1/approvals/{approval_id}`: reviews the exact stored proposal and remaining expiry.
- `POST /v1/approvals/{approval_id}/decision`: accepts only `{"decision":"approve"}` or `{"decision":"reject"}`.
- `GET /v1/goals/current`: returns the session's approved goal, or null.
- `DELETE /v1/session`: revokes the session credential.

All except creation require `Authorization: Bearer <session_token>`. Responses use `Cache-Control: no-store`; request logs omit credentials and bodies. A different session receives 404 for a proposal, and missing, expired, or revoked credentials receive 401. Browser cookies are not used and cross-origin access is not enabled. Use HTTPS and a same-origin host/proxy when connecting the browser; keep the credential out of agent prompts, tool arguments, traces, and URLs.

The trusted host obtains the session store via `app.state.sessions.approvals(token)` and injects it into `create_server(..., goal_approvals=store)`. There is no HTTP endpoint that lets the agent grant itself consent. The decision endpoint is for the human UI; it must never be registered as an agent tool. Bearer possession authenticates the demo session, not a real-world identity or proof of a physical click. Approval stores enforce their own session deadline and revocation state: cached MCP connections cannot propose goals, read goals/proposals, or execute decisions after the owning session ends. Revocation clears the session’s stored goals and proposals. Proposal expiry is capped by the session’s remaining lifetime. A decision racing with revocation is serialized by the store lock; requests that reach the store after revocation receive 401. Read-only synthetic MCP tools retain their independent startup scopes.

The API retains at most 100 sessions, evicts expired sessions on creation, and returns 503 at capacity. State is process-local: use one worker for this local prototype. Production rate limiting, shared storage and production lifecycle hardening remain outstanding. Tests run an actual MCP proposal followed by HTTP review/approval and cover cross-session denial, rejection, malformed decisions, expiry, revocation, and capacity recovery.

### Browser assistant and approval

The `/demo` side panel accepts water questions and displays live model answers with expandable tool-execution metadata. The dashboard and assistant share one scenario selection. Each question sends its text and selected scenario ID; the backend can retrieve that scenario's synthetic meter summary/readings and weather through scoped MCP tools, calculate illustrative costs/savings, or propose a daily goal. The browser does not submit readings, simulator labels or tool permissions. Questions and requested synthetic evidence go to OpenAI, with a visible reminder to avoid personal information. Meter evidence describes synthetic usage, not a model diagnosis.

The assistant displays the current selection and labels each question/reply with the scenario captured when that question was sent. Switching the dashboard while a request is running changes the chart and selection for the next question, while the arriving answer keeps its original label. New questions remain independent turns; the last 16 messages are retained only in the mounted panel. Agent proposal cards show their originating scenario, and approval decisions/follow-ups keep it even after switching the chart. Scenario changes preserve the same ephemeral session and confirmed daily goal. Model text is escaped as text, without HTML execution, embedded remote media or automatic link rendering.

Agent and manual goal proposals share one ephemeral bearer session. The manual form remains available without a model connection. A pending proposal disables new questions and proposals until it is approved, rejected, or refreshed into a terminal state. The review card shows the server's exact summary and provides explicit Approve, Reject and Refresh controls. Approval alone updates the displayed goal from the server-confirmed result. An uncertain decision leaves the pending proposal available for an explicit idempotent retry. Model text and tool proposals cannot trigger these decision requests. No household equipment is controlled.

After a confirmed review result for an agent proposal, the browser requests an assistant follow-up. The goal card updates before that model request, so a failed follow-up never hides or rolls back an applied decision. A lost follow-up response leaves a separate Check assistant follow-up button; it requests the saved continuation outcome without repeating the decision. Manual proposals do not create model continuations. Starting a new question abandons the old follow-up context.

Install `ml/requirements-agent.txt`, configure `OPENAI_API_KEY` and `OPENAI_MODEL` in the ignored root `.env.local`, then start the single-worker backend and frontend from the repository root in separate terminals:

```sh
AQUAMIND_AGENT_ENABLED=1 PYTHONPATH=ml ml/.venv/bin/python -m uvicorn aquamind_ml.api:app --env-file .env.local --host 127.0.0.1 --port 8000 --workers 1
AQUAMIND_API_URL=http://127.0.0.1:8000 pnpm --filter web dev --hostname 127.0.0.1
```

To enable model checks in chat, also set `AQUAMIND_DETECTOR_PATH=ml/artifacts/detector-v1` on the backend command after creating the frozen artifact described above. FastAPI loads the model once and shares the same instance and inference lock with the agent's MCP tools, including approval follow-ups. No fitting, calibration, threshold changes or per-turn model reloads occur. An absent or invalid artifact leaves meter/weather/utility/goal chat usable without advertising the anomaly tool; an inference failure returns a tool error without fabricated scores. New API credentials are not required. Stop both local servers after testing.

`AQUAMIND_API_URL` is a server-only backend address, not an API key. The Next.js relay exposes only the session, agent-turn/continuation, goal-proposal, goal-read, approval and bill-normalization endpoints. It forwards JSON and the bearer credential, omits browser cookies and limits streamed bodies to 16 KiB for new agent turns or 1 KiB for other requests. Both agent routes use 135/150-second relay/browser deadlines, allowing the backend's bounded stage to finish; other relay requests retain a ten-second deadline. All responses are non-cacheable. The OpenAI key is loaded only by Python, never sent to the browser.

Session credentials remain in memory and authorization headers, never URLs, cookies or browser storage. Reloading starts fresh. A 401 clears the expired session and its displayed proposals/goals; a new user action can create another session. Concurrent actions are blocked, and paid questions are never retried automatically. Missing dependencies, invalid responses, busy/budget outcomes and unconfirmed requests are surfaced without fabricated answers. These are local, session-only flows; shared storage and multi-worker deployment are not supported. General conversation history, durable state and multimodal inputs remain outstanding.


## External data foundation

The AMPds2 workflow includes checksum verification, chronological 15-minute windows, a training-only profile, controlled pattern generation, immutable loading, and training-only normalization. A separate LSTM training adapter fits unmodified real baseline days with unknown physical leak labels. See [provenance, experiments, limitations, and reproduction](datasets/ampds2.md).

The initial hybrid MSE validation baseline flags every variant. Subsequent sustained-residual experiments improve discrimination; strict four-hour persistence reaches validation F1 0.8995 while meeting the declared reference alarm caps. Short low-flow patterns remain difficult. The strict-persistence detector is frozen and versioned. Its chronological hybrid holdout achieved F1 0.8988, but unmodified/demand-confounder alarm rates rose to 6.4%/11.0%; it remains experimental.

The served detector and existing classification/latency benchmarks still use synthetic data. Manual bill validation and stateless API normalization are available as described above; manual entry and optional bill-only questions are available at `/analyze`. Bill questions do not use either anomaly detector.


## Agent MCP adapter

`aquamind_ml.agent_tools.McpAgentTools` is the first agent integration layer. The host supplies a connected official MCP `Client` and an explicit subset of the eight known AquaMind tool names. The default tool list is empty. Discovery reads the real server's tool descriptions and schemas, with at most four pages and a timeout; it never exposes host approval/decision methods. MCP scopes remain authoritative even when a name is allowed by the adapter.

`await bridge.discover()` returns function definitions suitable for a Responses API request. They preserve the MCP JSON schemas and explicitly use `strict: false`; the existing MCP/Pydantic server performs final validation. This follows the [official OpenAI function-calling contract](https://developers.openai.com/api/docs/guides/function-calling). There is no promise of model-side strict schema enforcement in this adapter.

`await bridge.execute(call_id, tool_name, arguments_json)` returns a `ToolOutcome`; `response_output()` serializes a correlated `function_call_output` record. Execution is serialized and bounded to eight calls by default (host-configurable up to 16), ten seconds per tool (up to 30), 32 KiB of arguments and 64 KiB of structured output. Invalid JSON, duplicate keys, NaN/Infinity, extra root arguments and disallowed tools are rejected. Failed attempts consume budget. Repeated call IDs cannot execute twice, including concurrent requests.

Read success, tool errors, unconfirmed transport outcomes, and pending approvals remain distinct. `set_conservation_goal` must return `approval_required`; it cannot be treated as an executed goal. Timeout/connection failures receive no automatic retry because an outcome may be uncertain. Hosts must stop or surface a pending approval rather than claiming a goal was applied. Cancellation/timeout does not guarantee the underlying server work stopped.

The bounded metadata trace contains only call ID, recognized tool name, status and elapsed time. It does not log tool arguments/results, session credentials, provider errors or hidden reasoning. Tool results stay in the returned in-memory outcome for the agent host. Tests negotiate real MCP sessions, including stdio subprocess discovery/execution, and cover scopes, approval safety, duplicate execution, malformed arguments, budgets, and timeout handling.

These are adapter development tests, not an end-to-end agent evaluation. The adapter supplies the following model loop, session-bound browser integration and approval-result continuation.

## Bounded text agent

`aquamind_ml.agent.run_agent` connects the official OpenAI Responses SDK to the MCP adapter for one text turn. The host supplies a model, connected client, explicit tool allowlist and scoped MCP server. It allows at most six model requests by default (configurable up to eight), 2,048 output tokens per request, 30 seconds per request and 120 seconds total. Input is limited to 8 KiB; accumulated history and each response have additional size limits. Every request overrides SDK retries to zero, including when the supplied client has its default retry policy. Tool budgets and validation still apply independently.

Function calls and correlated results are replayed in memory until an answer, pending approval, refusal, limit or dependency failure ends the stage. Unexpected parallel tool calls are rejected before execution. A goal proposal immediately returns its actual pending record to the trusted host, with no model-generated claim of approval or execution. Unconfirmed tool/provider timeouts stop the stage without retry. The HTTP host privately retains the bounded protocol checkpoint needed to continue after a trusted review result.

Requests use `store=False` and replay encrypted reasoning protocol items in memory, following the [Responses migration guide](https://developers.openai.com/api/docs/guides/migrate-to-responses). These items, prompts, arguments and raw provider errors are excluded from the public trace. Model trace metadata includes response ID, model and token counts; tool traces retain only execution metadata. `store=False` does not assert zero provider retention. The runtime policy requires evidence-grounded water guidance and disclosure of synthetic data and illustrative rates; policy text alone is not an evaluated reasoning-quality guarantee.

Install `ml/requirements-agent.txt`. Configure `OPENAI_API_KEY` and `OPENAI_MODEL` in the ignored repository-root `.env.local`, keeping the secret out of chat and `.env.example`. The model must support Responses function calling. Check presence without printing values or making an external request:

```sh
PYTHONPATH=ml ml/.venv/bin/python -m aquamind_ml.agent_cli --check-config
```

After configuration, run a live local smoke request:

```sh
PYTHONPATH=ml ml/.venv/bin/python -m aquamind_ml.agent_cli 'Estimate the water-only cost of 1,000 gallons using the demo rate.'
```

The CLI exposes only four read tools for synthetic weather and illustrative utility calculations, with `weather:read` and `utility:read` scopes. It has no meter, anomaly or goal tool enabled. Its response and metadata print locally; no conversation is persisted. Provider requests go to the official API endpoint with automatic retries disabled. The application key will later belong in the Python backend's production secret configuration, never in browser code.

Automated checks use the real SDK with a simulated HTTP transport and real in-process MCP sessions. They verify protocol replay, actual utility calculations, approval stopping, call limits, provider errors/timeouts and incomplete/refused responses. They do not establish live model behavior, answer quality, multimodal capabilities, agent benchmark scores or deployment readiness. OpenAI configuration is now available for explicit live smoke checks; database and hosting credentials are not needed for this increment.

## Bill-only agent questions

After calculating a bill at `/analyze`, users can opt in to share that bill and a question with OpenAI. The checkbox starts unchecked and resets when the bill is edited or cleared. Inputs are locked during an answer request so a reply cannot appear against an edited bill. Only the most recent answer and question stay in the mounted panel; new questions are independent, and reload clears the panel. Model output is displayed as escaped text, without HTML or automatic media/link rendering.

`POST /v1/agent/bill` requires a bearer session and accepts only `text`, `bill` (the original `ManualBill` fields), `is_example` (boolean) and `share_with_ai: true` (strict boolean). False/missing consent, client-computed quantities, synthetic scenario selections, paths and unknown fields are rejected before provider work. The host validates and normalizes the entry again; it never trusts frontend totals. Duplicate JSON keys, non-finite numbers and invalid decimal exponents are rejected. These JSON protections also apply to the ordinary agent and continuation request parsers.

The host supplies the normalized bill and example flag as a structured user message, separately from the fixed bill-only instructions and the user's question. Keeping data out of developer instructions follows the [OpenAI agent safety guidance](https://developers.openai.com/api/docs/guides/agent-builder-safety). Values remain unverified. Example entries are labeled as examples in the context; missing charges remain unknown. The bill policy asks for cautious explanations and additional evidence rather than inferring trends, leak timing, fixtures, tariffs or savings from one bill. This policy is guidance, not a measured guarantee of answer correctness.

Bill turns receive no tools or scopes: they cannot retrieve demo meter/weather data, use illustrative utility rates, invoke either detector, or propose/apply goals. Hallucinated tool calls are denied and do not trigger a second provider request. Each bill question allows at most one model request with existing timeout/token limits, `store=False` and automatic retries disabled. [OpenAI API data controls](https://developers.openai.com/api/docs/guides/your-data) govern provider retention; `store=False` is not a zero-retention assertion.

The existing session/process concurrency and attempt budgets apply across bill and demo questions. A pending demo goal blocks a bill question on the same session without discarding its approval checkpoint. Bill questions create no continuation checkpoint or durable bill/conversation record. Session liveness is checked before provider work and before releasing the answer. Application logs and traces omit bill fields, prompts, raw provider errors and hidden protocol content. Revocation cannot undo an already-sent provider request.

The response is the existing `AgentTurnResponse` body with request ID and bounded metadata; bill turns never return pending approvals. Authentication, size, media and validation failures use 401/413/415/422; disabled/unavailable hosts use 503. The same-origin relay allows only POST, limits bodies to 16 KiB and uses the existing 135/150-second relay/browser deadlines. The normalization endpoint remains usable without OpenAI configuration or sharing consent. The browser never retries a failed bill question automatically.

Automated checks use the real SDK with a simulated provider and in-process MCP to verify evidence calculation, empty tool access, consent/schema rejection, context isolation, retained pending approvals, budgets and expiry/revocation. Client/relay checks cover explicit sharing, captured input, invalid responses, provider failures and no retries. These checks do not measure live-model diagnostic quality or production deployment behavior.

## Session-bound agent API

`POST /v1/agent/turn` accepts `{"text":"your water question"}` with an optional `scenario_id`, and requires the bearer credential from `POST /v1/sessions`. The model, tool names, scopes, approval store and budgets are chosen by the host, never by request fields. A turn can use synthetic weather, illustrative utility calculations and `set_conservation_goal`. Selecting a demo scenario additionally enables scoped meter reads using the dashboard snapshot above, plus the bound anomaly tool when a frozen model is loaded. Unselected turns never receive anomaly access. The session credential is never included in the model input or tool arguments.

For example, `{"text":"How does this day compare with the baseline?","scenario_id":"overnight-leak"}` selects the dashboard's fixed seed-42 household. The only supported selections are `normal`, `overnight-leak`, `running-toilet`, and `irrigation-after-rain`. In this mode, `get_meter_summary`, `get_meter_series`, and `get_weather_context` take no model-supplied arguments: the host binds all three to the same scenario for the entire turn and any approval continuation. A new question can choose a different scenario. Omitted/null selection retains the previous utility/weather/goal-only behavior. The browser client now sends its selected scenario for every question, and continuation requests still contain only the proposal ID.

Missing or invalid demo snapshots return 503 before provider work for selected turns; unselected turns remain usable. Agent API checks cover all four selected scenarios, matching weather, argument override denial, missing-snapshot failure and context preservation through approval continuation. These checks use the real SDK with simulated provider responses and actual in-process MCP execution; they do not establish live model answer quality or an agent benchmark score.

The endpoint returns `status`, `answer`, `pending_approval`, `error`, `model_calls`, bounded model/tool metadata and `request_id`. Turn outcomes, including provider unavailability or incomplete responses, use this structured body with HTTP 200. Missing/expired/revoked sessions return 401; an unavailable/disabled host returns 503. Malformed text/extra fields return 422, non-JSON content returns 415, and raw request bodies over 16 KiB return 413. Text itself remains limited to 8 KiB of UTF-8. Request logs contain no prompts, bearer credentials or answers.

A goal tool shares the exact session's existing approval store. The endpoint returns its stored pending proposal and suppresses model text that might claim execution. Only the separate trusted decision endpoint can approve/reject it; a different session cannot review or decide. Expiry/revocation is checked before each model request and tool call, and before releasing the result. Revocation cannot undo a provider request already in flight. Unrelated questions remain independent; only the paused goal turn is replayed for its decision follow-up.

`POST /v1/agent/continue` accepts only `{"approval_id":"the-agent-proposal-uuid"}`, with the same bearer session. The host requires its own saved checkpoint and re-reads the server's proposal status and current goal. Pending decisions return 409, unknown/other-session/manual proposals return 404, and extra fields such as client-supplied decisions or history return 422. A pending agent proposal also blocks a new agent question with 409 until review resolves it. The follow-up continues the original function call with a correlated `function_call_output` containing only the verified status, requested gallons and current goal. It follows the [official Responses replay contract](https://developers.openai.com/api/docs/guides/function-calling), including required reasoning protocol items with `store=False`; none of that private history is returned in API metadata.

Continuation tools are read-only: the original proposal tool is not executed again and a new goal proposal is denied even if the model requests one. Approved, rejected, expired and conflicting results are explained using the stored outcome. The original model-call budget is shared across both stages; each stage has the existing timeout. Public model/tool traces describe that stage only. An admitted continuation consumes one session/process attempt. Repeated continuation requests reuse the saved outcome without a new provider attempt or budget charge; concurrent requests return 409. An externally interrupted continuation is consumed and returns 503 on subsequent checks, rather than retrying an uncertain paid request. A failed follow-up never reverses the already-confirmed decision.

There is at most one private checkpoint per session, limited to 512 KiB of serialized history. New questions discard the previous checkpoint/cache; the checkpoint is cleared after the first continuation attempt. The runtime keeps checkpoints and cached outcomes in process memory, inaccessible after session expiry/revocation and reclaimed with session cleanup or process restart. Private protocol histories are never logged or reported; the explicit smoke harness saves only public outcomes for its known demo questions. This is scoped approval continuation, not a general persistent conversation store.

For this opt-in local host, limits are two concurrent stages per process, one per session, eight attempted stages per session lifetime, and 100 attempted stages per process lifetime. Failed attempts consume budget; admitted stages retain the existing model/tool call and time limits. Concurrent requests for one session receive 409; global concurrency and exhausted budgets receive 429. There is no automatic HTTP retry. Counters are process-local, and anonymous users can create another session; these are bounded development controls, not production abuse prevention or distributed rate limiting. Use one worker and bind to loopback while developing.

The agent is disabled by default even if an API key is present. Install `ml/requirements-agent.txt`, configure the ignored root `.env.local`, then explicitly enable it for a local server:

```sh
AQUAMIND_AGENT_ENABLED=1 PYTHONPATH=ml ml/.venv/bin/python -m uvicorn aquamind_ml.api:app --env-file .env.local --host 127.0.0.1 --port 8000 --workers 1
```

Missing/invalid configuration leaves inference health available and the agent host unavailable. The provider client is created/closed with app lifespan, and the endpoint is pinned to the official OpenAI API. The inference-only installation does not import the optional OpenAI SDK when the agent is disabled. The Next.js relay and `/demo` assistant expose this endpoint using the same session as manual/agent goal approvals.

Run the explicitly paid smoke check to exercise session creation, a live-model utility answer, a live-model pending goal, trusted-host rejection and session cleanup through FastAPI's local ASGI test client:

```sh
PYTHONPATH=ml ml/.venv/bin/python -m aquamind_ml.agent_smoke --output evals/reports/agent-http-smoke.json
```

The record contains known demo questions, safe public outcomes, model/token/tool metadata, timings, source hashes and narrow check results. It excludes the API key and session credential. The initial run is saved in `evals/baselines/agent-http-smoke-v1.json`. These are two development smoke cases; the check does not establish browser behavior, production latency, multimodal reasoning or physical leak detection. Automated API checks additionally cover cross-session approval denial, malformed input, disabled/misconfigured hosts, concurrent requests, budget exhaustion and expiry/revocation during a provider request.

To additionally exercise approved/rejected live follow-ups and cached retrieval, making additional paid requests:

```sh
PYTHONPATH=ml ml/.venv/bin/python -m aquamind_ml.agent_smoke --with-continuation --output evals/reports/agent-continuation-smoke.json
```

`evals/baselines/agent-continuation-smoke-v1.json` records the verified continuation run and source hashes. Decisions in this harness come from the trusted test host, not human browser clicks. These narrow checks are not a new agent benchmark or a measured scenario pass rate. API tests separately cover forged decisions, read-only enforcement, all four resolved statuses, shared budgets, cached failures, interrupted requests and context invalidation.

To additionally check live-model calls to both the anomaly tool and meter summary for overnight and normal demo days:

```sh
AQUAMIND_DETECTOR_PATH=ml/artifacts/detector-v1 PYTHONPATH=ml ml/.venv/bin/python -m aquamind_ml.agent_smoke --with-anomaly --output evals/reports/agent-anomaly-smoke.json
```

This explicitly paid smoke run checks model readiness before provider work and cleans up its session, provider client and API lifespan without opening a listening port. Automated checks require successful tool execution and a final answer; they do not grade full diagnostic quality or establish new ML accuracy, latency or agent pass-rate metrics. Review the saved answers and limitations alongside the deterministic integration tests. `--with-continuation` may also be added within the existing per-session stage budget.

Recorded smoke reports describe the source hashes at the time of their original runs. Internal naming refactors can change those hashes without changing runtime behavior. Generate a new report when validating current sources; do not edit historical reports to imply a new provider run.
