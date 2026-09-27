# SportyBet-First Shadow Audit

## Purpose

This branch evaluates a SportyBet-first fixture/inventory architecture without
changing the production prediction, publishing, booking, or settlement paths.

Production remains authoritative. The shadow path is observation only.

## Hard guardrails

- `shadow_only = true`
- `can_publish = false`
- `can_book = false`
- `can_settle = false`
- `authoritative_for_user_output = false`
- Interactive shadow diagnostics never initiate SportyBet, ESPN, or
  API-Football refreshes.
- Ambiguous fixture identity fails closed.
- Youth/reserve/senior mismatches fail closed.
- Home/away orientation and kickoff tolerance are identity gates.
- Bookable does not mean prediction-ready.

## Shadow flow

1. Existing cached SportyBet catalogue.
2. Compact SportyBet-first inventory.
3. Canonical identity resolution.
4. Existing prepared production board cross-check.
5. Already-cached API-Football cross-check when available.
6. Data-support classification.
7. Existing current-engine candidates and existing trust/market policy.
8. Shadow prediction-readiness metrics.

There is no second prediction engine.

## Identity states

- `EXACT_ID`
- `EXACT_ALIAS`
- `TEAM_KICKOFF`
- `FUZZY_VERIFIED`
- `AMBIGUOUS`
- `UNMATCHED`

`AMBIGUOUS` and `UNMATCHED` never become prediction-ready.

## Enrichment states

- `FULL`: prepared production identity plus cached API-Football support.
- `PARTIAL`: prepared production identity without API-Football corroboration.
- `STALE_FALLBACK`: identity comes from a stale prepared production board.
- `SPORTYBET_ONLY`: valid SportyBet inventory item without a production-board identity.
- `AMBIGUOUS`: more than one plausible fixture identity.
- `UNSUPPORTED`: invalid or unsupported identity.

## Data support

- `STRONG`: eligible for shadow prediction-readiness.
- `ADEQUATE`: eligible for shadow prediction-readiness.
- `THIN`: diagnostic only.
- `VERY_THIN`: diagnostic only.
- `UNSUPPORTED`: diagnostic only.

A fixture is `prediction_ready` only when:

1. canonical/prepared identity resolves;
2. support is `STRONG` or `ADEQUATE`; and
3. at least one candidate survives the existing BetSightly trust and market policy.

## Metrics to collect before any cutover discussion

- SportyBet catalogue completeness.
- SportyBet fixture count and supported-selection count.
- Prepared-board identity match rate.
- Cached API-Football support rate.
- Identity-state distribution.
- Enrichment-state distribution.
- Data-support distribution.
- Shadow prediction-ready count and rate.
- Existing-policy rejection distribution.

## Cutover rule

No production cutover is implemented by this branch.

A later decision must compare shadow coverage and correctness across enough real
boards and verify that SportyBet-first improves usable fixture coverage without
increasing wrong fixture mappings, stale mappings, memory pressure, or booking
mismatches. The production ESPN-first pipeline remains authoritative until that
separate evidence review is explicitly approved.
