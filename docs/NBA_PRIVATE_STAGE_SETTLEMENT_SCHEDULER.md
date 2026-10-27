# Tokenless NBA private staging scheduler — activation and verification

## Security and zero-cost approach

New GitHub Actions jobs use **short-lived, GitHub-signed OIDC identities**, not
three permanent GitHub Actions secrets. GitHub issues the JWT from its managed
`ACTIONS_ID_TOKEN_REQUEST_URL` only when the job requests
`id-token: write`. The isolated Render staging service validates the RSA
signature using GitHub's fixed public JWKS, expected audience, issuer, exact
repository ID, default `dev` branch ref, exact workflow path and schedule /
manual-dispatch event. Tokens are never printed or stored in a database.

Server-side handlers are research only. They cannot accept caller fixtures,
rewrite frozen model predictions, make bets, generate SportyBet codes, publish
football products, or change football records. They reuse the staging-only
verified settlement/forecast/market evidence paths.

## Activation order — deployment must precede schedules

1. **Staging backend:** PR #186 is merged into
   `stage1/nba-private-research-20261024` as commit
   `fea13962a99e234f5824bbfddd3b953dc42d80a6`. Render service
   `srv-dbf7vde7bikc73ch5gg0` has auto deploy disabled, so deploy this
   exact latest staging commit via **Manual Deploy → Deploy latest commit**.
   Confirm Render shows it live and basic private health is still operating.
   Production football service `srv-d8hjd4rbc2fs73d6t010` is unrelated.
2. **GitHub workflow:** Only after staging is deployed, merge PR #183 into
   **default branch `dev`**. Public-repository GitHub-hosted cron does not
   require separate GitHub Actions secrets or paid data APIs.
3. **Authenticated smoke test:** In GitHub Actions, dispatch the settlement
   workflow and the forecast / market workflows. Require validated receipts
   and verify the corresponding private database `job_readiness` history.
4. **Unattended observation:** Confirm real scheduled invocations on two
   separate NBA game days, with fresh provider results, correct archive digest,
   and paper research reconciliation. An offline test alone is never proof
   that automation has run.

## Jobs and intended times (UTC/WAT)

- Final-score settlement: every half-hour at minutes 13 and 43 during
  01:00-12:59 UTC (02:13-13:43 WAT), plus 16:27 and 20:27 UTC catch-up.
- Pregame signed moneyline and original score forecasts: 15:16 and 18:16
  UTC (16:16 and 19:16 WAT). The experimental advanced model is not silently
  recomputed by this job.
- Private bookmaker market snapshot: 17:21 and 20:21 UTC (18:21 and
  21:21 WAT). Observations are not live guaranteed quotes or public tips.
- Existing protected Vercel daily jobs remain a best-effort fallback.
  GitHub schedule may be delayed or skipped under load; no minute-level
  settlement SLA is guaranteed.

## Fail-closed acceptance

The SHA-verified JWT must match every repository/workflow/ref/event claim;
wrong signature, token expiry, branch, PR event, cross-workflow claim or
provider failure returns an error rather than performing an operation.
A partial scoreboard read is not a successful settlement. No bets or real
stakes are placed. Private model scores must be independently assessed on
a larger sample before any public recommendations.

Offline checks:
`python3 -m unittest discover -s tests -p test_nba_stage_oidc_ping.py -v`
and
`python3 -m unittest discover -s tests -p test_nba_stage_github_oidc.py -v`
(the second runs on the staging service branch).

**Current status:** signed identity backend built and tested but not
confirmed deployed on Render; scheduled workflows in PR #183 unmerged.
