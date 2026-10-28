# Basketball data procurement — verified provider routing
28 October 2026 · BetSightly private research. **No agreement or payment made.**

## One commercial inquiry for most leagues

Official partners and possible licensed commercial distribution:
- NBA/WNBA: https://pr.nba.com/nba-sportradar-global-partnership/
- EuroLeague/EuroCup: https://sportradar.com/content-hub/news/sportradar-scores-with-euroleague-basketball-official-data-and-av-betting-rights-deal/
- Australia NBL: https://www.nbl.com.au/news/nbl-taps-sportradar-to-elevate-the-game

**Primary first contact:** Sportradar sales via https://betradar.com/about-us/contact-us/ or
https://sportradar.com/ . Contact **sales@sportradar.com** is published on
Sportradar/Betradar's company product sheets. The distributor may quote
prices outside BetSightly's zero-cost constraint; **do not purchase
or start a paid subscription automatically**.

**Alternative approval route:** for WNBA, NBASTATS@NBA.com is published at
https://stats.wnba.com/help/ but their public statistics terms explicitly
restrict gambling-related use without separate permission:
https://www.wnba.com/terms-of-use .
Use it for referrals to the correct commercial licensing contact, not to
assert the stats team can license betting feeds.

NCAA men's/women's data is a **separate rights investigation**:
research@ncaa.org and ncaastats@ncaa.org are published at
https://www.ncaa.org/news/contact-us/ .

## Commercial requirements to request explicitly

1. Six named leagues, separately priced if necessary: NBA, WNBA, NCAA
   Division-I men's and women's, EuroLeague, EuroCup, Australian NBL.
2. Historical game schedule, before-tipoff roster/injury/team context,
   original scores, final scores, detailed market-settlement context.
3. Minimum two complete prior seasons, stable event/team IDs, timezone
   and rescheduling updates; overtime and official status definitions.
4. Permission for automated retention/storage, commercial ML training,
   models producing probabilistic predictions on a sports-betting-related
   website, derived works, display of final scores, and permitted
   geographic distribution (Nigeria and international users).
5. Startup/noncommercial paper-trial terms if available; distinguish
   trials and production rights; API limits, rights audit documents,
   prices, invoice currency, retention/expiry, revocation and SLA.
6. Independently verifiable scores and a second licensed crosscheck
   (provider may offer or approve one); provision a separate contract
   if the primary does not permit betting-related derivatives.

## Ready-to-send inquiry — Sportradar commercial data

To: sales@sportradar.com
Subject: BetSightly startup inquiry — licensed basketball historical data and prediction use

Hello Sportradar team,

I represent BetSightly, a Nigeria-based sports research and probabilistic
prediction platform. We are assessing an authorized dataset partnership,
especially for WNBA, EuroLeague/EuroCup and NBL Australia, plus NBA if
available.

Our usage includes retaining two or more historical seasons of fixtures,
official finalized scores, team and game-level statistics, and stable
event IDs, using those inputs to develop and independently evaluate
probabilistic pregame models. Resulting predictions may appear on a
commercial, betting-related website; we do not seek to redistribute
your raw data feed.

Could you confirm: (a) whether your rights permit this use and the
territories covered; (b) included competitions, seasons, source delays
and schedules; (c) whether official bookmaker settlement rights are
separate; (d) API and data-download options; and (e) whether a
low-cost startup or research-to-production arrangement is available?
Please include retention limits, audit terms and current pricing.

Thank you,
BetSightly

## Ready-to-send inquiry — NCAA data and rights

To: research@ncaa.org
Cc: ncaastats@ncaa.org
Subject: Division I basketball game-data licensing request — commercial model research

Hello NCAA Research and Statistics teams,

BetSightly is evaluating an authorized source for Division I men's and
women's basketball historical fixtures, official final scores and
team-level game statistics (at least two complete prior seasons).
We want to use this data for independently tested, pregame
probabilistic models that may be shown in a commercial sports
prediction product with betting-related context.

Please let us know which NCAA office or authorized provider can
license automated collection, database retention, derivative ML
research, and publication of derived predictions in this context.
What is the available coverage and pricing, and are there startup
or limited research pilots that can lead to a compliant production
agreement?

We will not re-publish NCAA source datasets or use them commercially
until the permitted scope has been confirmed.

Thank you,
BetSightly

## Release gate

Do not approve any league or turn on commercial ingestion based on
HTTP 200, a free trial, screenshots, an email response without
grant scope, or a provider's marketing page. Record only a
verified, signed, unexpired permission summary in the
`nba_research.basketball_data_rights` table.
Never upload full contracts into GitHub or expose provider API keys.
