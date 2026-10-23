# BetSightly Command Center — Vercel migration

This is the **new isolated admin frontend**, mounted in admin-web until a dedicated repository is provisioned.
Existing Render /admin remains unchanged as the fallback. The public BetSightly frontend is not modified.

## Safety
- All admin reads/writes go through same-origin /api/proxy, never a browser-direct Render request.
- The proxy permits an explicit API allowlist, validates mutation Origin, forwards the httpOnly SameSite=Strict cookie, and avoids credential exposure.
- The backend still enforces require_admin, signed sessions, and booking validation.
- No automatic retry of publication, especially after a network timeout.
- Never move admin.betsightly.com or disable the existing admin until verified login, manual import / preview / publish and read-back, content and settings on a protected Vercel deployment.

## Setup
Configure `ADMIN_BACKEND_ORIGIN=https://betsightly-api.onrender.com` as **server-only** project env (not VITE_*).
Protect previews and deployment URLs with Vercel Authentication. Do not make the custom domain public without backend auth/CSRF smoke tests.
Run `npm install && npm run build` inside admin-web.
For local BFF testing run `vercel dev`; Vite alone cannot emulate Vercel functions.

## Release gates
1. Vercel preview build must complete.
2. Confirm login and session refresh/logout; inspect Set-Cookie and SameSite.
3. Test 401, 403, slow response, 502, and lost-response-after-commit (manual).
4. Import representative normal/early-goal SportyBet codes with review; verify exact leg counts, market mapping and actual prices.
5. Publish only an explicitly approved test ticket, verify DB read-back, website display, results and Telegram (must not affect model calibration).
6. Compare data and all settings with legacy admin before domain switch.
7. Keep Render /admin rollback access throughout migration.

**Never add passwords, API keys or cookie signing secrets to Git or Vite variables.**
