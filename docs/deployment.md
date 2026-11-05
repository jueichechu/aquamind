# Deployment

The root [render.yaml](../render.yaml) targets **two Render Free web services**.
There is no paid private service, persistent disk or managed database. Next.js
relays requests to a Python bill/MCP/agent service with server authentication.
The cloud service omits PyTorch; training and detector code remain available locally.
The free deployment does not serve model weights or anomaly inference.

Live OpenAI extraction and answers are separately billed by OpenAI. AI activation
is an explicit backend environment setting. Start with **AQUAMIND_AGENT_ENABLED=0**
for manual calculations without external credentials.

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
3. Confirm the preview creates **aquamind-api-free** and **aqua**, both
   **Free** in **Oregon**, with no disk or paid database. Review updates carefully
   if those service names already exist. Other apps can stay in the workspace.
   When prompted for **AQUAMIND_AGENT_ENABLED**, enter **0** for this initial
   calculator-only setup. The application also defaults to disabled if unset.
4. Select **Deploy Blueprint** and wait for both services to show Live. No OpenAI
   or Upstash credentials are required for this first manual-only deployment.
5. Open the HTTPS URL on **aqua**. Render generates and shares a
   server-only relay secret automatically; do not put it in browser settings/code.
6. Open **/api/health**: once the API is awake, expect HTTP 200 with status ok.
   The web service's Render probe checks **/** for frontend liveness; /api/health
   checks API connectivity separately and can return 503 during an API cold start.
7. At **/analyze**, enter 8.5 CCF from June 1, 2026 to the exclusive end July 1.
   Expect 30 days and about 211.95 US gallons/day. At **/compare**, load examples,
   confirm the household assumption and expect 100 daily gallons and 0.00% change.
8. With AI enabled, the homepage starts a bounded readiness check on arrival.
   Visitors can select a report and give consent while the API wakes. Reading
   stays disabled until ready, and submission rechecks readiness before creating
   a session or sending the document. If startup remains unavailable, the file
   stays selected; **Try again** checks readiness only. Never retry paid requests
   automatically.

`GET /api/aquamind/v1/bills/readiness` checks connectivity and whether the backend
agent is configured, without a session, document, quota reservation or provider
call. Relay authorization and public admission limits still apply. The homepage
polls at least 10 seconds apart for at most two minutes, respects longer numeric
`Retry-After` values, and stops after success or navigation. It does not run an
idle keep-alive. Readiness does not guarantee remaining AI quota, provider health,
or availability between the check and submission. Both Free web services can
still sleep; the frontend itself may show Render's startup page before loading.

Both service definitions use **autoDeployTrigger: checksPass**. GitHub Actions
validates pull requests and pushes to main; Render waits for the linked branch's
checks before deploying application updates. Require **CI gate** in branch
protection. Existing deployments need the one-time setup below before this takes
effect. See [continuous integration](ci.md).

If the previous paid AquaMind services were already created, this new Blueprint
does **not** stop or delete them. Verify the replacement, then check Billing and
suspend or remove those old services separately, preserving needed data first.
Leave unrelated projects alone.

## Deploy application updates after CI

For existing services, apply this configuration once:

1. Keep **Blueprint → Settings → Auto Sync → No**. Review and merge the
   configuration PR after CI passes, then wait for the main-branch CI run to pass.
2. On the **existing** Blueprint, choose **Manual Sync**. Confirm the preview
   updates only the intended **aqua** and **aquamind-api-free** services, both
   **Free**, with no replacement, new resource, disk or plan upgrade.
3. On each service's **Settings** page, confirm the connected GitHub repository
   is **jueichechu/aquamind**, branch **main**, and **Auto-Deploy → After CI Checks
   Pass**. Auto-deploys require a connected Git provider; a service created from
   only a public repository URL needs that connection established first.
4. Verify the first deploy and its commit on each service's **Deploys** page.
   A Blueprint sync can deploy configuration changes; it is separate from the
   service's automatic application-code deployment setting.

After setup, merging an application-code PR triggers main CI, followed by Render
builds/deploys when those checks pass. The existing CI gate fails if a required
job fails, is cancelled or is skipped. Keep the YAML setting and Dashboard aligned;
a conflicting Dashboard-only change is overwritten by the next Blueprint sync.

With Blueprint Auto Sync off, later **render.yaml** infrastructure changes still
need a reviewed manual sync after CI. Application-code updates need no manual
deploy. This keeps automatic Blueprint configuration updates separate from the
service CI gate. See [automatic deploys](https://render.com/docs/deploys#automatic-deploys),
the [Blueprint field reference](https://render.com/docs/blueprint-spec#autodeploytrigger)
and [Blueprint sync behavior](https://render.com/docs/infrastructure-as-code#disabling-automatic-sync).

Wait for both services to report **Live** on the intended commit, then verify
**/api/health**, manual bill calculation, comparison, session creation and
revocation. The API's **/health** and frontend's **/** probes are liveness checks;
they do not establish that every feature or provider integration works. There is
no automatic hosted smoke-test workflow yet. AI activation and paid live checks
remain subject to the configuration and verification steps below.

## Replace an existing frontend service

The frontend service is named **aqua**; **aquamind-api-free** remains the
Python backend. The name requests a cleaner generated address but does not
guarantee **aqua.onrender.com**. Use the exact URL Render assigns. See Render's
[subdomain change request](https://feedback.render.com/features/p/ability-to-change-onrendercom-sub-domain).

For an existing deployment using **aquamind-web-free**:

1. Set the existing Blueprint's **Auto Sync** to **No** before merging a service
   replacement. Inspect the target workspace first. A service named **aqua**
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
   existing project key and a Responses-compatible model with document support,
   function calling and strict JSON-schema structured outputs.
4. Verify public mode, relay authorization, **AQUAMIND_USAGE_STORE=upstash** and
   the daily stage cap (template: 20). Before public activation, evaluate the
   [topic boundary](development.md#household-water-topic-admission) with the actual
   configured model, including unrelated/mixed requests, adversarial overrides
   and legitimate ambiguous water questions. Scripted tests do not measure live
   classification. Keep **AQUAMIND_AGENT_ENABLED=0** until these checks and quota
   readiness are reviewed. Then set **AQUAMIND_AGENT_ENABLED=1** on the backend
   service's **Environment** page and deploy with the updated environment.
   The Blueprint declares this flag with **sync: false**: an existing service's
   value is preserved on later syncs. This does not change the relay, quota,
   consent or approval controls. Set it back to **0** and deploy to disable AI.
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
New questions include a paid, tool-free topic check, even when refused; bill
questions allow that check and one answering request. Classification failures
stop answering/tool work without fallback or retry. Topic admission does not
establish visitor identity or stop one visitor exhausting shared capacity.

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

- **Cold start:** the homepage waits for bill readiness before sending a report.
  If startup times out, use **Try again** or manual entry; other routes may still
  need a deliberate resubmission after the API wakes.
- **Raw API 401:** expected without the host key. Use the frontend. For relay
  failures, check that both services share the generated secret and required flag.
- **Budget startup error:** verify Upstash URL/token and store type, keeping AI
  off until valid. Do not use a temporary SQLite file as a fallback.
- **Budget 503:** check provider availability/limits and eviction settings. Do not
  automatically retry or clear the ledger.
- **Memory failure:** inspect hosted metrics; never silently upgrade to paid.
  Revise the deployment scope or architecture if Free capacity is insufficient.
- **Updates:** merge through CI and confirm automatic deploys finish on the
  intended commit for both services. Sync reviewed Blueprint configuration
  changes separately, then verify health and features again.
