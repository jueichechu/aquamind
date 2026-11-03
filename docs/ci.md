# Continuous integration

[CI](../.github/workflows/ci.yml) runs for pull requests targeting `main`, pushes
to `main` (including merges), and manual dispatches from the Actions tab.

| Check | Validation |
| --- | --- |
| Web checks | Frozen pnpm install, frontend tests, TypeScript, ESLint and production webpack build |
| Python checks | CPU PyTorch and agent dependencies, dependency consistency and the full Python suite |
| Cloud and Redis checks | Cloud dependencies without PyTorch, bill/MCP execution, provider and relay boundaries, and real Redis quota tests |
| CI gate | Succeeds only when all three jobs succeed; failures, cancellations and skipped jobs fail the gate |

Jobs use standard Ubuntu runners, bounded timeouts and read-only repository
permissions. Actions are pinned to commit SHAs. New runs cancel older runs for
the same pull request or branch. Tests use fictional inputs and mocked paid
providers; no OpenAI, Upstash or Render credentials are needed in GitHub Actions.
No models or downloaded household datasets are published by this workflow.

The Redis service is a disposable container belonging to the cloud job. It stores
only test counters and is removed when the job ends. This is separate from the
hosted Upstash database. CI does not merge pull requests, change repository rules,
or deploy services. Render service auto-deploys remain disabled in the Blueprint.

## Require CI before merging

Workflow files report results; repository protection enforces them. After the
first successful run makes the check available:

1. Open **Settings → Branches → Add classic branch protection rule**.
2. Set the branch name pattern to **main**.
3. Enable **Require a pull request before merging** and **Require status checks
   to pass before merging**. Select the **CI gate** check from GitHub Actions.
4. Enable **Require branches to be up to date before merging**.
5. Keep force pushes and deletions disallowed. Apply the rule to administrators
   as appropriate for the repository's maintenance policy.
6. Save and verify that an untested or failing pull request cannot merge.

A solo maintainer can require a pull request and checks without requiring an
approving review from another person. Enabling this workflow does not itself
enable branch protection or automatic merging. See GitHub's
[branch protection guide](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/managing-a-branch-protection-rule).

Review all three job results on the pull request before merging. After merging,
wait for the `main` run to pass, then deploy that commit deliberately and verify
the hosted app following the [deployment guide](deployment.md). Automated checks
do not replace browser review, hosted capacity checks or live provider verification.

## Real Redis integration checks locally

The integration tests execute the production quota Lua against Redis. They verify
the shared cap under concurrent independent connections, the non-expiring
date/count schema, next-day reset, and rejection of corrupt or backwards state.
They do not test Upstash's network, credentials, persistence guarantees or plan.
REST parsing, timeouts and failure behavior are covered separately with simulated
provider responses.

With Redis 7.4 and `redis-cli` installed, start a **disposable local server** in a
separate terminal; never point these checks at a hosted or production database:

```sh
redis-server --bind 127.0.0.1 --port 6380 --save "" --appendonly no
```

Then, from the repository root:

```sh
AQUAMIND_TEST_REDIS_PORT=6380 PYTHONPATH=ml:ml/tests \
  ml/.venv/bin/python -m unittest -v test_redis_budget_integration
```

Stop the server with Ctrl-C afterward. Tests use unique keys and delete only their
own keys; they never flush a database. Without the test-port variable, the regular
Python suite skips these optional integration tests. When configured, missing
tools or connection errors fail instead of silently skipping. CI always configures
the service and port, so these checks must execute there.
