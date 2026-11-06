# NBA Big Batches 09–11 — Model Evidence, Data & Preflight

This is an extension of the isolated research-only basketball work in PR #178.

- **09: Real capture preflight.** `coldstart-readiness` explains whether the private empirical-prior experiment can record in the next **48 hours**, with verified UTC tipoffs at least ten minutes ahead, current free-source snapshot freshness, and previous-season team game counts. This is a read-only lookahead; it does not create predictions or bettable tickets. `coldstart-cycle` is a separate write. The existing Windows pregame task invokes shadow capture when awake.
- **10: Stronger opening-week benchmark.** `coldstart-backtest` reports each 2025/2026 held-forward early-season cohort and pooled results: matched Brier and log loss versus the prior-season home-win baseline, paired improvement, home-win frequency, model accuracy, mean forecast and five transparent calibration bins. Small calibration bins are marked. This is **retrospective**, does not establish a betting edge, and uses no sportsbook odds.
- **11: Genuine forward head-to-head scoring.** `coldstart-report` supplies paired actual-settlement candidate-vs-baseline Brier, the most recent 30 actual finals, and keeps all metrics null on data integrity failure. No future games are backfilled as pregame forecasts; neither the original five-match v1 nor official results, football production, any VPS, or public publishing is touched.

Run in your isolated basketball checkout after pulling the private research branch:
```powershell
python -m basketball.research_cli coldstart-readiness
python -m basketball.research_cli coldstart-backtest
python -m basketball.research_cli coldstart-report
python -m basketball.research_cli advanced-gaps
```

**Critical limitation:** Laptop-off always-on processing is not implemented by this change. Scheduled tasks continue to require a running machine; no claims of first genuine forward NBA predictions until the ledger actually contains them.
