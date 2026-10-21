# Production Lunar API — Render + private PostgreSQL content

This API is an explicit **release dependency** of `tiroq/lunar-telegram-bot`.
Passing API unit tests or bot CI is not proof that the public API and content are live.

## Topology and boundaries

- **Public** `tiroq/lunar-calendar-api`: Render Docker web service (`lunar-calendar-api`) and managed PostgreSQL (`lunar-calendar-db`), region Singapore.
- **Private** `tiroq/moon-platform`: authoritative `content/v1/content.json` and `site_inventory.json`, validated and imported using a **manual** GitHub Actions workflow. This private content is NEVER checked into the public API, a Docker image, or Render Blueprint.
- **Bot** `tiroq/lunar-telegram-bot`: Cloudflare Worker reads API over HTTPS and must use exactly the same `X-API-Key` (when configured).
- Public source prose stays disabled (`LUNAR_ENABLE_SOURCE_PROSE=0`), regardless of imported historical reference links.

## 1. Provision API infrastructure (manual and billable)

1. Review `render.yaml` and the current [Render pricing](https://render.com/pricing). **Creating the Blueprint provisions paid resources**; no code commit creates them.
2. Render Dashboard → **New → Blueprint** → connect `tiroq/lunar-calendar-api`, branch `main`, `render.yaml`.
3. The Blueprint configures a Docker web service and PostgreSQL 16 in **Singapore**, turns **automatic code deployments OFF**, uses `/healthz`, and installs the database connection via `DATABASE_URL`.
4. Provide `LUNAR_API_KEYS` securely in the Render Blueprint prompt (generate, e.g., `openssl rand -hex 32`). Do not put it in GitHub source files or logs.
5. Review charges and explicitly approve initial Blueprint sync. Wait for Render to report successful service deployment.

The database starts with **external access disabled** (`ipAllowList: []`); only same-region Render service can access it internally. The `scripts/start-production.sh` entrypoint checks for a PostgreSQL config, runs idempotent migrations, then starts Uvicorn using Render's `PORT`.

**Expected after bootstrap:** `/healthz` and `/v1/locations` return HTTP 200. Calendar calculations may work, but the 30-day editorial dataset is not yet imported. This is NOT bot readiness.

Record the actual Render HTTPS web-service origin (no `/v1` path) and configure:
- `moon-platform` → Actions **Variable** `LUNAR_API_BASE_URL`
- `moon-platform` → Actions **Secret** `LUNAR_API_KEY` (same value as one Render `LUNAR_API_KEYS`)
- `lunar-telegram-bot` → Actions **Variable** `LUNAR_API_BASE_URL`
- `lunar-telegram-bot` → Actions **Secret** `LUNAR_API_KEY` for CHECK
- `lunar-telegram-bot` → Cloudflare Worker **Secret** `LUNAR_API_KEY` for runtime

Do not assume the service hostname before reading it from Render Dashboard.

## 2. Import the private dataset (manually gated)

In Render's PostgreSQL details, find **External Database URL**. Configure a **temporary IP allowlist** for the trusted `tsrv` self-hosted runner's current public egress address, using only `/32` (not `0.0.0.0/0`). Note that subsequent Blueprint syncs with `ipAllowList: []` may re-disable external access by design.

In private `tiroq/moon-platform`, set:
- `production` GitHub Environment with manual approval (strongly recommended).
- Actions **Secret** `LUNAR_PROD_DATABASE_URL`: external PostgreSQL URL, TLS mandatory, append `?sslmode=require` (or `&sslmode=require` if other query parameters exist). Never store database passwords in the public API repository or bot.
- Actions **Variable** `LUNAR_API_BASE_URL`, and **Secret** `LUNAR_API_KEY` as above.

In **moon-platform Actions → Deploy verified private lunar content to production API**:
1. Run `confirm=CHECK`: source-ratings/inventory quality gate and public API bootstrap only; NO database mutation.
2. After reviewing content quality, taking an appropriate database backup/restore checkpoint, and verifying the egress IP allowlist, run `confirm=IMPORT`.
3. Import validates 720 source ratings, applies schema migration, atomically activates an immutable content snapshot, and verifies the expected `content_version` from the live API. An erroneous import or failed release must not be marked ready.
4. Revoke the temporary PostgreSQL external access CIDR when import is complete.

If a deploy needs repeated content refresh, re-open external access only for the controlled import window. Never automatically publish third-party authored source prose; manual rights review remains required.

## 3. Validate external API

From a machine with network connectivity (keep secrets outside command history):

```bash
export LUNAR_API_BASE_URL='https://ACTUAL-RENDER-SERVICE.onrender.com'
# Export LUNAR_API_KEY from your secret manager, do not paste into a GitHub issue.
python scripts/verify_prod_api.py                 # full 30x24 content and astronomical check
python scripts/verify_prod_api.py --bootstrap     # availability only
```

Full check verifies `/healthz`, Bangkok timezone, source content counts, 24 category entries, real lunar timeline, and the publication safety flag. It fails closed on missing private content or unexpected source-prose publishing.

Only then run the bot's `Deploy Lunar Telegram Bot to Cloudflare` workflow with `confirm=CHECK` and, after production backup/approval, `confirm=DEPLOY`.

## 4. Recovery

- For an incorrect *content version*: activate a known-good immutable version using `python scripts/content_db.py activate --version VERSION` with a trusted `DATABASE_URL`, then repeat the full API probe.
- For an incorrect *API build*: redeploy the last known-good Render revision; `autoDeployTrigger: off` ensures code changes do not automatically publish.
- PostgreSQL migrations are NOT rolled back by redeploying a previous Docker image. Review SQL changes and back up before structural updates.
- If Render API or database fails, the Telegram bot must not fabricate calendar or recommendation data. Keep bot rollout gated on successful API and source-content checks.

## Known risks

Paid Render resources incur charges after manual provisioning; no secrets/Render credentials exist in this repository. A self-hosted runner behind changing/NATed public IP requires updating the temporary `/32` rule. External PostgreSQL URLs require TLS. Render database remains a single point of failure without a separately tested backup/restore plan. Publication rights and astronomical ephemeris licensing must be reviewed before commercial launch.
