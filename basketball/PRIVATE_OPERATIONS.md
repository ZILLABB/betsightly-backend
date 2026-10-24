# Private BetSightly NBA lab — operating instructions

**Status:** isolated Stage 1 research branch (based on live `devil`) with no production merge. The live
BetSightly backend, Vercel/Cloudflare frontend, administrator, SportyBet codes,
Telegram and calibration records are never touched. There is **no cloud
deployment, automatic cloud task or remote private admin URL**.

## What has actually been built

- Source-verified free public NBA historical-game imports (ESPN-derived data
  via SportsDataverse; see license caveats).
- An evaluated moneyline probability baseline, plus research-only actual-score
  total-points and home-margin regression baselines.
- A *durable local model*, source snapshot, training metrics, private SQLite
  prediction ledger, append-only-at-application-level result reconciliation,
  and a read-only Atlantic research dashboard.
- Local Windows command that can optionally register a Windows Scheduled Task.
  **The task has not been installed remotely or on your device.**
- GitHub CI checks plus the real source data backtest. GitHub Actions discards
  the models and downloaded provider data rather than leaking private material
  via artifacts from this public repository.

## One-time Windows setup

Open PowerShell in a local checkout of the Stage 1 research branch. The commands below operate only on your Windows computer; GitHub CI does not install a local scheduled task. Do **not**
merge it into `devil` or deploy to Render.

```powershell
git fetch origin stage1/nba-private-research-20261024
git switch -c nba-research --track origin/stage1/nba-private-research-20261024
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install scikit-learn==1.8.0 joblib
```

## Run the actual private daily research cycle

```powershell
.\scripts\nba_paper_research.ps1
```

This explicitly refreshes the public release data (not a paid API), retains
last-known training models under `data/basketball/research/`, forecasts
upcoming qualifying games for the following two provider calendar dates,
and settles older predictions **only** after their verified final scores
appear in the next snapshot. Predictions are never overwritten or backdated.
Re-running is safe: already-recorded game IDs are not revised.

If there are not enough previous completed same-season games for both teams,
the legitimate output is **zero paper forecasts**.

To run using the last downloaded data with no network:

```powershell
.\.venv\Scripts\python.exe -m basketball.research_cli cycle --offline
```

Explicitly refit both prospective models after inspection (do not automate
blindly or silently revise original paper picks):

```powershell
.\.venv\Scripts\python.exe -m basketball.research_cli cycle --retrain
```

## Open the local Atlantic research dashboard

```powershell
.\scripts\nba_paper_research.ps1 -ShowDashboard
```

Then open **http://127.0.0.1:8767** on the *same computer*. The server binds
to localhost only, includes a restrictive CSP, escapes provider strings, and
has no change/publish/book routes. It is **not** reachable from the internet.

To see a JSON-only status without opening a browser:

```powershell
.\.venv\Scripts\python.exe -m basketball.research_cli ledger
```

## Optional: install a local daily scheduled task

Only when you're ready to run on your own always-on Windows machine:

```powershell
.\scripts\nba_paper_research.ps1 -InstallSchedule -LocalTime "18:00"
```

This is a suggested **18:00 COMPUTER LOCAL TIME**, not a guaranteed WAT
conversion; make sure Windows is configured for Nigeria Standard Time if
that's your intended time. The PC must be awake with network access, Python
installed and the research checkout retained at the original path. Task
Scheduler history can reveal failed runs. To remove the task later:

```powershell
Unregister-ScheduledTask -TaskName "BetSightly NBA Paper Research" -Confirm:$false
```

**Do not run the above against your football production checkout.**

## Private data files

| Local path | Purpose |
|---|---|
| `data/basketball/research/nba_games.jsonl` | Most recent complete season snapshot |
| `data/basketball/research/source_manifest.json` | Source URL, byte counts and SHA256 checksums |
| `data/basketball/research/nba_moneyline.joblib` | Trained moneyline model |
| `data/basketball/research/nba_scores.joblib` | Separate total/point-margin models |
| `data/basketball/research/nba_paper.sqlite` | Original paper probabilities and verified final scores |
| `data/basketball/research/training_metrics.json` | Moneyline evaluation metadata |
| `data/basketball/research/score_training_metrics.json` | Total and margin regression evaluation |

