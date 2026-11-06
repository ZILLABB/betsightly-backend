# NBA Big Batches 32–34 — Prospective advanced model head-to-head

**Observed research, not betting edge:** Previous-season verified team-advanced opening-week model improved full-game total MAE on **143 matched** 2025–26 fixtures from **16.6283** (existing early score) to **16.2359** (advanced); margin worsened from 10.3256 to 10.6783. Yearly total differences were −0.3258 and −0.4599. The new model remains biased **−4.2131** points on combined scores. No model promotion or sportsbook O/U without a real price/line.

### 32: Paired uncertainty plus honest evidence size
`early-advanced-compare` includes paired original-vs-challenger *provider-calendar-day* bootstrap intervals on the matched 143 games, individually for 2025, 2026 and pooled, with explicit advanced coverage (143/157) and missing-count flags. An interval spanning zero forbids any robust improvement claim.

### 33: Truly new, signed pre-tipoff A/B cohort
Private `early-advanced-cycle` may save an independent advanced projection only when a signed, originally recorded `opening_score_forecasts.jsonl` already exists for the *same* game, identity and verified UTC tipoff; source freshness, original ledger hashes and at least ten-minute pregame buffers apply. Archive both challenger and the exact **unchanged originally captured score-model reference** so it can never be replaced by a favorable retrospective recalculation. Existing first 16 moneyline and original score projections remain unmodified, no backfills. The first advanced forecasts may be produced only if the user's local machine actually runs the new code before each game's cutoff.

### 34: Hourly final score grading, fail closed
Use the same verified local final source as the other independent score experiments. Store append-only signed final scores, report paired prospective MAE for total, margin and team points, and distinguish pending/final available/verified settled/overdue. Delayed or missing verified scores are NEVER marked as losses. An optional existing advanced-enabled pregame task creates the cohort, and the hourly NBA score task settles it when local tasks are awake; neither works while the laptop is off. All metrics remain experimental, not public football calibration or bookmaker returns.

CLI:
```powershell
git pull --ff-only origin stage1/nba-private-research-20261024
python -m basketball.research_cli early-advanced-compare
python -m basketball.research_cli early-advanced-cycle
python -m basketball.research_cli early-advanced-report
```

`early-advanced-cycle` writes local separate evidence and is *not* merely a report. Does not touch VPS, production football, SportyBet booking or stakes. No GitHub cloud state is configured.
