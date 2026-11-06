# NBA Big Batches 23–25: Expose Total-Points Scoring Regime Error

The user-provided 2026 early-season benchmark found **negative 6.2579 point signed forecast bias**, and the six original challenger settings did not solve it. Full-game total points MAE was **16.9778**, worse than **16.5284** for the naive baseline. All four 2026 calendar-day-cluster bootstrap intervals contained zero; *no promotion* was justified.

**23. Estimate league-wide scoring regime from strictly earlier games.**
Compare the entire previous-season **verified regular-season average total points** against the current season's verified *earlier-date* game totals. The exact independently identified NBA Cup championship is excluded in memory, not from original provider files. Five fixed configurations include no correction and four empirical shrinkage strengths (20, 60, 120, 240 prior games). Require at least five earlier league finals and bound the absolute point shift to 12. Adjust both team point projections equally, keeping the home margin unchanged and maintaining total = home + away. No player injury or possession-based inputs are invented.

**24. Keep selection out of 2026 results.**
Use the **2025 development cohort only** to select the configuration by total-points MAE. Then calculate the selected and original predictions against the same 2026 retrospective fixtures. The problem was motivated by already-seen 2026 underprojection, so **2026 is not independently untouched**. Include a paired calendar-date bootstrap interval and do not label slight gains as statistically established.

**25. Preserve genuine 2027 evidence.**
Read-only `opening-score-regime` does not change the original 16 pregame moneyline or 16 pregame score snapshots, alter any model artifact, publish new picks, obtain sportsbook odds, or modify trusted v1. New live experimental v2 capture is *not* activated. Promotion requires future verified 2027 outcomes and better prospective baseline comparison. Existing score task continues to settle the frozen v1 ledger.

Command:

```powershell
python -m basketball.research_cli opening-score-regime
```

Scope: private draft NBA PR #178 only; unrelated VPS and football production are untouched. Data rights remain unreviewed.
