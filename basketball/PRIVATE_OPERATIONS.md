# Private BetSightly NBA lab — operating instructions

**Status:** standalone local research tools on draft GitHub PR #171. The live
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

Open PowerShell in a local checkout of the draft research branch. Do **not**
merge it into `dev` or deploy to Render.

```powershell
git fetch origin research/nba-offline-pipeline-20261023
git switch -c nba-research --track origin/research/nba-offline-pipeline-20261023
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
