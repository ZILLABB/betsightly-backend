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
- Artifacts: `summary.md`, `walkforward.json`, `evidence.json`;
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
