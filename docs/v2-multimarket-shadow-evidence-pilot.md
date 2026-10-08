# Multi-market prospective shadow evidence pilot (staging only)

**Purpose:** Break the cold-start feedback loop where a market needs 25
settled *published* selections before the official quality gate approves it,
but the market cannot accumulate published selections without that evidence.

The staging-only `market_shadow_forecasts_v1` ledger stores prospective
snapshots of **all generated market opinions**, independently of their
publication status or trust activation. This includes BTTS and other market
candidates that public publication still disallows. It never changes the
published predictions, official result statistics, per-tier quality floors,
SportyBet booking state, or trained production model artifacts.

## Safety contract

- `scripts.prepare_staging_board_once.preflight()` requires
  `ENVIRONMENT=staging`, `BETSIGHTLY_STAGING_BOARD_ONCE=CONFIRM_STAGING_ONLY`,
  disabled background jobs, enabled board persistence and verifies actual
  connected database name `betsightly_db_staging` via SQL.
- Writes require an **additional** explicit
  `BETSIGHTLY_STAGING_MARKET_SHADOW_WRITE=CONFIRM_SHADOW_ONLY`. The ledger
  must use the **same engine** verified by the staging preflight.
- `report` is read-only and does not require the second write confirmation.
- Capturing requires a **fresh**, already persisted 7-day prediction board;
  the script never performs ESPN or SportyBet provider refresh. It refuses
  missing snapshots, invalid probabilities and forecasts made fewer than 10
  minutes before kickoff.
- First write wins for a model-version / fixture / market combination, even
  across later board refreshes. Captured probability, bookmaker real-price
  flags, observed timestamp and source snapshot cannot change during
  settlement. No retroactive synthetic 'as-of' captures.
- A score is graded only after kickoff +3h and ONLY from verified completed
  score feeds using date-scoped team identity. Ambiguous or missing scores
  remain pending. Draw No Bet draws are `void` and excluded from binary Brier
  scoring. Unsupported markets remain unresolved, not guessed.
- This is a **shadow performance dataset**, NOT the independently held-out,
  rights-cleared *historical training* dataset. None of its scores can be
  used to claim public winning picks or automatically change the 25-settlement
  publication requirement.

## Operator sequence (only on isolated staging DB)

On the existing Windows staging checkout, with the correct secret DATABASE_URL
provided privately (never paste it in a message or GitHub issue):

```powershell
git status --short
git fetch origin
git switch --detach origin/feature/v2-multimarket-challenger-20261008

$env:ENVIRONMENT = "staging"
$env:ENABLE_BACKGROUND_JOBS = "false"
$env:BETSIGHTLY_STAGING_BOARD_ONCE = "CONFIRM_STAGING_ONLY"
$env:PREPARED_BOARD_PERSISTENCE_ENABLED = "true"
$env:BETSIGHTLY_STAGING_MARKET_SHADOW_WRITE = "CONFIRM_SHADOW_ONLY"

# Existing board must still be within its 1-hour freshness window
.\.venv\Scripts\python.exe -m scripts.staging_multimarket_shadow capture

# View shadow-only market coverage
.\.venv\Scripts\python.exe -m scripts.staging_multimarket_shadow report

# Later, once fixtures have been completed for at least 3 hours:
.\.venv\Scripts\python.exe -m scripts.staging_multimarket_shadow settle
.\.venv\Scripts\python.exe -m scripts.staging_multimarket_shadow report

Remove-Item Env:BETSIGHTLY_STAGING_MARKET_SHADOW_WRITE -ErrorAction SilentlyContinue
```

No board refresh is required merely to run `settle` or `report`.

## How this supports market activation

1. Record unaltered **prospective forecasts**, with real odds availability
   and exact SportyBet market IDs where observed, across supported leagues.
2. Settle verified full-time result labels for Double Chance, total/team
   goals, DNB push, 1X2 and BTTS independent of public bets. Count unique
   fixture-market observations; retain source and model version.
3. Report per-market Brier/log-loss/calibration vs league baselines,
   opening/closing bookmaker implied probabilities (Phase 9 warehouse)
   and out-of-sample comparisons; avoid selection bias by keeping rejected
   markets. Current ledger Brier is descriptive and not an approval.
4. Test **product-specific evidence thresholds** in a separate counterfactual.
   Banker/2x retain highest safety requirements; 5x/10x experiments must
   preserve exact bookability, real prices, market trust, >=65% conservative
   probability and >=1 risk-adjusted expected return, pending governance.
5. Phase 11 joint goal-distribution challenger must be trained only with
   historical records whose commercial use and pre-kickoff feature provenance
   are established. Validate unselected market skill prospectively before
   any activation. BTTS stays restricted until it proves calibration.

## Release guardrails

- PR #29 remains **draft**, no production data migration, no model
  activation, no publication or SportyBet booking change.
- Do not deploy this pilot as an automatically invoked web/scheduler task.
- After sufficient independent evidence, write separate, reviewed migration
  and governance gates. Publish 5x and 10x only when quality/odds constraints
  are satisfied; otherwise withhold honestly.
