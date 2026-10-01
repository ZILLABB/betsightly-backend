# V2 Run 1: runtime reliability audit (2026-10-01)

This is the Phase 0/4/19/20 audit against `origin/devil` at `cfbed720f` and
frontend `origin/dev` at `d8adad6`. It does not replace the V2 roadmap.

## Current request and preparation path

`/api/leagues/slip-builder/v2/generate` and `/manual` use `builder_v2`, which
requires the prepared seven-day board. Today and three-day results are filtered
from that same board. The compatibility Builder route can reach the legacy
optimizer; its public path checks prepared-board readiness first. Daily
publication uses `scheduler.run_daily_job`, which calls `run_pipeline(7)` and
then locks the official card. `prepared_board_store` optionally persists latest
and last healthy snapshots; persistence is **disabled by default**.

Before this change, a cold or stale public Builder/recommendations/fixtures
request launched `start_prepared_board_refresh`, a daemon thread running the
full provider/model pipeline in the web process. The old `/accumulators/today`
compatibility fallback could also call `build_daily_accumulators()` with
generation enabled. A process-local thread lock did not coordinate Gunicorn
workers. These are credible causes of the 460-518 MiB production spikes and
502/restarts reported for a 512 MiB instance; this audit has no production
heap profile proving the exact allocation split.

The request path now suppresses board/history prewarming in production even
when `ALLOW_INTERACTIVE_BOARD_REFRESH=true`. Development/staging can opt in
explicitly. Cold requests return a retryable `board_refreshing` response;
stale safe entries are filtered by kickoff and remain usable. The scheduled
seven-day board is the common source for shorter horizons. Public coverage
diagnostics cannot force a production pipeline run. Builder response caches
and in-memory prepared horizon entries are bounded.

## Runtime classification

| Component | Classification | Current process / memory | Run 2 ownership or action |
| --- | --- | --- | --- |
| `leagues/api.py`, `builder_v2.py`, `slip_builder.py` prepared reads | A ACTIVE_AND_REQUIRED | WEB / medium per request | WEB, prepared reads only |
| `engine.run_pipeline`, `scheduler.run_daily_job`, daily publication | B ACTIVE_BUT_SHOULD_NOT_RUN_IN_PUBLIC_WEB_PROCESS | WEB thread or protected HTTP trigger / high | Dedicated WORKER with scheduler claim |
| `engine.start_history_prewarm`, base rates, team history | B | WEB startup thread when background jobs enabled / high | WORKER |
| `results_checker` background loop | B | WEB thread / medium | SCHEDULER or WORKER |
| Telegram polling | B | WEB thread / medium, unknown peaks | Separate TELEGRAM worker |
| Growth publication and booking refresh | B | WEB daily thread / medium | SCHEDULER/WORKER |
| SportyBet fetch/match and ESPN fixtures | A for generation, B for web | Scheduler pipeline / high | WORKER |
| Prepared-board store and `daily_runs` claim | A | Database / bounded payload, optional in memory | Shared PostgreSQL, migrated schema |
| `/api/daily-predictions`, old `/api/accumulators`, `services/daily_predictions_service` | C LEGACY_COMPATIBILITY_STILL_USED | Mounted; service ML imported only on explicit generation | Prove consumers before retirement; GETs stay read-only |
| `/api/predictions`, `/api/fixtures`, punters, bookmakers | F UNKNOWN_REQUIRES_PROOF | Mounted; some external provider calls possible | Measure traffic and consumers before disabling |
| `api.endpoints.ml_predictions` | D LEGACY_SAFE_TO_DISABLE | Disabled by default behind `ENABLE_LEGACY_ML_API`; heavy imports avoided | Keep compatibility flag only |
| Legacy prediction settlement loop | D | Disabled by default | Retain disabled pending history proof |
| Basketball endpoint module | E DEAD_SAFE_TO_REMOVE from runtime, F for repository deletion | Not mounted or imported | Leave source until consumer check |
| Training scripts and football-first shadow modules | A offline/shadow, B if invoked in web | Not public Builder inference; optional shadow work can load models | Evaluate off web process |
| `services.cached_prediction_service` | F | Lazy via legacy prediction engine, may start its own scheduler | Confirm production traffic before removal |

No category-F source was deleted. Router compatibility was preserved.

## Cache and schema findings

The evaluated board has latest and last healthy slots. Serving a shorter
horizon does not need a second evaluation. The old in-process `_CACHE` could
retain up to 14 horizon keys, each with fixtures, models, and picks; it now
keeps at most three per slot. Target-result caches formerly retained full
Builder responses for unbounded request keys (including anonymous IDs); they
now expire and retain at most 32 results per cache. In-flight locks are not
removed. The new additive `add_prepared_board_cache` migration covers the
optional store. Fresh and previous-head disposable SQLite upgrades were
tested; production/staging migrations were not run.

RSS checkpoints now bracket ESPN and SportyBet fetch, enrichment, prediction,
candidate creation, persistence, and cleanup, with counts, snapshot ID,
duration at pipeline level, and thread source. Startup RSS was already logged.
The local Python 3.12 SQLite/no-provider import measured 15.5 MiB before
`main`, 84.5 MiB after `main`, and 84.6 MiB after `builder_v2`; this is not a
before/after provider-run comparison or evidence of a lower production peak.

## Ownership and remaining operational risk

The daily run has a database claim, while the opt-in interactive refresh uses
only a process-local lock. Production interactive refresh is disabled, so that
weak lock no longer coordinates public requests. The daily loop, protected
`run-daily` trigger, settlement loop, Telegram, and Growth work still run
inside a web process when enabled. The GitHub daily workflow calls the web
service; it is not a separate worker. A 512 MiB web instance can therefore
still restart during legitimate scheduled preparation. Changing this without
a running worker/scheduler deployment would risk missing the 08:00 WAT card.

Run 2 should deploy a dedicated process/container that runs the existing
daily claim and one seven-day preparation, verify the persisted board in a
shared PostgreSQL database, then disable web background jobs explicitly.
Docker Compose can provide `web`, `worker`, `scheduler`, `telegram`, and
`postgres` services; Kubernetes is unnecessary. The new migration should be
applied before enabling `PREPARED_BOARD_PERSISTENCE_ENABLED`, and the worker
must be the only owner of provider/model preparation. Confirm the Render or
future VPS memory limit with an actual full-board RSS trace before claiming
the memory incident is resolved.
