# Zero-cost football settlement coverage: BetSightly pilot · 24 Oct 2026

**Non-negotiable budget: $0 per month.** This work must never authorize a
paid subscription, activate billing, turn on a suspended provider, or scrape
a consumer site whose terms prohibit it. The football prediction model and
calibration remain separate from manually curated booking results.

## What the live incident proves

At 2026-10-24 00:49 UTC, the production read-only audit reported 35 manual
tickets, 13 pending tickets and 151 unresolved legs across 47 distinct
bookmaker league labels. **Every one of those unresolved legs lacked an
ESPN-style league_slug**. The existing OpenLigaDB source only considered
manual legs with ger.1/ger.2/ger.3 slugs. Therefore it could not even attempt
to find a result from an unslugged German bookmaker selection. This
research-branch change allows exact and unique competition resolution via
the existing league metadata. It does not infer country from a generic
"1st Division" or "Premier League", and cannot settle unsupported leagues.

## Free-first verified results sources

| Source | Cost/access | Actual limitations | Operating choice |
| --- | --- | --- | --- |
| **OpenLigaDB** | $0, no key; ODbL 1.0 licensed data | User/community maintained; availability and freshness vary; currently our adapter supports Bundesliga 1/2/3 explicitly | Enable only supported leagues, exact match + verifiable FT score |
| **OpenScores** | $0 API key, expressly permits commercial products | Currently covers top-five leagues + 2026 World Cup; updates daily, **not continuous in-play** | Explore as a lawful delayed-score backstop, not a 10-minute FT SLA |
| **football-data.org** | $0 with free account/token, 12 competitions | Scores delayed; 10 calls/min; cannot fill small leagues | Existing 8-day bounded backup; retain |
| **TheSportsDB v1** | $0 key 123, 30 calls/min | Search/event method limits, crowdsourced scores; premium 2-minute live scores and v2 are not free; free licence targets development projects | Keep OFF in production pending terms review; use development/shadow coverage |
| **API-Football free** | $0, free key, 100 calls/day and all endpoints with season restrictions | Existing account was suspended; 100/day cannot sustain one-minute polling of dozens of games | Offline fixture-ID model only, do **not** reactivate until operator verifies active free account and the quota policy |
| **ESPN scoreboard** | Public accessible scores, no API key in current implementation | Public access is **not a commercial API licence**, coverage and uptime can change | Keep existing read-only source under current safeguards; do not assert legal redistribution right |
| **LiveScore consumer CDN** | Viewable website resources | LiveScore terms restrict automated extraction and commercial reuse without authorisation | Not eligible for unattended commercial settlement without rights |

Primary verified sources:
- OpenLigaDB API/licence: https://www.openligadb.de/
- OpenScores coverage, usage and cadence: https://openscores.ai/faq
- TheSportsDB free-vs-paid and terms:
  https://www.thesportsdb.com/docs/api and
  https://www.thesportsdb.com/docs_terms_of_use.php
- football-data.org free tier: https://www.football-data.org/pricing
- API-Football free quota/terms:
  https://www.api-football.com/pricing and https://www.api-football.com/terms
- LiveScore restriction:
  https://www.livescore.com/en/about-us/terms-and-conditions.html

## Proposed no-cost settlement architecture

1. **Before publishing:** store SportyBet event ID, UTC kickoff, teams,
   exact market, odds and bookmaker code immutably. Resolve its competition
   to an unambiguous provider slug or mark it `UNSUPPORTED_SCORE_COVERAGE`.
2. **During play:** read supported public/licensed live score snapshots for
   *display only*. Never derive won/lost from provisional/in-play goals.
3. **At full-time:** poll a cache-backed free scoreboard source in a bounded
   window, resolve the exact provider fixture ID and verify a regulation-time
   score. Persist evidence: source, provider event ID, UTC observation,
   home/away, score_90, match status, original bookmaker ID. Disagreeing
   providers remain pending for adjudication.
4. **Grade each leg immediately when final evidence arrives:** a losing leg
   makes an accumulator LOST. All won/void with at least one win makes it
   WON; entirely void becomes VOID. A missing score cannot become a win/loss
   through timeout or age.
5. **Publish states honestly:** distinguish `IN_PLAY`, `AWAITING_VERIFIED_FINAL`,
   `VERIFICATION_DELAYED`, `NEEDS_REVIEW`, WON/LOST/VOID. Show per-leg
   confirmation progress; Telegram's once-daily recap is not the live
   settlement mechanism.
6. **Coverage audit:** test the exact historical backlog of 151 against each
   free source and report matched event-ID %, verified-final %, unsupported
   leagues %, retrieval latency and usage-cost. Do not claim 10-minute SLA
   until observed verification time supports it.

## Acceptance criteria before enabling provider in production

- No subscription/credit card, hidden charge, expired free trial or unauthorised
  consumer CDN is required.
- Verified matching covers every league advertised as automatically settled.
  Publish previews warn prominently when a competition lacks score coverage.
- Cached API calls fit free quotas and obey documented terms.
- No fuzzy matching, no cross-date or reversed-team settlement, no live score
  settlement, no extra-time goals used for 90-minute markets, no fake voids.
- Original model calibration and official product history never mix with
  bookmaker-manual settlement statistics.
- Backfill the old 151 unresolved legs with exact evidence; do not overwrite
  or silently erase them when a source is missing.
- Record and surface genuine production results before claiming the work is
  finished. **This branch is research only, not a public production deploy.**

**Bottom line:** Zero-cost improvement is viable; a universal free,
legally-reusable, truly real-time score service for all 47 bookmaker
competition labels has not been demonstrated. Avoid promising blanket
10-minute settlement before the coverage test succeeds.
