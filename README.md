# Lunar Calendar API

Public **location-aware astronomical lunar calendar API** with an **optional private content plugin**.
This repository contains **no descriptions, historical interpretation text, category ratings or content dataset**. The astronomical calculations are local and always available, even without the private plugin.

The separate private repository `tiroq/moon-platform` stores the versioned JSON content and crawler pipeline. API processes **do not fetch GitHub repositories on incoming requests**: an operator mounts a private JSON snapshot or imports it into PostgreSQL.

## Run without content

```bash
python -m pip install -e '.[test]'
python -m lunar_api
# http://127.0.0.1:8000/docs
curl 'http://127.0.0.1:8000/v1/calendar/today?city=bangkok'
```

For example, without content a date/instant response includes the computed lunar-day number, `starts_at`, `ends_at`, and `summary.text` such as `5-й лунный день`. No recommendations or forecasts are invented. The number depends on local rise times: provide `city=` or `lat`, `lon`, `tz`.

## Plug in private JSON (no database required)

```bash
LUNAR_CONTENT_BACKEND=file \
LUNAR_CONTENT_FILE=/secure/moon-platform/content/v1/content.json \
uvicorn lunar_api.api:app
curl 'http://127.0.0.1:8000/v1/content/status'
curl 'http://127.0.0.1:8000/v1/content/lunar-days/5'
curl 'http://127.0.0.1:8000/v1/calendar/day?date=2026-10-14&city=moscow'
```

An updated JSON file is reloaded when its size/mtime changes. Do not commit the JSON or the private checkout here. The plugin is data-only and **does not execute arbitrary Python from a private repository**.

### Private package v1

```json
{
  "schema_version": 1,
  "content_version": "my-private-version",
  "provenance": "private-editorial",
  "categories": {},
  "days": {}
}
```

`days` is keyed by lunar-day numbers `"1"` … `"30"`. Each entry may contain:
`symbols`, `descriptions` (editorial/traditional/short/bot/practical/reflective),
`alternatives`, `categories` (slug -> score 1..5 + text),
`historical_sources` and permission-cleared `historical_texts`.
Optional `phases` and `zodiac` objects supply extra content endpoints.

## PostgreSQL deployment and migrations

```bash
cp .env.example .env    # change POSTGRES_PASSWORD
docker compose up -d --build
curl 'http://127.0.0.1:8000/v1/content/status'
```

Compose starts PostgreSQL 16 and the public FastAPI server, automatically applying the schema in `migrations/001_create_content_packages.sql`. With no active content package, the service still returns basic lunar information.

To install/activate private data, **on the server with access to the private checkout**:

```bash
python -m pip install -e '.[postgres]'
export DATABASE_URL='postgresql://user:password@host/lunar'
python scripts/content_db.py migrate
python scripts/content_db.py import --file /secure/moon-platform/content/v1/content.json --activate
python scripts/content_db.py status
```

For the built-in Docker Compose database (which is intentionally **not** exposed on the host), import from the public checkout with one command after `docker compose up -d --build`:

```bash
bash scripts/import_private_docker.sh /absolute/path/moon-platform/content/v1/content.json
curl http://127.0.0.1:8000/v1/content/status
```

The importer validates the package, computes SHA-256 and stores an **immutable** PostgreSQL JSONB snapshot. Existing version IDs cannot be silently overwritten with different content; importing without `--activate` cannot unset an active snapshot. Activation is atomic and limited to one version at a time. Running API workers cache active data for at most 10 seconds. A private helper `moon-platform/scripts/deploy_lunar_content.sh` first validates all rating URLs and scores against the independent private inventory, then applies the SQL migrations and activates the snapshot. Avoid exposing the database to the public Internet.

To roll back without changing any data files:

```bash
python scripts/content_db.py status
python scripts/content_db.py activate --version private-OLD_VERSION
```

The `/v1/content/status` response includes counts for source-backed ratings and historical reference links; it does not publish historical author prose without *both* the `LUNAR_ENABLE_SOURCE_PROSE=1` operator opt-in and an explicit `rights.third_party_prose_publication_allowed=true` in the private content package.

## HTTP endpoints

- `GET /healthz` — health check.
- `GET /v1/locations` — available city presets.
- `GET /v1/calendar/{today|tomorrow|day|instant|month|year}` — astronomically calculated local lunar calendar; `day` requires `date`.
- `GET /v1/content/status` — private plugin status and record counts.
- `GET /v1/content/lunar-days/{day}` — minimal placeholder, or imported descriptions/categories.
- `GET /v1/content/lunar-days/{day}/categories/{slug}` — 404 until private content exists.
- `GET /v1/content/categories` — imported categories, otherwise empty.
- `GET /v1/content/phases/{1..4}`, `GET /v1/content/zodiac/{sign}` — only when privately supplied.
- `GET /v1/recommendations/best-days` — only searches imported scores; no fabricated scores.
- `GET /v1/birth` — location-aware lunar-day computation.

The FastAPI OpenAPI schema is generated at `/openapi.json`; interactive docs are at `/docs`. Configure `LUNAR_API_KEYS` and `LUNAR_CORS_ORIGINS` where needed; API keys must not be embedded in browser JavaScript. Rate limiting and deployment-specific authentication remain separate operational requirements.

## Technical notes

Uses `pyswisseph` Moshier ephemerides and local lunar rises (not a fixed Moscow date), with no network calls for calculations. Dates 1900..2100. For inaccessible lunar rises (e.g., some polar cases), the lunar-day number may be null. Lunar symbolic predictions are editorial traditions, not scientifically validated guidance.

**License/rights:** review Swiss Ephemeris AGPL/professional licensing before commercial deployment. Third-party article reproduction requires suitable permission; a private Git repo alone does not grant redistribution rights.

**History:** the public `main` branch was rebuilt as an orphan root, so it has no historical prototype commits in its ancestry. Previously published commit SHA URLs or caches may nevertheless remain temporarily accessible; only deleting/recreating the repository can provide stronger administrative separation.
