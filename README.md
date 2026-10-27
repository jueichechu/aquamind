# AquaMind

AquaMind is a household water-intelligence application built with Next.js, FastAPI, PyTorch and MCP. It combines water-usage evidence with an AI assistant to help users investigate unusual consumption and explore conservation actions.

The current release is a local development application. It includes household bill analysis with optional document import, a synthetic household dashboard, an optional live text assistant and experimental anomaly detection.

## Features

- Interactive meter dashboard with normal usage, overnight leak, running toilet and irrigation-after-rain scenarios.
- Text assistant with scoped MCP tools for selected meter data, weather context, illustrative utility costs and anomaly inference.
- Conservation-goal proposals with explicit approval or rejection before changes take effect.
- PyTorch LSTM autoencoder training, frozen inference artifacts and a typed FastAPI prediction endpoint.
- Manual-bill entry at `/analyze`, with validation and normalization for US gallons, CCF, cubic meters and liters, plus optional bill-only AI questions after explicit sharing consent.
- PDF and photo bill import from the homepage, with explicit OpenAI sharing consent, editable extracted fields and a required review before calculation. Supports PDF, PNG, JPEG and WebP reports up to 4 MiB.

## Requirements

- Node.js 22 or newer.
- pnpm 12.5.1, pinned in `package.json`.
- Python 3.12 or newer for the backend and ML workflows.
- An OpenAI API key and a Responses-compatible model for the optional text assistant. Report import also requires image/PDF input and structured-output support from that model.

The synthetic dashboard runs without credentials or a database.

## Quick start

Run commands from the repository root:

```sh
pnpm install --frozen-lockfile
pnpm dev
```

