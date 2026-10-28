# NBA Big Batches 26–28 — Different Basketball Features, Not More Guesswork

**Result motivating this branch:** The user ran both score studies. Five regime variants selected the unchanged model on 2025 data; 2026 total-point MAE remains **16.9778 vs 16.5284** for the simple reference, with a mean prediction bias of **-6.2579**. Changes to constant home edge and league-score level did not pass. Do not promote a model because it beats an artificially weak comparator.

## 26: True second feature family
Use the *already accepted* earlier-match NBA advanced team and player box scores—estimated possessions, offensive/defensive efficiency, effective FG rate, 3-point attempt rate, turnover ratio and verified rotation statistics—from `research_advanced_features.from_home`. Require exact game/team identities and current-competition prior histories. This is a materially different input from tweaking a constant scoring offset.

## 27: Three-year scoring model methodology
Run two **matched** Ridge regressions (14-field v1 features vs 30-field advanced features) on precisely the same historic game IDs:
- Fit only 2024 labeled finals (at least 200).
- Choose alpha from `[1,10,100,1000]` using only 2025 (at least 100).
- Evaluate the frozen configurations retrospectively in 2026 (at least 100); also include a simple fixed training-year mean reference, total-score and home-margin MAE/RMSE/bias, paired calendar-day confidence intervals and exact sample counts.
- Derived home/away projections are total±margin halves; no logically inconsistent separate team score training.
- 2026 **is not a new untouched blind holdout**: earlier BetSightly investigations have already inspected its outcomes. The results are for diagnostics only, not a profitability or market-calibration claim.

## 28: Immutable 2027 evaluation remains the authority
Existing 16 moneyline and 16 point projections remain SHA256-checked and unchanged. The challenger is **read-only**, does not write model weights and never backfills historical finals as prospective records. No promotion or sportsbook market recommendations until genuine before-tipoff 2027 results and source rights checks support them.

Command after pulling the separate NBA research branch:

```powershell
python -m basketball.research_cli advanced-score-compare
python -m basketball.research_cli coldstart-closeout
python -m basketball.research_cli opening-score-report
```

The fifth/first game warmup gate for the separate trusted v1 prediction engine remains unchanged. Private NBA only, football and unrelated VPS untouched.
