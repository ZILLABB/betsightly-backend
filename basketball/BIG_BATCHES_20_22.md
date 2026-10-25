# NBA Big Batches 20–22: More disciplined basketball score research

**20 — Six fixed hypotheses.** The present experimental full-game totals model recorded **15.8875 MAE versus 15.7324** for the league scoring baseline across 157 historical games (worse). A new read-only challenger varies only the pseudo-game prior weight and home-edge offset across six specified *coherent* projections; home + away = total, home - away = margin. It neither imports bookmaker odds nor makes betting predictions.

**21 — Earlier-year selection.** Select exactly one hypothesis from **2025 development fixtures** using a predeclared balanced MAE-to-baseline ratio over all four targets. Evaluate that fixed choice on **2026**, alongside the original and naive reference. 2026 was used elsewhere in past project research, so it is retrospective, not independently blind.

**22 — Honest uncertainty.** Use paired calendar-day bootstrap intervals for candidate-vs-baseline MAE gains on the retrospective 2026 cohort, with per-target advisory gates. An apparent gain can be inconclusive on small sample sizes. No model promotion is approved, no prior 2027 forecast is recalculated, and no extra wager or code is created.

Read-only command: `python -m basketball.research_cli opening-score-challenge`.

The 16 captured basketball score forecasts and 16 moneyline forecasts remain archived and eligible for verified settlement. Production football, public basketball and the separate VPS remain unchanged. The experiment is still subject to real future evaluation and data rights.
