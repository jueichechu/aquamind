# Deployment

The root [render.yaml](../render.yaml) targets **two Render Free web services**.
There is no paid private service, persistent disk or managed database. Next.js
relays requests to a Python bill/MCP/agent service with server authentication.
The cloud service omits PyTorch; training and detector code remain available locally.
The free deployment does not serve model weights or anomaly inference.

Live OpenAI extraction and answers are separately billed by OpenAI. AI starts
disabled so initial manual calculations need no external credentials.

## Free-tier limits

- Render Free services have 512 MB RAM, sleep after 15 minutes without traffic,
  and can take about a minute to wake. Hosted capacity still needs verification.
- The workspace shares **750 Free running hours/month** across these two services
  and any existing Free apps. Two continuously awake services exceed that allowance.
  Spun-down services do not consume running hours.
- Build minutes and bandwidth have included limits. Usage overages can incur
  charges when a payment method is present. For strict zero-hosting charges,
  consider a separate Hobby workspace without a payment method and verify Billing
  settings. Do not upgrade compute or enable paid add-ons.
- Free compute is suitable for hobby/staging use, without always-on availability.

See [Render Free limits](https://render.com/docs/free) and
[compute plans](https://render.com/docs/compute-plans). Free hosting means staying
within provider allowances; it does not include OpenAI usage.

## Initial manual-only deployment

1. Connect the repository to the intended Render workspace.
2. After the configuration is merged, choose **New → Blueprint**, repository
   **jueichechu/aquamind**, branch **main**, path **render.yaml**, and a new Blueprint
   name such as **aquamind-free**. Both builds run from the repository root.
3. Confirm the preview creates **aquamind-api-free** and **aquamind**, both
   **Free** in **Oregon**, with no disk or paid database. Review updates carefully
   if those service names already exist. Other apps can stay in the workspace.
4. Select **Deploy Blueprint** and wait for both services to show Live. No OpenAI
   or Upstash credentials are required for this first manual-only deployment.
5. Open the HTTPS URL on **aquamind**. Render generates and shares a
   server-only relay secret automatically; do not put it in browser settings/code.
6. Open **/api/health**: once the API is awake, expect HTTP 200 with status ok.
   The web service's Render probe checks **/** for frontend liveness; /api/health
   checks API connectivity separately and can return 503 during an API cold start.
7. At **/analyze**, enter 8.5 CCF from June 1, 2026 to the exclusive end July 1.
   Expect 30 days and about 211.95 US gallons/day. At **/compare**, load examples,
   confirm the household assumption and expect 100 daily gallons and 0.00% change.
8. If the first request reports unavailable during a cold start, allow startup
   and submit deliberately again. Never retry paid requests automatically.

Automatic service deploys are off. Blueprint edits can still sync automatically;
set **Blueprint → Settings → Auto Sync → No** if configuration must also be manual.
See the [Blueprint reference](https://render.com/docs/blueprint-spec).
GitHub Actions checks pull requests and pushes to main; it does not merge or
deploy them. Require the **CI gate** status in repository branch protection and
deploy a passing main commit deliberately. See [continuous integration](ci.md).

If the previous paid AquaMind services were already created, this new Blueprint
does **not** stop or delete them. Verify the replacement, then check Billing and
suspend or remove those old services separately, preserving needed data first.
Leave unrelated projects alone.

## Replace an existing frontend service

The frontend service is named **aquamind**; **aquamind-api-free** remains the
Python backend. The name requests a cleaner generated address but does not
guarantee **aquamind.onrender.com**. Use the exact URL Render assigns. See Render's
[subdomain change request](https://feedback.render.com/features/p/ability-to-change-onrendercom-sub-domain).

For an existing deployment using **aquamind-web-free**:

1. Set the existing Blueprint's **Auto Sync** to **No** before merging a service
   replacement. Inspect the target workspace first. A service named **aquamind**
   might already exist; verify its service ID, repository, runtime and ownership
   before proceeding. A Blueprint can update an existing same-name service.
   Do not overwrite another project's service or assume a suspended URL is free.
2. Keep the working frontend and **aquamind-api-free** running. Review and merge
   the new configuration through CI, then manually sync the **existing** Blueprint.
   Expect the frontend replacement on **Free**, with the backend and its existing
   relay secret preserved. Do not create a second copy of the whole Blueprint.
3. Review the assigned URL. If Render adds a suffix or the desired name is taken,
   stop the cutover and keep the original working site. Deleting the original
   frontend does not free a different service's subdomain.
4. Once the replacement is Live, verify **/api/health**, manual bill analysis and
   comparison at its actual HTTPS URL. The generated relay references connect
   it to the existing backend; do not copy credentials into browser code.
5. Only after successful verification, retire **aquamind-web-free**. Removing its
   definition does not delete the deployed service. Confirm it is no longer
   managed by the Blueprint before deletion, or a later sync can recreate it.
   Both frontends consume shared Free running hours while they coexist.

See [Blueprint resource lifecycle](https://render.com/docs/infrastructure-as-code#deleting-resources).
Recreating a service is a deployment operation; changing its display name alone
does not establish a new public address. No custom-domain purchase is required
to try a new generated address.

## Enable OpenAI with a free durable quota store

Render Free services have no persistent disk. Upstash Redis can hold the durable
AI-stage counter without relying on a temporary file or resetting it on app sleep.

1. At [Upstash](https://console.upstash.com/), create a Redis database on **Free**.
   Published allowances are 250 MB and 500K commands/month; verify current limits
   and availability in your account. Keep **eviction disabled** and paid upgrades
   off. See [pricing](https://upstash.com/pricing/redis),
   [durability](https://upstash.com/docs/redis/features/durability) and
   [eviction](https://upstash.com/docs/redis/features/eviction).
2. Under **aquamind-api-free → Environment**, set **UPSTASH_REDIS_REST_URL** and
   **UPSTASH_REDIS_REST_TOKEN** from that database. Use its normal HTTPS REST URL
   ending in .upstash.io and the **read/write** REST token, not the read-only token.
   Never put credentials in URLs, Git or chat.
3. On that same API service, set **OPENAI_API_KEY** and **OPENAI_MODEL** using the
   existing project key and a Responses-compatible model with document support.
4. Verify public mode, relay authorization, **AQUAMIND_USAGE_STORE=upstash** and
   the daily stage cap (template: 20). Change **AQUAMIND_AGENT_ENABLED** in the
   Blueprint to **1**, publish the reviewed configuration and sync deliberately.
   A dashboard-only flag change would be overwritten on the next Blueprint sync.
5. Verify health, then explicitly authorize a live test using a fictional report.
   Check consent, extracted fields, review and calculation. OpenAI bills this use;
   real extraction accuracy is separate from mocked integration tests.

Only a UTC day number and attempted-stage count are stored in one Redis hash,
**aquamind:paid-stages:v1**. No reports, prompts, bill values, session tokens or
OpenAI credentials go to Upstash. A server-side Lua operation reserves a stage
before provider work; failures/cancellation are not refunded. Redis errors,
quota exhaustion, malformed responses and uncertain network outcomes stop model
work without retry or fallback. Keep eviction disabled and never delete or restore
the ledger to reset quota. Instances using this database/key share the cap.
A stage can include multiple bounded model calls: this is **not a dollar cap**.

Tests need no live Upstash/OpenAI calls. Actual provider connectivity, credentials
and Free plan settings must be verified after deployment.

## Runtime and request boundaries

Keep one API instance/worker. Sessions, goals and approval checkpoints disappear
when the API sleeps, restarts or redeploys; reload to start a new session. Durable
AI quota survives these events in Upstash.

Both services are public because Free private services are unavailable. Every API
/v1 route requires a host relay secret plus the existing session bearer credential
where applicable. Next.js supplies its own secret and ignores browser-supplied
relay headers. Health and contract metadata remain public. The browser continues
to use the same-origin relay; no browser-to-API CORS or credentials are introduced.
Both network hops use HTTPS. Relay authentication does not replace consent or
human approval before state changes.

Public mode keeps eight active requests per layer, actual-byte caps and a 15-second
body deadline. Rolling 60-second API limits are 60 requests, six new sessions and
six combined AI/import requests. Existing host/session limits remain: one active
stage/session, two/host, eight stages/session and 100/process. Overload returns
429, incomplete bodies 408 and oversized requests 413. Numeric Retry-After hints
pass through without automatic retries. Limits are shared across visitors and do
not guarantee fairness or replace edge DDoS controls. Health consumes no AI quota.

**AQUAMIND_INFERENCE_ENABLED=0** avoids PyTorch in the cloud; /ready and anomaly
prediction remain unavailable. Full local inference defaults to enabled and uses
ml/requirements-agent.txt. Serving a detector later needs the full dependencies,
a verified frozen artifact and measured capacity. Frozen sources are unchanged.
The SQLite quota option remains supported with **AQUAMIND_USAGE_STORE=sqlite** and
an absolute **AQUAMIND_USAGE_DB** path on persistent storage. Free hosting never
bypasses the durable-ledger requirement for public AI. No bills or files are saved.

## Troubleshooting

- **Cold start:** allow the API to wake and resubmit manually.
- **Raw API 401:** expected without the host key. Use the frontend. For relay
  failures, check that both services share the generated secret and required flag.
- **Budget startup error:** verify Upstash URL/token and store type, keeping AI
  off until valid. Do not use a temporary SQLite file as a fallback.
- **Budget 503:** check provider availability/limits and eviction settings. Do not
  automatically retry or clear the ledger.
- **Memory failure:** inspect hosted metrics; never silently upgrade to paid.
  Revise the deployment scope or architecture if Free capacity is insufficient.
- **Updates:** validate, push reviewed code to main, deploy each desired commit
  manually and verify health and features again.
