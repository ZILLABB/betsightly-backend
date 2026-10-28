# BetSightly — Contabo/Coolify provisioning and acceptance handoff

Status 2026-10-28: **configuration prepared, VPS NOT purchased or accessed**.

## Owner chooses and provisions VPS
- Candidate: Contabo Cloud VPS 8, 8 shared vCPU/24 GiB RAM and 150 GB NVMe
  or 300 GB SSD, Ubuntu **24.04 LTS**, EU region.
- Contabo advertises **€11.20/month for the first 24 months**. Review
  region, initial payment, prepaid term, taxes and renewal cost at checkout.
  Don't select an unaffordable prepaid term for a discount.
- Order on your own account. Create an Ed25519 SSH key on your own machine;
  upload only its **public** key. Never give anyone a private key, root
  password, database URL or API token in a chat.
- Once provisioned, record the public IP and retain provider recovery console.
  The IP alone grants no access. This ChatGPT conversation has no Contabo
  provider/SSH connection and cannot purchase or administer the server.

## Secure bootstrap before running BetSightly
- Use provider firewall where available: SSH from trusted source IP/VPN,
  HTTP 80/HTTPS 443 for public traffic; no public PG 5432, Redis 6379,
  API 18080. Coolify dashboard ports 8000/6001/6002 should be limited
  to authorized access and closed to the public after HTTPS setup.
- Establish SSH key login for a sudo account and verify reconnecting
  before restricting root or passwords, to avoid lockout.
- Install security updates, Docker Engine+Compose, PostgreSQL 18 client,
  and follow official Coolify install docs on a clean Ubuntu LTS instance.
- Inspect host using `python3 -m scripts.vps.preflight_host --phase preinstall`
  and again `--phase staging` after tooling setup.
- Secure Coolify login and configuration backup; route dashboard via HTTPS
  and protect admin access.

## Git-backed Coolify stack (recommended)
- Connect GitHub `ZILLABB/betsightly-backend` and initially select the
  **draft staging branch** `infra/vps-megabatch1-20261028`.
- Set build strategy to **Docker Compose from Git** and file path
  `compose.coolify.yml`, NOT `compose.vps.yml`. The Coolify recipe
  publishes **no host ports**. Give only the `api` component the HTTPS
  domain and set internal port **8000** in Coolify's Domains UI.
- Configure secrets and private PostgreSQL 18 connection in Coolify's
  protected environment variables; Git-based Compose references them
  but does not commit values. Use an **isolated staging database** with
  TLS `sslmode=require`, not the live Render production DB.
- The Compose `writers` and `telegram` profiles and
  `BETSIGHTLY_VPS_WRITER_ACTIVATION` remain disabled. Test the API
  first without publication/settlement/Telegram or NBA research jobs.
- Enable approved GitHub/webhook deployments only after staging
  health/readback tests and rollback checks. Do not use Coolify Raw Compose
  unless supplying all networking/proxy labels yourself.

## Standalone Docker Compose (diagnostics ONLY)
`compose.vps.yml` binds host port **127.0.0.1:18080** to API container
port 8000. It is for an alternate host-native proxy/manual debug approach,
NOT for Coolify proxy networking. Do not run both Compose strategies as
writers against the same database.

## Production-data move: separate, gated action
- Read-only Render inspection: PG 18.4, 53 public tables, ~380 MiB.
  Connected Render SQL tooling cannot export a complete `pg_dump`.
- From an **authorized private host**, back up with PG18 `pg_dump`,
  hash archive, encrypt and send an off-provider copy.
- Restore into a distinct empty database and verify schema/row parity
  at one captured snapshot watermark plus booking/settlement invariants.
  Never ship customer records through public GitHub Actions.
- Keep Render live until existing uninstrumented Render workers are
  explicitly fenced, final database sync is reconciled, rollback works,
  and your endpoints/SSL/jobs are verified on the actual VPS.
- Keep NBA private research on its independent Supabase/Vercel
  migration path; do not mix it with football production.

**STOP gate:** no automatic VPS production startup, migration or Render
service cancellation is authorized by passing synthetic GitHub CI.