Back up this entire **git-ignored** folder locally if you need to retain your
longitudinal experiment across hardware changes. Never upload raw data,
models, predictions or the SQLite file to a public GitHub repository.

## Remaining scientific and operational acceptance gates

1. A local machine/private host must actually run the cycle repeatedly; code
   and a schedule installer do not mean it has been started.
2. Track enough **real pregame paper forecasts** and their settled outcomes to
   measure calibration, reliability, and performance across NBA seasons.
3. Add appropriately licensed timestamped bookmaker moneylines, totals and
   spreads before claiming probabilities have positive expected betting value.
4. Verify player injury, availability and advanced statistical data rights.
   Unverified scraped sources must not be silently used for a commercial
   betting-facing launch.
5. Review the research dashboard and model record protection before choosing
   a separate private cloud deployment. Public basketball site exposure must
   remain disabled without explicit new release approval.

A previous baseline passed a 1,711-game **historical** holdout at **65.93%
accuracy** (Brier **0.21347**). That is historical probability discrimination,
not prospective performance, ROI or bookmaker-beating evidence.

## Stage 1 isolation checks (24 October 2026)

- The Stage 1 branch was created from the current `devil` commit to avoid merging the obsolete `dev` history.
- Only the standalone `basketball/`, NBA-specific workflows/tests, local runner, and a `.gitignore` privacy rule were changed; no live FastAPI route or Render configuration was changed.
- `data/basketball/research/` is explicitly ignored by Git so the private ledger, downloaded raw data, source manifests, and model artifacts do not enter the public repo.
- A CI research cycle may run on an ephemeral GitHub-hosted runner for **smoke validation only**; its SQLite paper ledger is discarded and does **not** count as persistent prospective tracking.
- To start *durable* prospective paper testing, run the script locally once and use `-InstallSchedule` only on the Windows PC where data/model files will persist. A computer that is powered off will miss its local scheduled run.
- Until a private persistent machine has actually executed and retained a cycle, operational status is **READY FOR LOCAL ACTIVATION**, not actively running.

## Stage 2A readiness diagnostics (private; code only)

The local dashboard at http://127.0.0.1:8767 now displays upcoming scheduled NBA fixtures, same-season prior-final counts for both teams, explicit blocking reasons, and source age. Read-only JSON is at http://127.0.0.1:8767/api/readiness; neither endpoint downloads data, scores matches or creates bookmaker codes. The source is refreshed by the scheduled cycle, not by refreshing the browser.

When your research checkout is updated, run:

```powershell
Set-Location "$HOME\Desktop\betsightly-nba-lab"
git pull --ff-only origin stage1/nba-private-research-20261024
.\.venv\Scripts\python.exe -m basketball.research_cli readiness --days-ahead 7
```

If the old dashboard is open, stop it with Ctrl+C, then restart:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\nba_paper_research.ps1 -ShowDashboard
```

The dashboard's READY label is **only pregame research eligibility**, never a recommendation to bet. Readiness uses a 36-hour maximum age for the snapshot and explicitly reports missing or invalid local snapshots. Existing immutable forecast rows and historical model results are not changed by diagnostics.

## Stage 2B — verified private NBA finals and monitoring

Updated sources remain **unofficial/keyless and research-only**. The historical
SportsDataverse schedule and ESPN's scoreboard are two different access
paths to ESPN data, **not two independent licensors or a paid SLA**. Failures
or unresolved finals are reported and never silently converted into wins.

From the Windows NBA research checkout:

```powershell
Set-Location "$HOME\Desktop\betsightly-nba-lab"
git pull --ff-only origin stage1/nba-private-research-20261024

# Manual one-off lightweight score verification; no model training
.\.venv\Scripts\python.exe -m basketball.research_cli settle

