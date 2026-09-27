# BetSightly Historical Source Registry

Generated: `2026-09-27T11:11:39.310197+00:00`

This registry distinguishes football-results coverage from bookmaker-odds-backed ML training coverage.

## Snapshot

- Missing live competitions tracked: **9**
- Free results-history source identified: **5**
- Free odds-backed source identified: **0**
- Immediately eligible for the current market-feature ensemble: **0**
- Still unresolved: **4**

## Competition sources

| ID | Competition | Provider | Class | Results | Odds history | Current ensemble eligible | Verification |
|---:|---|---|---|---:|---:|---:|---|
| 1 | FIFA World Cup | OpenFootball | RESULTS_ONLY | yes | no | no | VERIFIED |
| 2 | UEFA Champions League | OpenFootball | RESULTS_ONLY | yes | no | no | VERIFIED |
| 3 | UEFA Europa League | OpenFootball | RESULTS_ONLY | yes | no | no | VERIFIED |
| 848 | UEFA Conference League | OpenFootball | RESULTS_ONLY | yes | no | no | VERIFIED |
| 13 | Copa Libertadores | OpenFootball | RESULTS_ONLY | yes | no | no | VERIFIED |
| 11 | Copa Sudamericana | UNRESOLVED | UNRESOLVED | no | no | no | REVIEW_REQUIRED |
| 265 | Chilean Primera Division | UNRESOLVED | UNRESOLVED | no | no | no | REVIEW_REQUIRED |
| 292 | K League 1 | UNRESOLVED | UNRESOLVED | no | no | no | REVIEW_REQUIRED |
| 307 | Saudi Pro League | UNRESOLVED | UNRESOLVED | no | no | no | REVIEW_REQUIRED |

## Guardrail

Results-only data may expand form, base-rate, ELO/Dixon-Coles, replay, and future football-first models. It must not be silently mixed into the current 25-feature market-price ensemble as though bookmaker odds were present.

The next ingestion phase should therefore create two explicit datasets:

1. `football_history`: result/identity history, allowed to use verified results-only sources.
2. `market_training`: rows with explicit bookmaker-price provenance suitable for market-feature model training.
