# Deployment

The root [render.yaml](../render.yaml) defines a public Next.js Node service and a
private FastAPI service in the same Render region. This initial configuration
supports manual bill analysis, manual comparisons and the synthetic dashboard.
**AI answers and document extraction are disabled.** Public request-admission and
paid-AI abuse controls remain launch work; this is a staging configuration, not a
completed production release.

## Before provisioning

- Create a [Render account](https://dashboard.render.com/) and connect GitHub.
  Grant repository access to `jueichechu/aquamind` only if that is the intended
  source. No Render API token is needed for dashboard deployment.
- Merge the deployment configuration into `main` before selecting that branch.
- Review the paid service plans in the Blueprint creation screen. The template
  selects 512 MB for Next.js and 2 GB for Python/PyTorch. Capacity still needs
  deployed measurement; these are starting sizes, not measured guarantees. Check
  [current pricing](https://render.com/pricing) before creating resources.
- Keep `AQUAMIND_AGENT_ENABLED=0`. Do not add an OpenAI key or enable AI until public
  request controls and the live-test plan are ready. Calculations need no key.
- Use a new Blueprint without existing services of the same names. If those names
  are already used in the workspace, rename both services and the `fromService`
  reference before syncing. Review any existing environment variables separately:
  a Blueprint does not erase omitted secrets or detector-path settings.

## Create the staging deployment

1. Open Render Dashboard and choose **New → Blueprint**.
2. Select `jueichechu/aquamind`, branch **main**, Blueprint path **render.yaml**.
   Leave the repository root unchanged; both services build from the root.
3. Confirm two services: `aquamind-api` is **Private Service / Python** and
   `aquamind-web` is **Web Service / Node**. Both use **Oregon**. Review the displayed
   recurring charges before selecting **Deploy Blueprint**.
4. Wait for the API build and startup, then the web build and its health check.
   No environment values need to be pasted for this initial deployment.
5. Open the HTTPS URL displayed on `aquamind-web`. The API intentionally has no
   public URL. Render injects the private API `host:port`; the web start command
   converts it into its server-only `AQUAMIND_API_URL`.
6. Check `/api/health`: expect HTTP 200 and `{"status":"ok"}`. This checks backend
   liveness through Next.js; it does not certify AI or detector availability.
7. On `/analyze`, enter 8.5 CCF for June 1–30, 2026 using an exclusive end date of
   July 1. Expect 30 days and about 211.95 US gallons/day. On `/compare`, load the
   examples, confirm the same-household assumption, and expect 100 US gallons/day
   for both periods and 0.00% change. Check `/demo` as well.
8. Keep the URL as staging until public request controls and deployed verification
   are complete. Upload extraction and AI questions are unavailable with these
   defaults; an unavailable response is not a successful AI smoke test.

The [Blueprint reference](https://render.com/docs/blueprint-spec) documents the
service settings and [private networking](https://render.com/docs/private-network)
describes the internal connection. Normal Git pushes do not deploy automatically
in this template: `autoDeployTrigger: off` requires deliberate deployment from the
dashboard. This setting does not prevent the initial Blueprint deployment.

## Runtime and data boundaries

Use exactly one backend instance and one Uvicorn worker. Sessions and approval
state live in process memory; restarts, service replacement and deployments clear
them. Users must reload and start a new session. Zero-downtime replacement can
temporarily route traffic across old and new instances; do not assume a session
survives it. Shared storage is required before scaling backend instances/workers.

The Python build installs the pinned CPU PyTorch package before the remaining
agent dependencies, avoiding a CUDA installation. Existing dependency pins and
model source checksums are preserved. The initial deployment includes no model
weights, external datasets or private local files. `/ready` returns 503 without a
detector artifact; it is **not** the health check for a bill-only deployment.
The private API uses a TCP service check; the public `/api/health` checks its HTTP
endpoint. Public health responses contain no upstream details or credentials.

Do not upload `.env.local`, `.codex-local/`, instruction files or local artifacts.
Git-based builds use the committed repository. Bill documents and entered data
must not be added to durable storage or logs. The service disables Uvicorn access
logs; application tracing records request ID, status and duration without bodies.

## Enabling AI later

After public admission controls are implemented and tested, add `OPENAI_API_KEY`
and `OPENAI_MODEL` under **aquamind-api → Environment**, and deliberately update
`AQUAMIND_AGENT_ENABLED` in the Blueprint to `1` before syncing. Do not put a key in
the web service, `NEXT_PUBLIC_*`, Git or a chat message. Existing process counters
limit development requests but are not a distributed rate limiter or a dollar
spending cap. Do not rely on them alone for an anonymous public AI endpoint.

Use a fictional report for an explicitly authorized live extraction check; this
incurs provider usage. Verify consent, extraction review and calculation through
the deployed URL. Live model accuracy is separate from mocked integration tests.
Anomaly tools additionally need a separately provisioned, verified frozen model;
do not substitute experimental AMPds2 artifacts or imply the initial deployment
serves a trained detector.

## Troubleshooting and updates

- **Web health 503:** check the API startup logs, both service regions and the
  injected `AQUAMIND_API_HOSTPORT`. Keep internal addresses out of browser code.
- **API import failure:** check the Python build log and CPU wheel installation;
  do not silently change the pinned PyTorch version to make deployment pass.
- **Session unavailable:** reload after a backend restart. Never retry an uncertain
  paid request or approval automatically.
- **Memory pressure:** inspect Render metrics and resize deliberately. Builds and
  runtime memory need separate checks.
- **Updating code:** run repository checks first, push reviewed code to `main`,
  then deploy the desired commit using each service's Manual Deploy menu. Verify
  health and calculations after both services update.
- **Stopping staging:** suspend the services in Render when no longer needed and
  review billing. Stopping local development servers does not stop hosted services.