# Confirm immutable existing forecasts/results (if any)
.\.venv\Scripts\python.exe -m basketball.research_cli ledger

# Confirm upcoming vs started-but-unverified games
.\.venv\Scripts\python.exe -m basketball.research_cli readiness --days-ahead 7
```

Optional, **only after the manual score check succeeds**: install a separate
Windows task for hourly score checks at HH:20 (computer-local time).
The existing daily 18:00 model cycle is not changed.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\nba_score_check.ps1 -InstallSchedule
Get-ScheduledTaskInfo -TaskName "BetSightly NBA Score Check" |
    Select-Object LastRunTime, NextRunTime, LastTaskResult
```

The optional repeated task is registered for one year and must be renewed
after expiration; the Windows PC needs to be on. It is not an immediate
post-buzzer settlement guarantee. It never fetches 11 seasons or retrains.
Its local log is git-ignored at
`data/basketball/research/score_check.log`. Scoreboard health appears at
`data/basketball/research/scoreboard_health.json` and in the dashboard.

Final acceptance is keyed by **exact ESPN event ID, home/away IDs, verified
final status, plausible same tipoff and non-tied integer scores**. A conflicting
final or fixture identity stops the run without changing prior settled
records. The research ledger remains append-only.

If the scoreboard endpoint returns 403, times out or changes its JSON schema,
`scoreboard.status` becomes `partial`, with failed dates listed.
The research dataset remains usable and no score is invented. The
`settle --offline` command only reconciles already saved verified scores.

To see Stage 2B's dashboard changes, stop the existing localhost server
with Ctrl+C and restart using
`powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\nba_paper_research.ps1 -ShowDashboard`.

### Stage 2B provider diagnostic fix (2026-10-24)

An October 24 local test initially showed `scoreboard.status=partial`,
`dates_checked=0`, with one bare `RuntimeError`. This confirms **no ESPN
scoreboard data was actually verified**, even though the hourly Windows task
had exit code 0. The initial code incorrectly treated a partial provider check
as successful task completion.

The checker now tries ESPN site scoreboard **and** the documented ESPN CDN
scoreboard endpoint (`cdn.espn.com/core/nba/scoreboard?xhr=1&date=YYYYMMDD`).
Both are ESPN-owned, unofficial, free-to-query feeds, NOT independent
providers or guarantees. The parser only accepts the CDN's real `sbData`
scoreboard events. All final-result identity safeguards still apply.

The `settle` output now includes sanitized diagnostic details such as
`site:HTTP_403; cdn:HTTP_403`, `TIMEOUT`, `NETWORK_ERROR` or
`CDN_MISSING_EVENTS`. Provider HTML, redirects, response bodies and
auth details are **not** printed. No data is invented.

The hourly PowerShell task now returns a **nonzero failure** if
`scoreboard.status != ok`, rather than reporting TaskResult 0 while ESPN
verification failed. `nba_paper.sqlite` remains persistent, and the last
failure is visible in `scoreboard_health.json` and in
`score_check.log`.

To check after updating your Windows checkout, manually execute:

```powershell
Set-Location "$HOME\Desktop\betsightly-nba-lab"
git pull --ff-only origin stage1/nba-private-research-20261024
.\.venv\Scripts\python.exe -m basketball.research_cli settle
```

Inspect `scoreboard.failed_dates[].detail` for real network/HTTP failure.
If both ESPN access methods are blocked on this PC, do not repeatedly
poll or attempt to evade provider blocks: stop the optional hourly task
and retain the safe historical snapshot while a distinct authorized
no-cost provider is evaluated. A successful Windows script or hourly
schedule does not prove that a final was obtained.

### Additional no-cost official NBA fallback

When ESPN site API **and** ESPN CDN are unreachable, the scoreboard checker
now attempts the NBA's own keyless live scoreboard from
`cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json`.
This is a genuinely separate league-owned feed, but it only covers the
NBA server's **current scoreboard day**, not arbitrary historical dates.

