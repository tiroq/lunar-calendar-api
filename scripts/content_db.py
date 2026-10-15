"""Apply the public PostgreSQL schema and activate a private JSON content snapshot.

No database records or third-party content are committed to the public repo.
Usage:
  python scripts/content_db.py migrate
  python scripts/content_db.py import --file /secure/private/content.json --activate
  python scripts/content_db.py status
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from lunar_api.content_provider import validate_package

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "001_create_content_packages.sql"


def database():
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("pip install -e '.[postgres]'") from exc
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required")
    return psycopg.connect(url, connect_timeout=10)


def migrate() -> None:
    with database() as conn:
        with conn.transaction():
            conn.execute(MIGRATION.read_text(encoding="utf-8"))
    print("Migration 001 applied")


def import_package(file: Path, activate: bool) -> None:
    payload = validate_package(json.loads(file.read_text(encoding="utf-8")))
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    version = payload.get("content_version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("content_version must be a nonempty string")
    with database() as conn:
        with conn.transaction():
            import psycopg.types.json
            conn.execute(
                "INSERT INTO lunar_content_packages (content_version, sha256, payload) "
                "VALUES (%s, %s, %s) "
                "ON CONFLICT (content_version) DO UPDATE SET sha256=EXCLUDED.sha256, "
                "payload=EXCLUDED.payload, imported_at=now(), activated_at=NULL",
                (version, fingerprint, psycopg.types.json.Jsonb(payload)),
            )
            if activate:
                conn.execute("UPDATE lunar_content_packages SET activated_at = NULL "
                             "WHERE activated_at IS NOT NULL")
                conn.execute(
                    "UPDATE lunar_content_packages SET activated_at = now() "
                    "WHERE content_version = %s", (version,)
                )
    print(f"Imported {version} (days={len(payload['days'])}, sha256={fingerprint}); active={activate}")


def status() -> None:
    with database() as conn:
        rows = conn.execute(
            "SELECT content_version, sha256, imported_at, activated_at "
            "FROM lunar_content_packages ORDER BY id DESC LIMIT 20"
        ).fetchall()
    print(json.dumps([{
        "version": r[0], "sha256": r[1], "imported_at": r[2].isoformat(),
        "activated_at": r[3].isoformat() if r[3] else None,
    } for r in rows], ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate")
    command = sub.add_parser("import")
    command.add_argument("--file", required=True, type=Path)
    command.add_argument("--activate", action="store_true")
    sub.add_parser("status")
    args = parser.parse_args()
    if args.command == "migrate":
        migrate()
    elif args.command == "import":
        import_package(args.file, args.activate)
    else:
        status()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
