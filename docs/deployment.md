# Deployment

The root [render.yaml](../render.yaml) serves the exported Next.js website and its
Python API from one process in the existing **aqua** Render Free web service.
Node builds the HTML, CSS and JavaScript during deployment; no Node server runs
in the final image. The Python runtime includes FastAPI, MCP, CPU-only PyTorch and
the pinned experimental synthetic detector. Browser requests retain the existing
same-origin API routes. The [hosting adapter](../ml/aquamind_ml/web.py) dispatches
allowlisted API requests in process; no second server or remote wake-up is needed.

The former **aquamind-api-free** service is retained during migration as a fallback
and server-side configuration source. It has automatic application deploys disabled.
The website does not call or wake that remote service. Keeping its definition avoids
silently deleting or replacing infrastructure; its stored environment values remain
available to Blueprint references even while its process sleeps. Do not delete it
while those references exist. No paid service, disk or managed database is added.

## Startup and readiness

Uvicorn completes the API lifespan before opening its public listener. The hosting
adapter verifies the exported pages, process health, detector readiness when
inference is enabled, and bill readiness when AI is enabled before startup yields.
These checks do not create sessions, reserve quota, upload a document or call
OpenAI. An unavailable enabled feature fails startup rather than exposing the page.

The container runs as a non-root user with read-only model files. Only one Python
worker serves the exported files and API. There is no package-manager download,
model download or training on wake. The entrypoint passes SIGTERM directly to
Uvicorn for graceful shutdown. The Render health check remains **/api/health**.

After inactivity, Render can show its own loading screen before the application
appears. Once the application is served, the local backend has completed the
startup checks. This does not test OpenAI/Upstash availability or remaining quota.
Provider outages and later restarts still require the existing error handling.

The homepage continues to check bill readiness before reading a report. Visitors
must select a file and give sharing consent. Submission rechecks readiness before
creating a session or uploading. Waiting never uploads automatically; an unavailable
service leaves the file selected and offers a deliberate readiness retry. Existing
70-second relay, 75-second browser and two-minute total readiness deadlines remain.
These bounded, read-only checks are not an idle keep-alive. Paid requests and writes
are never automatically retried after uncertain outcomes.

## Free-tier limits

- Render Free web services have 512 MB RAM, sleep after 15 minutes without inbound
  traffic, and can take about a minute to wake. Model loading adds startup work.
  A local bounded container check is not a hosted availability or load guarantee.
- The workspace shares **750 Free running hours/month** across all Free services.
  The combined website consumes one running service's hours. The migration fallback
  and unrelated apps consume additional hours whenever awake.
- Build minutes and bandwidth have included limits. Overages can incur charges
  when a payment method is present. Verify Billing and spend settings; do not
  upgrade compute or enable paid add-ons automatically.
- Free compute is suitable for hobby/staging use, without always-on availability.
  Live extraction and answers are separately billed by OpenAI.

