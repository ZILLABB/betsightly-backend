# NBA Big Batches 17–19 — Opening-week total points and handicap evaluation

**17 — Genuine independent NBA point projections.** A fixed early-season research model uses actual previous-season and no more than four already completed current-season results per club to estimate (a) both teams' points, (b) full-game total points, and (c) home margin. This is a *score regression experiment*, **not** bookmaker-spread pricing, validated O/U, a 1UP/2UP market or a bet. It excludes only the exact independently verified 2025 NBA Cup non-standings game **in memory**, leaving provider assets, official v1, and the 16 original opening-week moneyline forecasts unchanged.

**18 — Matched historical evaluation.** Compare each predicted target with the prior-season league baseline on the exact same 2025 and 2026 retrospective cohorts. Report candidate and baseline MAE, signed bias and RMSE; **no ROI, calibration, betting odds or published picks**. Preserving day-batch isolation prevents post-tipoff scores on the target game or same NBA provider day from leaking into predictions.

**19 — Immutable real pregame evidence and final grades.** New local-only SHA256-checked score forecasts and separate verified score settlements, 10-minute pregame buffer, 48-hour lookahead, prevention of duplicate captures, no result guessing, 30 latest actual-finals diagnostics. The scheduled pregame task runs this experiment as an optional sidecar; the existing score task settles its archived original forecasts without retraining. Any source/model failure remains independent from trusted v1. Advanced Stage 4 and official moneyline ledgers remain unchanged.

Commands:

```powershell
python -m basketball.research_cli opening-score-backtest
python -m basketball.research_cli opening-score-report
# optional explicit mutating capture, when Windows is awake
python -m basketball.research_cli opening-score-cycle
```

No production deployment, no unrelated VPS or football changes. No assumption of market-level edge based on retrospective MAE. Keep first 16 original moneyline forecasts as a separate experimental cohort. No cloud host launched; laptop-off remains unsupported.
