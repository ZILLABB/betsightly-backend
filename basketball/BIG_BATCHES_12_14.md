# NBA Batches 12–14 — First real predictions into true verified outcomes

## 12. First-game score closeout
`python -m basketball.research_cli coldstart-closeout` reports separate `not_started`, `awaiting_final_score`, `overdue_unverified_final`, `final_available_pending_grade`, `verified_settled` states. Verified directional classifications and private paired Brier are scored only after a real settled game. Pending never becomes a loss merely because time elapsed; no bookmaker win, stake, odds or ROI is claimed. Original forecast SHA256 records remain unchanged.

## 13. Team-season schedule classification audit
An 83-game prior-season count for New York requires checking whether the ESPN-derived release labels a tournament game as regular season. A `calendar_quality` report flags all >82 finished 'regular-season' game records, with exact recently included IDs/dates, as **possible provider classification differences**. They are not automatically discarded or called fraudulent. No existing 16 forecasts or model version is modified.

## 14. Trusted baseline versus experimental predictor
Wave 1 `separate_early_season_experiment` shows the separate early-season counts while the trusted five-game research v1 remains zero. Avoid conflating these independent systems or their calibration.

All work remains isolated to draft PR #178. No production, sportsbook, public publication, cloud hosting, or football/VPS modification.
