# Competition coverage audit — 2026-09-09

The runtime source of truth is `leagues/competition_registry.py`; the protected
`GET /api/leagues/competition-coverage` endpoint reports live provider,
historical-rate, rating and SportyBet health for every registry entry.

All 91 previously configured competition slugs remain enabled. The following
25 additions were verified directly against ESPN's scoreboard API. “Results”
means the probe returned completed events with stable provider team identities;
it does not imply that every future fixture will carry odds or be listed by
SportyBet.

| Competition | ESPN slug | Type / region | Probe window | Events / completed | Prediction + settlement | Known limitation |
|---|---|---|---|---:|---|---|
| UEFA Super Cup | `uefa.super_cup` | continental club / Europe | 2025-08 | 1 / 1 | enabled | very thin annual sample |
| UEFA Nations League | `uefa.nations` | international tournament / Europe | 2026-09 | 52 scheduled/current | enabled | national rating evidence varies |
| European Championship | `uefa.euro` | international tournament / Europe | 2024-06–07 | 51 / 51 | enabled | knockout/neutral context required |
| Euro qualifying | `uefa.euroq` | international qualifier / Europe | 2023-10–11 | 92 / 92 | enabled | thin groups shrink to qualifier prior |
| FIFA World Cup | `fifa.world` | international tournament / Global | 2026-06–07 | 104 / 104 | enabled | regulation-time settlement only |
| World Cup qualifying — UEFA | `fifa.worldq.uefa` | international qualifier / Europe | 2025-03–11 | 192 / 192 | enabled | SportyBet availability varies by round |
| World Cup qualifying — CAF | `fifa.worldq.caf` | international qualifier / Africa | 2025-03–10 | 162 / 156 | enabled | postponed/unplayed rows remain ungraded |
| World Cup qualifying — Concacaf | `fifa.worldq.concacaf` | international qualifier / N. America | 2025-06–11 | 66 / 66 | enabled | SportyBet naming varies |
| World Cup qualifying — AFC | `fifa.worldq.afc` | international qualifier / Asia | 2025-03–10 | 42 / 42 | enabled | SportyBet availability varies |
| World Cup qualifying — CONMEBOL | `fifa.worldq.conmebol` | international qualifier / S. America | 2025-03–09 | 30 / 30 | enabled | league-format context |
| World Cup qualifying — OFC | `fifa.worldq.ofc` | international qualifier / Oceania | 2025-03 | 3 / 3 | enabled | very thin; safe tiers remain gated |
| International Friendly | `fifa.friendly` | international friendly / Global | 2026-09 | 24 scheduled/current | enabled | lowest priority; motivation uncertainty |
| Africa Cup of Nations | `caf.nations` | international tournament / Africa | 2025-12–2026-01 | 52 / 52 | enabled | neutral/knockout context required |
| AFCON qualifying | `caf.nations_qual` | international qualifier / Africa | 2024-09–11 | 144 / 144 | enabled | SportyBet availability varies |
| Copa América | `conmebol.america` | international tournament / S. America | 2024-06–07 | 32 / 32 | enabled | tournament-host effects not estimated |
| Concacaf Gold Cup | `concacaf.gold` | international tournament / N. America | 2025-06–07 | 31 / 31 | enabled | tournament-host effects not estimated |
| AFC Asian Cup | `afc.asian.cup` | international tournament / Asia | 2024-01–02 | 51 / 51 | enabled | tournament-host effects not estimated |
| CAF Champions League | `caf.champions` | continental club / Africa | 2025-04–05 | 13 / 13 | enabled | current preliminary ties absent on SportyBet board |
| CAF Confederation Cup | `caf.confed` | continental club / Africa | 2025-04–05 | 14 / 14 | enabled | current preliminary ties absent on SportyBet board |
| AFC Champions League Elite | `afc.champions` | continental club / Asia | 2025-04–05 | 7 / 7 | enabled | current SportyBet availability incomplete |
| AFC Champions League Two | `afc.cup` | continental club / Asia | 2025/2026 | 5 / 5 per tested final window | enabled | current SportyBet availability incomplete |
| Coupe de France | `fra.coupe_de_france` | domestic cup / France | 2026-01 | 16 / 16 | enabled | cup sample shrinks hierarchically |
| Taca de Portugal | `por.taca.portugal` | domestic cup / Portugal | 2026-01 | 3 / 3 | enabled | very thin annual window |
| Dutch KNVB Beker | `ned.cup` | domestic cup / Netherlands | 2026-01 | 8 / 8 | enabled | cup sample shrinks hierarchically |
| Scottish Cup | `sco.tennents` | domestic cup / Scotland | 2026-01 | 16 / 16 | enabled | cup sample shrinks hierarchically |

## Live seven-day snapshot

The 2026-09-09 probe returned 623 upcoming fixtures across 59 active
competitions; 354 carried ESPN market probabilities. SportyBet's complete
1,535-fixture board matched 424 fixtures. Tournament matches included 10/12
Champions League, 7/9 Europa League, 10/10 Carabao Cup, 3/6 Libertadores and
4/5 Sudamericana. CAF/AFC preliminary fixtures were not present on that board,
so they can enter prediction history but cannot enter the Builder while exact
SportyBet bookability remains mandatory.

## Domestic cup gaps

Verified cups now cover England, Spain, Germany, Italy, France, Portugal,
Netherlands and Scotland. Other tracked countries remain without an enabled
domestic cup until their ESPN fixture/result identity is verified. No fallback
slug is inferred from the domestic league name.

## Attempted but not enabled

| Competition | Attempted slug | Reason |
|---|---|---|
| OFC Nations Cup | `ofc.nations` | no ESPN competition identity or events returned for the tested 2024 window |
| CAF Super Cup | `caf.super`, `caf.super_cup` | no verifiable ESPN competition payload returned for the tested 2024 window |

Qualification-only bookmaker outcomes remain unsupported and are never mapped
onto regulation-time Home Win or Away Win.
