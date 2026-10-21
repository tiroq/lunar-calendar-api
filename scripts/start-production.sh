#!/bin/sh
# Production entrypoint: no secrets, private datasets or credentials in images/logs.
set -eu

: "${DATABASE_URL:?DATABASE_URL is required for PostgreSQL-backed production API}"
if [ "${LUNAR_CONTENT_BACKEND:-}" != "postgres" ]; then
  echo "LUNAR_CONTENT_BACKEND must be postgres in production" >&2
  exit 2
fi

PORT="${PORT:-8000}"
case "$PORT" in
  ''|*[!0-9]*) echo "PORT must be numeric" >&2; exit 2 ;;
esac

# The versioned migrations are idempotent and must complete before traffic.
python scripts/content_db.py migrate
exec uvicorn lunar_api.api:app --host 0.0.0.0 --port "$PORT"
