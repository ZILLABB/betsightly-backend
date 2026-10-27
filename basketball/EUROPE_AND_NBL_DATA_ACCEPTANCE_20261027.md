# Multi-league candidate evidence — 27 Oct 2026

## EuroLeague and EuroCup
Public-facing source research (not a commercial license): EuroLeague v2 competition/season games, documented by the SportsDataverse hoopR game reference. The new `research_europe_sources.py` performs a single bounded read-only page inspection and verifies that identities are unique and the page count is consistent. It does **not** import raw games into training, verify final scores or bookmaker selection IDs, resolve club aliases, or publish predictions.

Next gates: independently compare actual completed games with a second primary source, resolve competition-specific season/team IDs, verify timestamps/periods and postponements, implement league-specific chronological holdout benchmarks, and obtain a data-rights decision before model training or commercial redistribution.

## Australian NBL
NBL's official statistics site offers historical season views. A separately documented unofficial Rosetta proxy is referer-gated and its reuse rights have not been approved; **do not bypass that gate or silently treat it as an official open API**. No automated adapter should be deployed until legal terms and authorized API/data access are confirmed.

## Invariants
- Neither European competition nor NBL can write to the isolated NBA archive.
- A fetched game or listed bookmaker market is *not* evidence of a validated forecast.
- Never infer NBA's 12-minute quarter rules for WNBA, NCAA or FIBA competitions.
- Before enabling model training or settlement require independent finals, complete verified seasons, fixed club IDs, explicit betting market identities, overtime/void rules, and per-league calibration.
- No public odds, SportyBet code generation, stakes or model promotion in this batch.

Sources (reference only):
- https://hoopr.sportsdataverse.org/reference/euroleague_games.html
- https://www.nbl.com.au/stats/statistics
- https://sportsdataverse-py.sportsdataverse.org/docs/nbl_au/reference/nbl_rosetta
