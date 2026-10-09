# Staging-only GitHub Actions historical model evaluation

**Purpose:** run four-fold, forward-only model research and pre-match odds
evidence checks from GitHub Actions instead of a local Windows terminal.
Outputs are aggregate reports only. Nothing trains, promotes, deploys,
publishes, settles or generates real booking codes.

## Security boundaries

- Trigger: **manual** `workflow_dispatch`, only on branch
  `feature/daily-tier-reach-and-builder-supply-20261009`.
- Environment: `betsightly-staging-evaluation`.
- Database: must resolve to **`betsightly_db_staging`** via a *dedicated
  SELECT-only login*. Production credentials must never be used.
- The job also requests PostgreSQL `default_transaction_read_only=on`
  through `PGOPTIONS` and verifies `SHOW transaction_read_only`, superuser
  and write privileges on both evidence tables before querying.
- GitHub token: `contents: read`; no checkout credential persistence.
- No `push`, `pull_request`, scheduled, or background triggers.
- Artifacts: `summary.md`, `walkforward.json`, `evidence.json`,
  and (in `all` mode) `settlement_dry_run.json`;
  14-day retention, no per-fixture predictions or connection strings.
- Comparisons against actual champion and real odds remain **blocked**
  until matched, settled, verified historical evidence exists.

## One-time GitHub setup (account owner)

1. Create a dedicated Postgres login using the **staging** database's SQL
   console/admin connection. Example, **only against `betsightly_db_staging`**:

   ```sql
   CREATE ROLE betsightly_eval_readonly LOGIN PASSWORD '<strong unique password>';
   GRANT CONNECT ON DATABASE betsightly_db_staging TO betsightly_eval_readonly;
   GRANT USAGE ON SCHEMA public TO betsightly_eval_readonly;
   GRANT SELECT ON
     public.external_historical_results_v1,
     public.market_shadow_forecasts_v1
     TO betsightly_eval_readonly;
   ```

   Ensure no inherited write grants, `SUPERUSER`, `CREATEDB` or other
   elevated privileges exist for this login. A staging DB administrator may
   need to do this through approved organization access rather than Render
   read-only querying. **Never paste passwords or connection URLs into chat.**

2. In GitHub **Settings → Environments**, create
   `betsightly-staging-evaluation`; configure a deployment branch restriction
   allowing only the exact staging feature branch and optionally reviewer
   approval.
3. Add an **environment secret** named
   `BETSIGHTLY_STAGING_READONLY_DATABASE_URL`, pointing to the staging DB's
   **external** PostgreSQL connection endpoint and the *read-only* login.
   GitHub-hosted runners cannot reach Render's private-only internal DB URL.
   Make sure Render network policies allow access securely.
