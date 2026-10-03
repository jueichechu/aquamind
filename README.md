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

All meter readings and weather context are **synthetic**. Anomaly flags are injected by the simulator, not predicted by a trained model. The assistant panel is an inactive placeholder. An untrained PyTorch autoencoder is implemented separately; FastAPI, LLMs, MCP, image analysis, and voice interaction are not implemented yet. The landing-page preview is illustrative and is separate from the generated demo dashboard.

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

`ml/aquamind_ml/model.py` implements an LSTM autoencoder: a 32-unit encoder compresses a sequence into an 8-value latent vector; an LSTM decoder reconstructs the flow sequence from that vector. Input and output shapes are `[batch, time, 1]` with normalized float32 flow values. The decoder does not receive the original observations. `reconstruction_errors` returns squared errors per interval and mean squared error per window, not leak probabilities or classifications. No threshold or trained production weights exist yet.

Create an isolated environment and run all Python tests from the repository root:

```sh
python3 -m venv ml/.venv
ml/.venv/bin/python -m pip install -r ml/requirements.txt
PYTHONPATH=ml ml/.venv/bin/python -m unittest discover -s ml/tests -v
```

The model tests check gradients, sequence reconstruction learning on a simple fixture, and saved-weight round trips. These tests do not establish held-out leak accuracy. Reproducible training, validation-based threshold selection, and test-set evaluation remain to be implemented.

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

The repository is a pnpm workspace. Python data preparation and the untrained LSTM autoencoder live in `ml/`; backend serving and model training remain future development. The current runnable web application is `apps/web`.