The NBA's event IDs and team IDs are unrelated to ESPN game IDs. To avoid
fabricating matches, a final is credited only after **all** of these:
official NBA `gameStatus=3` with `Final` label; valid non-tied integer
scores; NBA scoreboard's `gameDate` equals the requested season game date;
exact home/away team tricodes mapped from known NBA names; within **30
minutes** of the ESPN fixture's known UTC start; and exactly one ESPN
fixture matches. The original NBA provider event ID is preserved in the
verification metadata, and an unmatched game is ignored.

After `git pull`, run the usual
`python -m basketball.research_cli settle` command. The result reports
`official_nba_fallback_dates` and includes sanitized failure causes from
all routes (ESPN site, ESPN CDN, NBA CDN). Do not interpret `status=ok`
as a promise that every overdue game has been verified: always inspect
`verified_new_finals` and the dashboard's started/unverified count.

### Stage 2B follow-up — "ok" with 0 dates is not provider verification

The user's 2026-10-24 local run reported `status=ok` with
`dates_requested=0`, `dates_checked=0`, then left the hourly task disabled.
The source selector asks only about **started games that are not already final**
(or have unsettled forecasts). A previous run may have saved all recent finals.
No network request on a subsequent cycle is normal; it does **not** prove
that the ESPN/NBA providers are reachable or broken.

Now `settle` clearly returns `status=idle`,
`verification_performed=false` when there was nothing to check, and adds a
brief `recent_fixtures` summary. The PowerShell task prints an explicit
no-work message and returns success for idle (not a provider success claim).
A `partial` provider check still fails loudly. Local
`scoreboard_health.json` preserves last actual non-idle check timestamp.

Two new, **read-only, no-write** commands explain this without retraining:

```powershell
Set-Location "$HOME\Desktop\betsightly-nba-lab"
git pull --ff-only origin stage1/nba-private-research-20261024

# Read saved final scores, source provenance and unresolved started fixtures
.\.venv\Scripts\python.exe -m basketball.research_cli diagnose-scores

# Independently request the latest locally finalized game's scoreboard day.
# Accept success only when a provider final matches exact fixture identity.
.\.venv\Scripts\python.exe -m basketball.research_cli probe-scores
```

For a known recent provider-local game date, append `--date 2026-10-23`
(or another genuine date from `diagnose-scores`). The probe is limited to
the past 14 days. A successful HTTP response with no exact final event is
`no_exact_final_match`, **not** provider verification. The NBA CDN only
supports its current live-scoreboard day, so its noncurrent date mismatch is
expected, not evidence of an ESPN failure. The probe never mutates the local
snapshot, SQLite, forecasts, scores or model artifacts.

Do not re-enable the hourly task based only on an idle result. Inspect
`probe-scores` first. After a real exact-match probe, hourly checks can
safely be enabled again; they will stay idle until another game starts.

## Stage 2C — prospective calibration and sample-size controls (private)

The independent read-only `prospective` command measures ONLY immutable
pre-tipoff forecasts which have been settled by an exact-ID verified NBA
final. It never mixes historical backtest predictions with the prospective
cohort and does not require bookmaker prices, a key, subscription, stake or
any extra Python package.

```powershell
Set-Location "$HOME\Desktop\betsightly-nba-lab"
git pull --ff-only origin stage1/nba-private-research-20261024

# Strictly read-only; inspect the local ledger without retraining
.\.venv\Scripts\python.exe -m basketball.research_cli prospective

# Compare score-source health, private predictions, and readiness
.\.venv\Scripts\python.exe -m basketball.research_cli ledger
.\.venv\Scripts\python.exe -m basketball.research_cli readiness
```

Restart the local dashboard after updating so it displays
`Prospective research evaluation`. The read-only JSON API is
`http://127.0.0.1:8767/api/prospective`. The original daily 18:00 WAT
cycle and separate optional hourly score-only task remain unchanged.

This report includes:
- Settled and pending prospective forecasts, first/last paper times, and
  real score-projector coverage.
