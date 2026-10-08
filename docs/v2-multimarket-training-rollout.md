# BetSightly V2 multi-market recovery and training: staged release checklist

**Scope:** Phase 9 Odds History/CLV provenance → Phase 11 coherent goal
distribution challenger. This is a draft, dependency of backend recovery
PR #28, and MUST NOT modify production models, official cards or result records.

## 1. Priority: show users usable predictions again

- Frontend PR #13 selects first actually populated official tier by default;
  preserve explicit links and user tab choice.
- Keep a separate, clearly identified upcoming **match analysis** board when
  a day's official slips are withheld. Analysis is not a verified bet or an
  official published result.
- Existing October 8 production card has a duplicate fixture between Banker
  and Over 1.5. Enforce unique fixture identity across all official tiers and
  no nonactionable booking-code exposure before any production merge.
- Preserve immutable prior published slips; replacement/previews never
  overwrite the public win/loss record.

## 2. Capture lost alternative markets before retraining

The production daily selector reduces a fixture to rank 1 / close rank 2
before the official per-leg policy checks all possible outcomes. An otherwise
viable third market may be invisible to the portfolio optimizer.

- Run `python -m scripts.audit_staging_market_alternatives` (guarded staging
  DB) for a six-date **candidate supply** comparison.
- Run `python -m scripts.compare_staging_official_market_slips` to compare
  actual **preview slip outcomes** with the same quality, booking, odds and
  exposure gates. Enabling this feature requires all three:
  `ENVIRONMENT=staging`,
  `BETSIGHTLY_STAGING_BOARD_ONCE=CONFIRM_STAGING_ONLY`, and
  opt-in `BETSIGHTLY_PREVIEW_ALL_MARKETS=1`, strictly while previewing.
  The compare script temporarily sets/restores the flag itself.
- The regular live daily card, recovery and bookable-now paths are unaffected.
- **Success metrics:** additional unique exactly-bookable fixtures/day,
  qualifying selection per market, number of genuinely publishable 2x/5x/10x
  slips, unchanged per-leg model-return >=1, no fixture reuse or new
  inaccurate prices. An improvement in candidate counts alone is insufficient.

## 3. Dataset and lawful use

Frozen deployed benchmark = 64,218 trainable rows. The September 27 audit
shows the existing price-rich source lacks row-level capture/source history.
Never automatically ingest that corpus for the new training run until
commercial usage rights and odds provenance are verified. The available
7,775 gap-league results are **not** historical bookmaker-price labels.
Own immutable Phase 9 odds history stores source/license, kickoff, provider
fixture identity, market/outcome/specifier, quoted price, capture time,
availability, settlement and later closing price.

A new source CSV must have one unique fixture per row, verified explicit rights,
data origin and an authorized representative:
- `fixture_id,source_id,rights_basis,license_reference,rights_verified_by`
- `kickoff_utc,features_as_of_utc,home_goals,away_goals` (timestamps include
  timezone; feature capture strictly precedes kickoff)
- `home_scored_avg_5,home_conceded_avg_5,away_scored_avg_5,
  away_conceded_avg_5,home_win_rate_5,away_win_rate_5,
  home_rating_pre,away_rating_pre`

`rights_basis` values: OWNED_VERIFIED,
COMMERCIAL_LICENSE_VERIFIED, PUBLIC_DOMAIN_VERIFIED. These are **operator
attestations, not proof of legal permission**. Verify underlying terms,
redistribution/training rights, and feature collection rights before marking
records verified. Do not add corners/cards/HT targets from full-time scores.

## 4. Offline coherent full-time model

`leagues/goal_distribution_challenger.py` derives an entire scoreline grid
from home/away expected goals. It produces consistent O/U0.5–4.5, BTTS,
team goal lines, 1X2 and Double Chance; DNB is conditional on avoiding draw
and its draws are PUSH, not losses.

`scripts/train_multimarket_goals_challenger.py` is an **offline-only**
two-expected-goals Poisson gradient-boosting prototype, using only explicitly
permissioned pre-kickoff feature CSV, strict whole-WAT-date chronological
train/calibration/test splits, 500+ matches and 30+ dates. It reports holdout
Brier/log loss/ECE against training base-rate probabilities and does not
alter active model artifacts.

Example **only after permissioned source verified**:

```powershell
.\.venv\Scripts\python.exe -m scripts.train_multimarket_goals_challenger `
  --input-csv C:\secure\licensed_football_history.csv `
  --report C:\secure\multimarket_shadow_report.json
```

This first challenger is a *benchmark*, not an approved betting algorithm.
Later Phase 11 fit alternative joint-goals families (e.g. Dixon-Coles,
correlated/bivariate Poisson), compare FT probability skill, independent
chronological holdout, calibration/expected-value intervals and bookmaker
no-vig baselines. **Never promote on synthetic tests or retrospective fit
alone**. Model governance remains fail-closed with multi-week prospective
monitoring and settlement/price lineage.

## 5. Planned target waves

1. Full-time result and goals: Over/Under 0.5–4.5, both teams to score,
   home/away team Over/Under0.5/1.5, 1X2, 1X/X2 and draw-no-bet. Existing
   full-match Over0.5 **is not currently a SportyBet-verified registry
   mapping**; do not mark bookable until its exact market/outcome identifiers,
   price and settlement semantics are verified. Do not reactivate broken BTTS
   ML without independent calibration evidence.
2. First-half/second-half score markets only after verified half-time labels
   and explicit provider bookability; no proxying HT goals from FT scores.
3. Corners, cards and handicaps only with their own license-cleared event,
   team and push/quarter-line settlement datasets.

## 6. Release and rollback gates

- Backend full CI and isolated staging previews PASS.
- Selectors and forecasts compared on the **same** fixtures and prices.
- Confirm matching SportyBet event+specifier/outcome before any booking.
- Published fixture exposure <=1 across all official products.
- Product-specific evidence and conservative EV policy review documented
  before any policy change; 10x remains withheld when it cannot reach the
  target safely within the allowed legs.
- Frontend publication states transparently differentiate unavailable,
  preview, analysis-only, and exact bookable today.
- Shadow model training/candidate diagnostics shall not trigger real cards,
  settle, create codes or notify users.
- Rollback: feature flag off (default), no production imports, and keep current
  immutable published records untouched.

**Current state:** code and synthetic tests are committed to draft PR #29.
Real rights-approved historical data is not yet connected, so *no real model
has been trained and no evidence exists yet of higher accuracy or more
official slips*. Run staging comparison first before prioritizing retraining.
