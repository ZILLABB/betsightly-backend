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
