# NBA core research: Big Batches 06–08

**Scope**: Draft PR #178 / isolated local NBA research only; never football, unrelated VPS, public tips or booking.

## Batch 06 — Open-week truthfully prospective shadow
Trusted v1 continues to require **five completed earlier same-season games per club**. A completely independent, explicitly experimental opening-week empirical-prior model uses actual previous-season club results (minimum 20 each), prior-season NBA home-win rate, and only earlier current-season results (0–4 for at least one club). Coefficients are heuristic, not tuned or calibrated to a bookmaker. It never replaces v1 or advanced models.

- \`python -m basketball.research_cli coldstart-backtest\`: retrospective walk-forward performance for 2025/2026, separated from future evidence. The baseline is prior-season home-win frequency, not market odds. Keep folds, sample counts and Brier scores visible; an empty fold is not a win.
- \`python -m basketball.research_cli coldstart-report\`: verify immutable SHA256 pregame records, precise team/game/UTC identity and score provenance, report forward Brier **only** from authentic settled games.
- \`python -m basketball.research_cli coldstart-cycle\`: explicitly lock, settle verified past forecasts, and append new upcoming forecasts at least 10 minutes before tipoff, if the source snapshot is fresh (36h) and previous-season evidence is sufficient.
- Scheduled \`automate --mode pregame\` invokes the independent shadow cycle as an optional sidecar. Score tasks settle already-captured cold-start forecasts; any failure stays separate from trusted v1.

**No confidence, edge, ROI, SportyBet prices, booking codes, stakes or betting recommendation is asserted.** Historical games never get backfilled as purported forward forecasts. Forecast hashes and settlements remain in separate local JSONL files.

## Batch 07 — Exact player/team completeness
\`python -m basketball.research_cli advanced-gaps\` reads the cached 2027 accepted advanced JSON and manifests and lists *verified finals missing two matched sides*, with exact game IDs and source-specific coverage. No incomplete row is fabricated and the 85% acceptance threshold stays intact.

## Batch 08 — Regression and isolation
Synthetic tests cover real-before-tipoff capture, duplicate suppression, after-tipoff rejection, score settlement without changing the original forecast, corruption lockout, previous-season requirements, same-day leakage, missing box-score files and CLI parsing. CI must pass. The change does not deploy or schedule a cloud service: laptop-off execution remains separate and not yet achieved.

### Run
\`\`\`powershell
git pull --ff-only origin stage1/nba-private-research-20261024
python -m basketball.research_cli coldstart-backtest
python -m basketball.research_cli advanced-gaps
python -m basketball.research_cli coldstart-report
\`\`\`
The already configured hourly **pregame** and **score** jobs can maintain independent opening-week shadow observations while Windows is awake. The manual mutating \`coldstart-cycle\` is optional.