- Moneyline accuracy and descriptive Wilson 95% interval; Brier and log
  loss. An **explicit constant 50% home-win forecast baseline** gives Brier
  0.25000. Brier skill = `1 - Brier / 0.25`, positive is better than this
  naïve baseline, not better than bookmaker odds.
- Five *fixed, prespecified* calibration buckets, and empirical observed
  home-win frequencies. ECE is hidden until **at least 100** settlements;
  buckets with fewer than 20 observations are marked too small.
- Rolling windows of latest 30 and 100 **settled** results, separate model
  versions and total-points/home-margin errors and bias.
- Integrity checks on original forecast SHA256, immutable JSON vs stored
  fields, original creation and physical insertion timestamps relative
  to tipoff, final score provenance, and recorded outcome.

A failing integrity check yields `integrity_failed` and **withholds all
model statistics** instead of silently excluding or editing compromised rows.

The `review_ready` status after 100 settled games is an **early descriptive
review checkpoint only**, not statistical proof, endorsement, bookmaker edge
or monetization readiness. A genuine first prospective pregame forecast and
its later verified score are still needed before nonempty real-world
metrics can exist. Current five-game same-season warm-up gates remain.

## Stage 2D — first genuine forecast and automatic settlement monitoring

Stage 2D does **not** bypass the five-game same-season minimum, invent
a forecast, run a paid bookmaker endpoint, or deploy basketball publicly.
It adds a separate read-only `operations` command and the
`/api/operations` localhost endpoint. These compare the current real
source snapshot against the private immutable SQLite ledger.

```powershell
Set-Location "$HOME\Desktop\betsightly-nba-lab"
git pull --ff-only origin stage1/nba-private-research-20261024
.\.venv\Scripts\python.exe -m basketball.research_cli operations
.\.venv\Scripts\python.exe -m basketball.research_cli readiness
.\.venv\Scripts\python.exe -m basketball.research_cli prospective
```

The Atlantic dashboard displays **First-forecast operations** after a
dashboard restart. It shows whether the last research cycle was seen,
schedule snapshot freshness, whether the current two-provider-date
window contains any eligible games, how many original forecasts are
already saved, and whether any pending forecast remains unsettled more
than **four hours** after tipoff. Four hours is a diagnostic threshold,
not a guaranteed score-provider delay or a deadline for finality.

States include `warming_up`, `eligible_for_first_forecast`,
`forecast_pending_settlement`, `first_settlement_verified`, and
`attention_required`. Eligibility uses only results completed on
earlier fixture dates and the same season. A missing forecast is **not**
scored as a loss or backfilled after tipoff. Warnings distinguish an
eligible fixture missed by a cycle which saw the current snapshot from a
cycle that ran before newer data arrived.

**New actual forecast safety guard:** even if the probability model
generates a candidate, the daily cycle writes it only if the separate
readiness gate also approves the exact fixture ID, source snapshot is
fresh, model/training cutoff is recorded, team histories each have at
least five earlier regular-season finals, and tipoff has not occurred.
Filtered candidates appear in `readiness_guard_rejected`. Prior
immutable forecasts and verified settlements are not modified.

For repeatable daily operation, the PC must be awake and in the correct
Windows timezone when the **18:00 COMPUTER LOCAL TIME** scheduled task
runs. Confirm it is actually registered and succeeded, rather than
assuming the existence of the task proves model execution:

```powershell
Get-ScheduledTaskInfo -TaskName "BetSightly NBA Paper Research" |
    Select-Object LastRunTime, NextRunTime, LastTaskResult
Get-ScheduledTaskInfo -TaskName "BetSightly NBA Score Check" |
    Select-Object LastRunTime, NextRunTime, LastTaskResult
```

Stage 2D's first genuine prospective prediction cannot be accepted until
a cycle writes a real fixture before tipoff. A complete lifecycle then
requires that same game ID to appear under verified final settlement.
The operational suite uses **synthetic data for tests only**; no fake
forecasts or returns are inserted into the user's private NBA ledger.