Open [localhost:3000](http://localhost:3000) for the landing page or [localhost:3000/demo](http://localhost:3000/demo) for the dashboard. Stop the server with `Ctrl+C`.

## Backend and text assistant

Create a Python environment and install the backend, MCP and agent dependencies:

```sh
python3 -m venv ml/.venv
ml/.venv/bin/python -m pip install -r ml/requirements-agent.txt
```

For bill analysis without AI configuration, start the backend and frontend in separate terminals, then open `/analyze`:

```sh
AQUAMIND_AGENT_ENABLED=0 PYTHONPATH=ml ml/.venv/bin/python -m uvicorn aquamind_ml.api:app --host 127.0.0.1 --port 8000 --workers 1
AQUAMIND_API_URL=http://127.0.0.1:8000 pnpm --filter web dev --hostname 127.0.0.1
```

To also enable the text assistant, follow the configuration below.

Create `.env.local` in the repository root, or edit the existing file, with:

```dotenv
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=your-responses-compatible-model
```

Keep this file private; local environment files are Git-ignored. The repository's [.env.example](.env.example) also lists placeholders for future integrations. Database, Redis and weather credentials are not used by the current local application.

Check that the assistant configuration is present without making a provider request:

```sh
PYTHONPATH=ml ml/.venv/bin/python -m aquamind_ml.agent_cli --check-config
```

Start the backend and frontend in separate terminals:

```sh
# Terminal 1: Python backend
AQUAMIND_AGENT_ENABLED=1 PYTHONPATH=ml ml/.venv/bin/python -m uvicorn aquamind_ml.api:app --env-file .env.local --host 127.0.0.1 --port 8000 --workers 1
```

```sh
# Terminal 2: Next.js frontend
AQUAMIND_API_URL=http://127.0.0.1:8000 pnpm --filter web dev --hostname 127.0.0.1
```

Visit `/demo` to use the synthetic-meter assistant, or `/analyze` to calculate a bill and optionally ask about it. Bill questions require the sharing checkbox; calculating usage alone does not call OpenAI. Live assistant requests incur provider usage. Stop both servers with `Ctrl+C` when finished.

The backend also runs without OpenAI configuration when `AQUAMIND_AGENT_ENABLED` is unset or `0`; session, goal and bill-normalization endpoints remain available. Anomaly inference additionally requires a frozen model artifact.

## Configuration

| Variable | Used by | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | Python backend | Server-side credential for live assistant requests |
| `OPENAI_MODEL` | Python backend | Responses-compatible model for the assistant |
| `AQUAMIND_AGENT_ENABLED` | Python backend | Set to `1` to enable the assistant; disabled by default |
| `AQUAMIND_DETECTOR_PATH` | Python backend | Optional frozen detector directory, such as `ml/artifacts/detector-v1` |
| `AQUAMIND_API_URL` | Next.js server | Backend URL used by the same-origin relay |

The frontend never receives the OpenAI key. Set `AQUAMIND_DETECTOR_PATH` on the backend process after generating the artifact using the [training and freeze instructions](docs/development.md#pytorch-model). Missing model artifacts disable anomaly inference while other configured features remain available.

## API

With the backend running, open [127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) for the OpenAPI contract.

- `GET /health`: process liveness.
- `GET /ready`: readiness of the anomaly detector; returns 503 when no detector is loaded.
- `POST /v1/anomaly/predict`: frozen-model inference on a daily meter window.
- `POST /v1/sessions`: create an ephemeral demo session.
- `POST /v1/agent/turn`: submit a session-bound assistant question.
- `POST /v1/bills/normalize`: validate and normalize one manually entered bill.
- `POST /v1/agent/bill`: answer one bill-only question with explicit sharing consent.

Goal review, approval decisions and assistant follow-ups are documented in the [development reference](docs/development.md). Session-bound endpoints require the bearer credential returned by session creation.

## Development

```sh
pnpm test
pnpm typecheck
pnpm lint
pnpm build
PYTHONPATH=ml ml/.venv/bin/python -m unittest discover -s ml/tests -v
```

The production frontend runs with `pnpm --filter web start` after building. If restricted worker ports prevent a Turbopack build, use `pnpm build --webpack`. The `next/font` build step requires network access when Google Fonts are not cached.

Keep changes focused and run the relevant checks before opening a pull request. Never commit credentials, downloaded datasets or generated model weights.

## Project structure

```text
apps/web/           Next.js frontend, dashboard and backend relay
ml/aquamind_ml/     Python data processing, models, FastAPI, MCP and agent
ml/tests/           Python unit and integration tests
ml/data/            Data manifests and versioned demo snapshot
ml/artifacts/       Locally generated model artifacts (Git-ignored)
evals/              Generated experiment summaries and local reports
docs/               Technical reference and dataset documentation
```

## Data and limitations

Demo meter readings and weather are synthetic. Chart highlights come from simulator labels; model predictions are a separate experimental signal. Utility calculations use a disclosed illustrative rate, not a user's actual tariff. Anomaly scores do not prove a physical leak or identify its fixture.

The manual bill form sends structured fields to a stateless calculation API without a model call. Document import separately requires consent to send the entire report to OpenAI; redact identifying details first. Extraction may make mistakes and its fields require review. Optional bill questions separately share the entered fields, normalized values and question with OpenAI. No bill history or uploaded files are saved by AquaMind; provider retention follows OpenAI's API data policy. Bill-only questions have no meter, weather, tariff, anomaly or goal tools. Fixture-image analysis and voice interaction are not implemented. Sessions and approved goals live in process memory; restarting the backend clears them. Use a single worker and loopback binding for local development; this configuration is not a public production deployment.

Assistant questions and requested evidence are sent to OpenAI. Avoid entering personal information into the demo. Application request logs omit prompts, bill values and credentials.

## Documentation

- [Development reference](docs/development.md): data generation, model training, API contracts, MCP scopes and agent behavior.
- [AMPds2 dataset and experiments](docs/datasets/ampds2.md): provenance, reproducible processing, experimental results and limitations. External data has its own license and attribution requirements.

## License

[GNU General Public License v3.0](LICENSE).
