"""Versioned PostgreSQL content snapshot management (public code; private data external).

Usage:
  python scripts/content_db.py migrate
  python scripts/content_db.py import --file /secure/content.json --activate
  python scripts/content_db.py activate --version private-OLD_VERSION
  python scripts/content_db.py status

Snapshots are immutable per content_version. New imports never unset an active
version unless --activate is explicitly requested. Activation is transactional.
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


def database():
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("Install optional dependencies: pip install -e '.[postgres]'") from exc
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is required")
    return psycopg.connect(dsn, connect_timeout=10)


def migrate() -> None:
    migrations = sorted((ROOT / "migrations").glob("[0-9][0-9][0-9]_*.sql"))
    if not migrations:
        raise RuntimeError("No SQL migrations found")
    with database() as conn:
        with conn.transaction():
            for path in migrations:
                conn.execute(path.read_text(encoding="utf-8"))
    print(f"Applied migrations: {', '.join(path.name for path in migrations)}")


def _activate(conn, version: str) -> None:
    record = conn.execute(
        "SELECT id FROM lunar_content_packages WHERE content_version = %s FOR UPDATE",
        (version,),
    ).fetchone()
    if record is None:
        raise ValueError(f"No snapshot exists for content_version={version!r}")
    conn.execute(
        "UPDATE lunar_content_packages SET activated_at = NULL WHERE activated_at IS NOT NULL"
    )
    conn.execute(
        "UPDATE lunar_content_packages SET activated_at = now() WHERE id = %s",
        (record[0],),
    )


def import_package(file: Path, activate: bool) -> None:
    payload = validate_package(json.loads(file.read_text(encoding="utf-8")))
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    version = payload.get("content_version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("content_version must be a nonempty string")
    with database() as conn:
        with conn.transaction():
            current = conn.execute(
                "SELECT sha256 FROM lunar_content_packages WHERE content_version = %s FOR UPDATE",
                (version,),
            ).fetchone()
            if current is not None and current[0] != fingerprint:
                raise ValueError(
                    f"Immutable snapshot conflict: version {version!r} exists with different SHA-256"
                )
            if current is None:
                from psycopg.types.json import Jsonb
                conn.execute(
                    "INSERT INTO lunar_content_packages (content_version, sha256, payload) "
                    "VALUES (%s, %s, %s)",
                    (version, fingerprint, Jsonb(payload)),
                )
            if activate:
                _activate(conn, version)
    print(f"Imported/verified {version} (days={len(payload['days'])}, sha256={fingerprint}); activated={activate}")


def activate_version(version: str) -> None:
    with database() as conn:
        with conn.transaction():
            _activate(conn, version)
    print(f"Activated existing snapshot: {version}")


def status() -> None:
    with database() as conn:
        records = conn.execute(
            "SELECT content_version, sha256, imported_at, activated_at "
            "FROM lunar_content_packages ORDER BY id DESC LIMIT 20"
        ).fetchall()
    print(json.dumps([{
        "version": row[0], "sha256": row[1],
        "imported_at": row[2].isoformat(),
        "activated_at": row[3].isoformat() if row[3] else None,
    } for row in records], ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate")
    command = sub.add_parser("import")
    command.add_argument("--file", required=True, type=Path)
    command.add_argument("--activate", action="store_true")
    switch = sub.add_parser("activate", help="Activate an existing snapshot or roll back")
    switch.add_argument("--version", required=True)
    sub.add_parser("status")
    args = parser.parse_args()
    if args.command == "migrate":
        migrate()
    elif args.command == "import":
        import_package(args.file, args.activate)
    elif args.command == "activate":
        activate_version(args.version)
    else:
        status()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
