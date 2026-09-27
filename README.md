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

All meter readings and weather context are **synthetic**. Anomaly flags are injected by the simulator, not predicted by a trained model. The assistant panel is an inactive placeholder. PyTorch, FastAPI, LLMs, MCP, image analysis, and voice interaction are not implemented yet. The landing-page preview is illustrative and is separate from the generated demo dashboard.

## Water-data model

The public API lives in `apps/web/src/lib/water/index.ts`:

```ts
import { generateHouseholdDataset } from "@/lib/water";

const dataset = generateHouseholdDataset("overnight-leak", 42);
```

The same scenario and seed reproduce the same dataset. The default seed is `42`. Each dataset contains seven days beginning June 15, 2026 at midnight UTC: 672 readings at 15-minute intervals, with gallons, interval-average flow, fixture attribution, anomaly flags, and excess gallons. The simulated household has three occupants and includes baseline usage, showers, toilets, faucets, dishwasher and washer cycles, and occasional irrigation.

Summary calculations use the final simulated day as “today” and the preceding six days' mean daily volume as the baseline. Percentage change is calculated before display rounding. Excess gallons represent injected anomaly volume, not the difference from the historical baseline. Peak excess flow is the maximum anomalous interval's excess gallons divided by 15 minutes; it is not a live flow measurement. All displayed meter times use UTC.

These are transparent simulation assumptions, not a scientifically validated household model or an evaluated leak detector.

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

The repository is a pnpm workspace. Backend and model work remain future development; the current runnable application is `apps/web`.
