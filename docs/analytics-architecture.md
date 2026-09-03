# BetSightly analytics ownership

PostHog answers what people did: anonymous audience, acquisition, journeys,
funnels, retention, and interaction with SportyBet booking UI. PostgreSQL
answers what BetSightly did: predictions, results, builder runs, booking and
validation outcomes, catalogue health, rollover, settlement, jobs, publishing,
and referral configuration. The Admin Command Center aggregates both.

Vercel Web Analytics remains enabled as an independent traffic and deployment
sanity check. It is not used as PostHog identity and is not authoritative for
product behavior.

## Migration window

Canonical browser events are dual-written to the historical `growth_events`
store through `2026-09-17T23:59:59Z`. The two anonymous ID keys are retained
only for that comparison. They have no non-analytics dependency. Do not backfill
PostHog identities from their historical hashes.

After at least seven days of successful production ingestion and Admin Query
API retrieval, compare page views, prediction/rollover/builder users, code
viewers and copiers, SportyBet opens, referrers, countries, and devices. Explain
expected differences from identity, bot, and session definitions. Then remove
the legacy browser write and its rewrite; keep historical rows read-only.

## Failure behavior

PostHog Query API results are cached for five minutes in memory and PostgreSQL.
On failure, Admin serves the last cache marked `stale`; without a cache it marks
analytics `unavailable`. Prediction, Builder, Rollover, Results, and booking
paths never wait for analytics.

## Future GA4 trigger

Do not install GA4 until Google Ads is actively running, meaningful conversion
events have been selected, and Google-native attribution or optimization has
clear business value. If triggered, send only that narrow conversion set; do
not duplicate the PostHog taxonomy.
