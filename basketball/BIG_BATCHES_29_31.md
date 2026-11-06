# NBA Big Batches 29–31 — Cross-season advanced opening week (no betting)

The actual matched historical advanced regression (2024 training, 2025 tuning, 2026 retrospective 1151-game evaluation) improved **total-points MAE by only 0.07064**, with the paired confidence interval crossing zero; the advanced model made **home-margin predictions worse**. More inputs alone are not enough to promote a model.

**29: Meaningful opening-week advanced data access.** Existing 30-feature advanced scorer demands FIVE earlier same-season completed games from both teams, so it cannot serve our first-16 fixture cohort yet. New `research_early_advanced.py` tests a different *fixed-form, never-trained-on-2027* opening-week candidate: use last season's **12 most recent verified regular-season paired team boxscores** (at least 8 needed per club) and at most four strictly earlier-date finals from the current season. Compute possessions, offensive efficiency and opponent defensive efficiency; derive both teams' point projections and the resulting total and margin. The official Cup final is excluded in memory, including from previous-year trailing efficiency.

**30: Fair same-game comparison, not inflated accuracy.** Use exactly the fixture IDs eligible for the existing `opening-score` early-season model (historical 2025 and 2026 cohorts, 0–4 current-season games), and only those with verified advanced past-game data. Report advanced-versus-reference MAE for four targets on identical matches, separate by season, with explicit missing-advanced counts. This model uses no player injury information and does not claim changing rosters are unchanged from last year.

**31: Before-tipoff preview without alteration.** The same read-only operation can show estimated total points, previous model's total and estimated possessions for genuinely upcoming 2027 fixtures inside the 48-hour original eligibility window. The current 16 moneyline and 16 score snapshots are *unchanged*. No new shadow predictions are recorded in this batch; based on the historical and future eligibility result we can decide whether a separate frozen early-advanced prospective ledger should be enabled.

Run:

```powershell
python -m basketball.research_cli early-advanced-compare
```

No sportsbook markets/prices, no bets, no 2027 leakage, no production football or separate VPS touched. This is a research model comparison, not an approved betting model.
