# NBA private staging: hosted final-score monitor

## Purpose and boundaries

This workflow calls the **existing** staging-only, machine-authenticated NBA
settlement endpoint. The server resolves completed games through its independent
scoreboard checks and appends only exact-identity, signed three-model research
grades to the separate NBA staging database. It must never infer a final score,
publish a betting selection, generate a bookmaker code, or read/write football
production. No access to the database or SportyBet is granted to GitHub Actions.

GitHub standard runners are free for this **public** repository; usage is still
subject to GitHub Actions policies and availability.

## Activation (not automatic while this PR is open)

1. Review and merge the workflow PR into the repository **default branch `dev`**.
   GitHub schedules do not run for workflows only living on other branches.
2. In `ZILLABB/betsightly-backend` go to **Settings → Secrets and variables →
   Actions → New repository secret**. Set:
   - **Name:** `NBA_STAGE_SETTLEMENT_JOB_TOKEN`
   - **Value:** the *existing private staging settlement machine token*
     (`NBA_SETTLEMENT_JOB_TOKEN` in the isolated NBA Render staging service).
   - Never paste this value into code, workflow logs, PRs, or chat.
   - Do **not** use football production credentials or the Vercel `CRON_SECRET`.
3. Use **Actions → NBA private staging - verified finals monitor → Run workflow**.
   Check for a 200 result and a validated `archive_digest` response; verify the
   corresponding audit in the private NBA health panel and new finalized fixtures.
4. Confirm that the automatic schedule runs across at least two game days and
   that verified finals are reflected in both all three model ledgers and the
   frozen-market paper research. Check provider outages and recovery explicitly.

## Timing and guarantees

- Twice per hour at minute 13 and 43, 01:00–12:59 UTC (02:13–13:43 WAT).
- Catch-up at 16:27 and 20:27 UTC (17:27 and 21:27 WAT).
- GitHub Actions schedules may start late or be dropped during heavy load:
  **no exact settlement SLA is claimed**. A result is recorded only when
  the upstream NBA API has a matching, verified final.
- The server's `NBA_SETTLEMENT_JOB_TOKEN` must be 32+ characters and enabled
  with the existing staging settlement feature flags.
- Existing Vercel daily settlement is a backstop, not evidence that this new
  schedule has started. No rebooking or paid Render cron is involved.

## Fail-closed behavior

Missing/invalid secret, expired database, HTTP 404/503, source partial days,
tampered/missing archive SHA, non-research response, non-bookable response,
malformed JSON, or invalid model settlement counts fail the workflow visibly.
One bounded retry occurs only for transient HTTP 429/5xx/transport errors;
other failures are not retried. No provider JSON, tokens, raw response bodies,
or private fixtures are written to Actions logs. A green run proves a signed
staging archive was checked; a source outage is **not** a settled match.

## Independent acceptance

```bash
python3 -m unittest discover -s tests -p test_nba_stage_settlement_ping.py -v
```

This deployment is **not active** merely because a GitHub branch/PR builds
successfully. The secret, default-branch merge, and one real authenticated run
must all be confirmed before marking automatic settlement operational.

## Before-tipoff forecast + market snapshot automation

Additional workflow `.github/workflows/nba-private-stage-research.yml` also runs
from **default branch dev only**, and has an **offline-only PR test**:

- Forecast: 15:16 and 18:16 UTC daily (16:16 and 19:16 WAT).
- Market capture: 17:21 and 20:21 UTC daily (18:21 and 21:21 WAT).
- Actions secret `NBA_STAGE_FORECAST_JOB_TOKEN`: the existing private Render
  staging `NBA_FORECAST_JOB_TOKEN` value, at least 48 characters.
- Actions secret `NBA_STAGE_MARKET_JOB_TOKEN`: the existing private Render
  staging `NBA_MARKET_JOB_TOKEN` value, at least 48 characters.
- After merging, test one **workflow_dispatch** invocation of each job and verify
  independent private staging `job_readiness` receipt timestamps. Do not interpret
  a provider outage or a stale source as valid prediction evidence.

The forecast trigger can only add eligible before-tipoff **moneyline and
original-score** research forecasts, not recompute the independent advanced
score model; advanced model work remains a separately controlled experiment.
The market trigger archives quoted NBA totals for paper research only, with no
public tips, odds recommendations, stakes, or bookmaker booking codes.
Historical bookmaker observations are immutable; the first observation is the
only frozen reference eligible for paper outcome grading.

The existing Vercel daily cron stays as a backup. No claim of guaranteed cron
minute precision or public ROI is made. All three new Actions secrets must be
configured by the repo owner; never use GitHub workflow source to store tokens.
