# September 22 historical-input measurement (review only)

Status: incomplete as-of comparison. Do not merge or deploy on the strength of
this document. Publication cutoff is 2026-09-22 07:00 UTC (08:00 WAT).

## What the immutable production record proves

The publication-associated four-day board was generated at 07:13:44 UTC from
106 ESPN fixtures and 874 candidate markets.
Its recorded generation time is **after** the requested 07:00 UTC replay
cutoff; it cannot by itself prove what was available exactly at 08:00 WAT.
Provider coverage was degraded:
99 of 116 requested leagues responded, 52 fixtures had a market price and 54
used base-rate-only pricing; 58 had SportyBet prices, 17 Elo, and 35 an ML
second opinion. The pipeline reported calibration on 769 settled legs. This is
the board associated with the daily product decisions. A later seven-day board
(275 fixtures, 2,199 candidates) is **not** the publication board.

The production log reported `Base rates computed for 1 leagues`. Source
inspection and an independent read-only ESPN check established that the one
entry was `_priors`: ESPN rejected the `YYYYMMDD-YYYYMMDD` request with HTTP
400, while its `YYYYMM` request returned 51 events for Brazil Serie B.
The same rejected request format was used by team history. The repaired code
retrieved 86 finished matches in a 45-day Brazil Serie B base-rate window and
191 in its longer team-history window when checked on September 23. These are
**present-day coverage checks**, not an as-of September 22 replay.

Of the 874 archived candidates, 131 belonged to 16 fixtures with a September
22 UTC kickoff. Of those 131, 29 had a public rank; 21 had real prices and
eight estimated prices. Safe-tier eligibility covered only three markets on
two fixtures. The published products tied to this board were: Banker 1.22x
(one leg), 2 Odds no safe combination, 5 Odds 4.09x (six legs, quality-capped),
and 10 Odds no safe combination. The 5 Odds card had three Under 4.5 legs and
five price-negative legs. These are archived decisions, not simulated outcomes.

## Why an exact OLD-versus-FIXED card is not yet defensible

The archived board contains compact evaluated candidates, but not the full
pre-publication fixture/market input, all source response timestamps, the
calibration fit as used at publication, or first-observed-completed timestamps
for historical ESPN results. The settled-forecast view likewise lacks an
observation timestamp suitable for reconstructing the 07:00 calibration set.
Fetching ESPN history today and filtering merely by match date would admit a
result whose completion was first observed after publication. Reusing current
calibration, Elo, odds, or availability would change more than the historical
input defect. Consequently the fixed funnel, fixed final cards, historical
coverage percentages, selector binding constraints, and each requested
OLD-versus-FIXED product answer are **not verified**. No 2x/10x or improved 5x
claim is made. September 22 final scores must not be used to pick a winner.

The new `as_of` history interface is deliberately fail-closed: it requires a
timezone-aware cutoff and an archived `observed_completed_at` no later than
that cutoff. A live ESPN response does not provide this field, so it cannot
stand in for an archived pre-publication observation. As-of requests bypass
current caches and do not write over them. This prevents an apparent replay
from silently using today's history, but it does not create the missing archive.

## Forward-only shadow comparison required

Starting with future boards, store once before publication (one row per
fixture-market, with shared fixture identity) the fixture/provider snapshot,
observation times, pre-kickoff bookmaker quote and margin, base-rate sample and
source, team/H2H sample counts, feature vector, calibration version and fit
cutoff, and six predictions: de-vigged bookmaker, current Poisson, calibrated
Poisson, trained ML only where its feature contract applies, production hybrid,
and simple league/base-rate baseline. Record abstention explicitly. Store
outcomes only after independent settlement; do not overwrite forecasts.

Evaluate chronological forward cohorts without duplicate fixture-market
observations. Report Brier, log loss, calibration error, coverage, abstention,
and bookmaker-relative scores only for genuine timestamped pre-kickoff prices.
Stratify by market family, competition type, league versus domestic cup, and
competition sample bands 0, 1-9, 10-24, and 25+. No production challenger is
activated by this protocol. The existing replay metadata explicitly says Elo
and ML were not used, so it cannot rank the requested six production paths.

## Cache and release gate

The old base-rate and team-history caches had no fetch-version marker and
could survive a code deployment. Both caches now require schema 2, the monthly
ESPN input fingerprint; schema-less files are rejected even on failure
fallback. Normal production history still uses its current clock. The cache
change and cutoff guard have focused tests. Before merging, obtain the missing
as-of archive or run a forward-only shadow cohort and inspect whether the new
historical coverage improves calibration and market selection without relaxing
quality rules. Nothing here authorizes republishing, catch-up, or settlement.