4. GitHub requires a workflow file to exist on the **repository's default
   branch** before manual `workflow_dispatch` runs are available. The current
   implementation lives only on the staging feature branch. Register **only
   the reviewed workflow entrypoint** on the default branch after explicit
   authorization (don't merge the entire feature PR just to enable a button).
   A commit to a production auto-deploy branch can still trigger deployment,
   even if it changes only workflow files; coordinate the release boundary.
5. From **Actions → Staging Model Evaluation → Run workflow**, choose the
   staging feature branch and `all` (or `walkforward` / `evidence`).
   Download the artifact from the completed job or inspect its job summary.

## Result interpretation

- Pooled train-rate benchmark, train-only league-specific benchmark and
  forward-time folds **measure historical forecast loss**, not betting profit.
- Odds evidence audit intentionally reports `CHAMPION_COMPARISON_BLOCKED`
  while no settled same-fixture pre-match evidence exists.
- No automatic updates to `devil`, published slips, user Builder tickets,
  or model artifacts occur.

## Maintainer dry-run

The checked-in test `tests/test_staging_readonly_actions_runner.py`
exercises all guardrails and report composition with mocked data. Backend
CI runs this test on PRs without connecting to any staging database.

Workflow file: `.github/workflows/staging-model-evaluation.yml`.
Python entrypoint: `python -m scripts.run_staging_readonly_evaluation --mode all`.

## Phase 9: verified market-shadow settlement

The `all` evaluation now runs an additional **read-only** settlement preview
over mature rows from `public.market_shadow_forecasts_v1`. It uses verified
ESPN 90-minute final scores, matches the *same league, normalized home/away
names and kickoff within 90 minutes*, and requires a completed event. A
missing, ambiguous, unsupported or provider-unavailable result stays pending.
The report distinguishes `would_settle`, `would_void` and each unresolved
reason. The GitHub environment secret remains a SELECT-only database role;
the workflow **never settles or writes to PostgreSQL**.

For a local authorized staging operator only, the separate command is:

```powershell
# After setting DATABASE_URL to the correct staging admin URL without printing
# it and setting the staging preflight environment used by this project:
python -m scripts.settle_staging_market_shadow --dry-run
```

Only after inspecting the dry-run, with distinct explicit authorization and
a writable staging role (NEVER the read-only GitHub role), may the operator use
`--write-staging`. The command requires
`BETSIGHTLY_STAGING_MARKET_SHADOW_WRITE=CONFIRM_VERIFIED_SHADOW_SETTLEMENT_ONLY`,
rejects execution under GitHub Actions, verifies the connected database is
`betsightly_db_staging`, and updates **only** matching pending evidence rows.
Reruns are idempotent. It never settles official product slips, publishes,
books, promotes models or modifies production.

Even after prospective shadow outcomes are settled, a true
champion/challenger comparison remains blocked until synchronized
same-fixture probability pairs and prices are collected and verified.

## Phase 9: separate prospective champion/challenger comparison

The GitHub evaluation now checks `public.football_first_shadow_observations`
**separately** from the SportyBet market-shadow prices. This warehouse already
contains paired, settled 1X2 probabilities for existing football-first runtime
versions, but their fixtures overlap between versions. The evaluation reports
fixture counts and multiclass Brier/log loss **per model version**, never pools
the same match twice across versions and never authorizes promotion.

The existing GitHub evaluation login was originally granted SELECT only on
the two market/history evidence tables. If its output says
`STAGING_READONLY_SELECT_GRANT_REQUIRED`, a staging database administrator
may run **only on betsightly_db_staging**:

```sql
GRANT SELECT ON TABLE public.football_first_shadow_observations
TO betsightly_eval_readonly;
```

Do not change the GitHub secret, assign admin credentials to Actions, or
grant write privileges. The evaluation preflight explicitly refuses write
permissions on all three evidence tables. The optional paired report remains
permission-aware and does not fail the rest of the run if access is absent.

A paired probabilistic comparison is **not** proof of sportsbook profitability.
There is still no verified same-fixture closing-line cohort between this
football-first table and the separately captured SportyBet prices.

## Repeatable local staging settlement (PowerShell)

Instead of pasting the long manual environment setup each day, pull the current
staging feature branch and use its guarded helper:

```powershell
git fetch origin
git switch feature/daily-tier-reach-and-builder-supply-20261009
git pull --ff-only origin feature/daily-tier-reach-and-builder-supply-20261009
.\\scripts\\settle_staging_market_shadow.ps1 -DryRunOnly
# After reviewing the dry-run, repeat without -DryRunOnly:
.\\scripts\\settle_staging_market_shadow.ps1
```

The PowerShell helper prompts for the **staging administrator database URL**
without echoing it, verifies the branch and the dry-run response, and requires
typing `SETTLE STAGING` before a write. It restores prior process environment
variables and clears the temporary secret. It cannot change production:
the backend additionally checks the actual connected PostgreSQL database and
the explicit staging-only write flag. Do not use the read-only GitHub secret for
a manual write; GitHub Actions itself remains SELECT-only.

If your PowerShell session blocks script execution by policy, use your
organization's approved local execution procedure. Do not weaken machine-wide
PowerShell security policy merely to run this helper.

## Phase 9: append-only SportyBet odds-history capture (staging)

The module `scripts.capture_staging_odds_history` prepares a dedicated
`public.sportybet_odds_history_v1` table. It is **separate** from immutable
model forecasts (`market_shadow_forecasts_v1`), the official predictions,
booking codes, and the existing live bookmaker cache.

Important integrity rules:

- It reads **only** the existing, *complete* `sportybet_board` cache; it
  neither calls the provider nor triggers a pipeline or a cache refresh.
- Each captured price is stamped with the **original source fetched_at**
  from cache and its immutable source snapshot ID, never the CLI run time.
- A source must have matching metadata/cache timestamps, a complete board,
  and be at most six hours old. Invalid odds, missing event IDs, and matches
  near/past kickoff do not become evidence.
- A unique primary key
  `(snapshot_id, sportybet_event_id, market)` plus
  `INSERT ... ON CONFLICT DO NOTHING` makes retries idempotent. There are
  no updates/deletes to the odds warehouse.
- Staging-only DB identity and the staging board preflight must pass.
  `--write-staging` requires separate
  `BETSIGHTLY_STAGING_ODDS_HISTORY_WRITE=CONFIRM_APPEND_ONLY_ODDS_HISTORY`.
  GitHub Actions writes are refused. The **default mode is dry-run**.
- Prices from a single cached snapshot **cannot establish CLV**. Future
  distinct complete provider snapshots must first be captured at real
  different fetch times, including credible near-kickoff prices, before a
  verified CLV calculation can be implemented.

When an authorized staging operator or dedicated staging job is ready:

```powershell
$env:ENVIRONMENT = "staging"
$env:ENABLE_BACKGROUND_JOBS = "false"
$env:PREPARED_BOARD_PERSISTENCE_ENABLED = "true"
$env:BETSIGHTLY_STAGING_BOARD_ONCE = "CONFIRM_STAGING_ONLY"
# DATABASE_URL must be the staging admin URL (never printed or committed).
python -m scripts.capture_staging_odds_history --dry-run

# Only after inspecting the preview, with an explicit authorized write:
$env:BETSIGHTLY_STAGING_ODDS_HISTORY_WRITE = "CONFIRM_APPEND_ONLY_ODDS_HISTORY"
python -m scripts.capture_staging_odds_history --write-staging
```

The first explicitly authorized write creates the new table and index in the
isolated staging database and inserts qualifying quotes, without touching the
live cache or published results. **No standing cron schedule or production
activation is implied by committing this script.** CI only tests the code.

### Post-initialization read access (optional, staging only)

The next manual staging evaluation includes
`append_only_odds_archive` with an honest status if this new table has not
yet been initialized. The staging evaluator's SELECT-only account may need
one additional grant **after** the first authorized table creation. A
staging administrator can separately grant SELECT on only the new table:

```sql
GRANT SELECT ON TABLE public.sportybet_odds_history_v1
TO betsightly_eval_readonly;
```

Never substitute the staging admin URL for the evaluation GitHub secret.
The existing preflight now refuses evaluation roles that can write this new
table, and missing read access merely produces a reported access blocker.

The append-only capture has intentionally not been executed on the live
staging database in this code batch: the table remains uninitialized until
an authorized staging write is performed. Production is unchanged.

### Operator helper for initial archive capture

The repository includes `scripts/capture_staging_odds_history.ps1`, a
Windows PowerShell wrapper modelled on the already-validated settlement
helper. It never enables a job or gives write access to GitHub Actions.

```powershell
cd C:\Users\ZILLAB\Desktop\betsightly-stage-board
git fetch origin
git switch feature/daily-tier-reach-and-builder-supply-20261009
git pull --ff-only origin feature/daily-tier-reach-and-builder-supply-20261009
.\scripts\capture_staging_odds_history.ps1 -DryRunOnly
# Only if the provider snapshot is complete and not older than six hours:
.\scripts\capture_staging_odds_history.ps1
```

The script prompts for the isolated **staging admin** database URL as a
masked SecureString, starts in a read-only PostgreSQL session, validates
the JSON preview, then separately requires typing `CAPTURE STAGING ODDS`
before a write. The backend performs its staging-only checks again.
The password and temporary authorization flags are restored/cleared at
the end. Existing captured snapshots are not updated.

**Run only with a truly new complete bookmaker snapshot.** Re-running a
stale board cannot create another CLV observation. A failed preview should
be diagnosed as missing/incomplete/stale source data, not worked around
by changing the age guard or by replacing `fetched_at` with current time.

To collect history routinely, a staging-specific capture operator still
requires a secure, least-privilege writer identity and a new provider
snapshot at each desired lead-time checkpoint. Do not enable production
or create an unattended task with embedded admin credentials.

### Fresh-source capture research mode (separate from the cached-board helper)

An opt-in `--source live` mode can retrieve a **new** complete bookmaker
board in the staging-only CLI process. It temporarily disables the normal
SportyBet cache get/set hooks, so the source-only fetch does not mutate
`bookmaker_cache` or run the prediction engine.

A staging operator may preview a new source in read-only mode after
setting `BETSIGHTLY_STAGING_ODDS_SOURCE_LIVE=CONFIRM_SOURCE_ONLY_LIVE_FETCH`:

```powershell
# Same isolated staging database environment as documented above.
$env:BETSIGHTLY_STAGING_ODDS_SOURCE_LIVE = "CONFIRM_SOURCE_ONLY_LIVE_FETCH"
$env:PGOPTIONS = "-c default_transaction_read_only=on"
python -m scripts.capture_staging_odds_history --source live --dry-run
```

**Note:** A subsequent `--source live --write-staging` starts a *new* live
provider fetch, not a replay of the preview. It is not executed by the
PowerShell wrapper; its activation remains reserved for a separately
approved staging writer and monitored capture job. Do not assume price
values, even from the same fixture, stayed unchanged between requests.
No claim of verified CLV is permitted by a fresh-source dry-run.

### One-shot fresh source with preview of the exact persisted prices

The staging PowerShell helper additionally supports `-LiveOnce`. It uses a single
source-only bookmaker fetch in one Python process. It validates the complete
snapshot and prints its original bookmaker timestamp, snapshot ID and price
counts before asking for the exact phrase `CAPTURE STAGING ODDS`. Approval
appends those SAME in-memory prices, without fetching them a second time.

```powershell
cd C:\Users\ZILLAB\Desktop\betsightly-stage-board
git fetch origin
git switch feature/daily-tier-reach-and-builder-supply-20261009
git pull --ff-only origin feature/daily-tier-reach-and-builder-supply-20261009
.\scripts\capture_staging_odds_history.ps1 -LiveOnce
```

The helper asks for a masked staging admin DB URL and restores process
environment variables when complete. A stale cached board is irrelevant to
this source-only live fetch. It does not write to the bookmaker cache, run
predictions, settle forecasts, publish picks or change production.

Do not confuse this with `-DryRunOnly`, which reads the old cached board and
may fail due to the six-hour freshness cutoff. A source error or explicit
decline makes no archive changes. `-LiveOnce` is not an unattended scheduler.
Two genuinely different provider fetches are needed for price history;
neither proves a verified closing line or CLV.