See [Render Free limits](https://render.com/docs/free),
[Docker deployment](https://render.com/docs/docker) and
[health checks](https://render.com/docs/health-checks).

## Migrate the existing deployment

1. Inspect the existing Blueprint, resource IDs, Auto Sync setting and live versions.
   The change should update **aqua** from Node to Docker on **Free**, preserving its
   existing website URL, and disable automatic application deploys on the old API.
   It should not create, replace or remove a service, disk, database or paid plan.
   Render supports [changing runtimes](https://render.com/docs/native-runtimes#changing-a-services-runtime)
   on an existing web service.
2. Review and merge the configuration PR after CI passes. With Auto Sync enabled
   and the initial Blueprint already approved, Render applies configuration changes
   automatically. With Auto Sync disabled, review and apply a manual sync. Keep the
   existing intended setting; application-code auto-deploy and Blueprint Auto Sync
   are separate controls.
3. The combined service takes its existing AI-enabled flag, model name, OpenAI key,
   Upstash URL/token, relay secret and daily stage cap from **aquamind-api-free**
   through server-only **fromService** references. No credential value belongs in
   Git, browser code, build arguments, chat or logs. Existing source values are
   preserved; **sync: false** does not overwrite them on an existing service.
4. Wait for the actual **aqua** Docker deploy to be **Live** on the intended commit.
   A successful sync or deploy trigger alone is insufficient. Check memory, restart
   events and startup logs, then verify health, bill readiness, pages, manual bill
   calculations, comparison, session isolation and revocation.
5. Verify actual idle shutdown and a fresh wake before signing off on startup.
   Deliberately test live extraction using a fictional report and verify the review
   gate. Live provider calls cost money; do not retry an uncertain request.
6. Keep the old API available as a migration fallback until the combined deployment
   is verified. Later retirement requires moving the referenced settings to the
   combined service or a shared environment group, removing those references and
   separately reviewing suspension/removal. Removing a Blueprint definition alone
   does not delete a deployed service.

For a new deployment, create the Blueprint with AI initially disabled and provide
its source configuration when prompted. Use blank provider values only while AI
is disabled. The built model supports manual calculations and the synthetic demo;
OpenAI and Upstash are necessary for public AI activation.

## Deploy application updates after CI

The combined service uses **autoDeployTrigger: checksPass**. GitHub Actions checks
PRs and pushes to **main**. Require **CI gate** in branch protection and confirm
**Auto-Deploy → After CI Checks Pass** on the existing service. Merging application
code then triggers CI followed by deployment; no manual deploy is normally needed.
See [continuous integration](ci.md).

Blueprint Auto Sync can apply infrastructure edits separately from the service CI
gate. Inspect the resource diff before merging configuration. A failed build keeps
the prior working deployment; still inspect the actual live commit after any failure.
The migration fallback deliberately uses **autoDeployTrigger: off**. Its Blueprint
configuration can still trigger a deploy when changed. No periodic wake-up job or
automatic paid provider smoke test is configured.

## Enable OpenAI with a free durable quota store

Render Free has no persistent disk. Upstash Redis holds the durable AI-stage counter
without resetting it when the application sleeps or redeploys.

1. Create an Upstash Redis database on **Free**, verify its current allowances,
   keep eviction disabled and paid upgrades off. See [pricing](https://upstash.com/pricing/redis),
   [durability](https://upstash.com/docs/redis/features/durability) and
   [eviction](https://upstash.com/docs/redis/features/eviction).
2. On the configuration-source API service, set **UPSTASH_REDIS_REST_URL** to its
   official HTTPS REST URL and **UPSTASH_REDIS_REST_TOKEN** to the read/write REST
   token. Set **OPENAI_API_KEY** and **OPENAI_MODEL** to the existing project key
   and a Responses-compatible model supporting documents, tools and structured output.
3. Preserve public mode, relay authorization, **AQUAMIND_USAGE_STORE=upstash** and
   the daily stage cap. Keep AI disabled until the [topic boundary](development.md#household-water-topic-admission)
   and quota configuration are reviewed with the intended model. Then set
   **AQUAMIND_AGENT_ENABLED=1** on the source service.
4. Blueprint **fromService** values refresh on sync, not immediately when the source
   value changes. Sync the reviewed Blueprint and verify the combined service's new
   deploy. Setting the source flag back to **0** and syncing disables public AI.
   Preserve the intended Auto Sync setting; no secrets need to enter agent context.

Only a UTC day number and attempted-stage count are stored in the single Redis hash
**aquamind:paid-stages:v1**. Reports, prompts, bill values, session tokens and OpenAI
keys are not stored there. Instances sharing this database/key share the cap.
Reservation happens before provider work; failures and cancellation are not refunded.
Do not clear or restore the ledger to reset quota. Redis errors, quota exhaustion
and uncertain outcomes stop model work without retry or fallback.

One stage can contain several bounded model calls, so the stage cap is not a dollar
cap. Questions include a paid, tool-free topic check; bill questions allow that
check and one answer. Readiness checks do not spend AI quota. Topic admission is
not visitor authentication or protection against one visitor exhausting shared quota.

## Runtime and request boundaries

Use one API worker. Sessions, temporary goals and approval checkpoints disappear
when the combined service sleeps, restarts or redeploys; reload to create a new
session. The durable AI quota remains in Upstash. No bill history or files are saved.

The public listener is the Python hosting adapter. It preserves the Next.js relay's
endpoint/method allowlist, host-only relay secret, session bearer forwarding,
actual-byte body limits, concurrency cap, sanitized failures and no-retry behavior.
Browser-supplied relay keys, cookies and forwarded identity headers are ignored.
Every internal API **/v1/** route retains its own relay/session authorization and
public admission limits. Raw API, inference and documentation routes are not mounted
publicly. Browser traffic uses HTTPS; the internal ASGI dispatch never opens a
network connection. Consent, review and human approval remain required.

Known page routes and navigation payloads use **Cache-Control: no-store**, so a fresh
navigation reaches the ready process. Hashed **/_next/static/** assets can be cached
immutably. The **/analyze?example=1** link is interpreted in the browser and retains
its existing fictional example values. Local Next.js development keeps its original
server routes; only the container's build-stage copy omits them for static export.

Public mode preserves eight active requests per layer, actual-byte limits and a
15-second body deadline. Rolling 60-second API limits remain 60 requests, six new
sessions and six combined AI/import requests. Existing stage limits remain one
active stage/session, two/host, eight stages/session and 100/process. Overload
returns 429, incomplete bodies 408 and oversized bodies 413. These limits do not
guarantee fairness, unlimited free capacity or protection from every traffic spike.

The Docker build installs the release pinned in [model-release-v1.json](../ml/model-release-v1.json).
Archive, manifest, weights and frozen runtime checksums are verified. A mismatch
fails the build. Weights are neither trained nor downloaded at startup and remain
outside Git history. The model is experimental and synthetic-trained; scores are
not leak probabilities or fixture diagnoses. Dashboard scenario highlights remain
rule-defined. The AMPds2 experiment is separate and unchanged.

**AQUAMIND_INFERENCE_ENABLED=0** remains supported by the Python host when the
detector path is omitted. The SQLite ledger option remains available for local or
persistent-storage deployments; it is never a fallback for public AI on Free.
Local two-terminal development continues to work as documented in the README.

## Local container verification

Run from the repository root:

```sh
docker build --platform linux/amd64 -t aquamind-combined -f services/combined/Dockerfile .
```

The build downloads the public checksum-pinned detector and installs locked frontend
and pinned direct Python dependencies. It needs no private credentials. Supply
server credentials only at runtime. Validate startup, feature behavior and whole
container memory under the intended resource limits before changing hosted compute.

## Troubleshooting

- **Startup never finishes:** inspect backend startup events. Missing
  model or enabled-AI configuration intentionally prevents the website from opening.
  Do not bypass the readiness gate or upgrade compute automatically.
- **Page open, later request fails:** the service may have restarted, a provider may
  be unavailable, or an existing quota may be exhausted. Use the displayed error;
  never automatically resubmit an uncertain paid request.
- **Raw API unavailable:** expected; raw API routes are not mounted publicly. Use the
  existing same-origin routes. The old API is not a dependency of website requests.
- **Budget errors:** verify the source settings and sync/deploy, Upstash availability,
  quota and eviction policy. Never use temporary SQLite or reset the ledger.
- **Memory failure:** inspect whole-service metrics and restart/OOM events. Revise
  architecture or scope if Free capacity is insufficient; do not silently upgrade.
- **Updates:** confirm CI and the actual combined service deploy finish successfully
  on the intended commit. Configuration references refresh only on Blueprint sync.
