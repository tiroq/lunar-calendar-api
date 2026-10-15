#!/usr/bin/env bash
# Import a private package into the containerized PostgreSQL without exposing its port.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$#" -ne 1 ]]; then
  echo "Usage: $0 /absolute/path/to/private/content/v1/content.json" >&2
  exit 2
fi
PACKAGE="$(realpath "$1")"
if [[ ! -f "$PACKAGE" ]]; then
  echo "Content file not found: $PACKAGE" >&2
  exit 2
fi
cd "$REPO_ROOT"
docker compose run --rm --no-deps \
  -v "$PACKAGE:/run/private-lunar-content.json:ro" \
  api python scripts/content_db.py import \
  --file /run/private-lunar-content.json --activate
echo "Private content activated; query /v1/content/status"
