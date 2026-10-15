"""Repository-neutral content plugin: no descriptions or rating tables are bundled.

Provision a package from a *private* deployment source, not from GitHub at
request time. The public service can run in none/file/postgres modes.
"""
from __future__ import annotations

from functools import lru_cache
import json
import os
from pathlib import Path
from threading import RLock
import time

_LOCK = RLock()
_FILE_CACHE: tuple[str, int, int, dict] | None = None
_DB_CACHE: tuple[float, dict | None] = (0.0, None)


class ContentConfigurationError(RuntimeError):
    pass


def validate_package(payload: object) -> dict:
    """Fail closed: a corrupt package must not silently become authoritative."""
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("Expected content package schema_version=1")
    days = payload.get("days")
    if not isinstance(days, dict):
        raise ValueError("Content package must contain a days object")
    for key, value in days.items():
        if not key.isdigit() or not 1 <= int(key) <= 30 or not isinstance(value, dict):
            raise ValueError(f"Invalid lunar day: {key}")
        descriptions = value.get("descriptions", {})
        if not isinstance(descriptions, dict) or any(
            not isinstance(k, str) or not isinstance(v, str)
            for k, v in descriptions.items()
        ):
            raise ValueError(f"Invalid descriptions: day {key}")
        categories = value.get("categories", {})
        if not isinstance(categories, dict):
            raise ValueError(f"Invalid categories: day {key}")
        for slug, item in categories.items():
            if not isinstance(slug, str) or not isinstance(item, dict):
                raise ValueError(f"Invalid category: day {key}")
            rating = item.get("score")
            if rating is not None and (type(rating) is not int or not 1 <= rating <= 5):
                raise ValueError(f"Invalid category score: {key}/{slug}")
    return payload


def _load_from_file() -> dict | None:
    global _FILE_CACHE
    filename = os.getenv("LUNAR_CONTENT_FILE", "").strip()
    if not filename:
        raise ContentConfigurationError("LUNAR_CONTENT_FILE required for file backend")
    path = Path(filename).expanduser()
    if not path.is_file():
        raise ContentConfigurationError("Configured content package is missing")
    stat = path.stat()
    key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    with _LOCK:
        if _FILE_CACHE is None or _FILE_CACHE[:3] != key:
            _FILE_CACHE = (*key, validate_package(json.loads(path.read_text(encoding="utf-8"))))
        return _FILE_CACHE[3]


def _load_from_postgres() -> dict | None:
    global _DB_CACHE
    now = time.monotonic()
    with _LOCK:
        if now - _DB_CACHE[0] < 10:
            return _DB_CACHE[1]
        dsn = os.getenv("DATABASE_URL")
        if not dsn:
            raise ContentConfigurationError("DATABASE_URL required for postgres backend")
        try:
            import psycopg
        except ImportError as exc:
            raise ContentConfigurationError("Install the postgres extra") from exc
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            row = conn.execute(
                "SELECT payload FROM lunar_content_packages "
                "WHERE activated_at IS NOT NULL ORDER BY activated_at DESC, id DESC LIMIT 1"
            ).fetchone()
        payload = validate_package(row[0]) if row else None
        _DB_CACHE = (now, payload)
        return payload


def package() -> dict | None:
    backend = os.getenv("LUNAR_CONTENT_BACKEND", "none").strip().lower()
    if backend == "none":
        return None
    if backend == "file":
        return _load_from_file()
    if backend == "postgres":
        return _load_from_postgres()
    raise ContentConfigurationError(f"Unsupported content backend: {backend}")


def _allow_third_party_prose(payload: dict | None) -> bool:
    """Deliberately require both an operator opt-in and a rights declaration."""
    return bool(
        payload
        and os.getenv("LUNAR_ENABLE_SOURCE_PROSE", "0") == "1"
        and payload.get("rights", {}).get("third_party_prose_publication_allowed") is True
    )


def status() -> dict:
    backend = os.getenv("LUNAR_CONTENT_BACKEND", "none").strip().lower()
    payload = package()
    days = payload["days"].values() if payload else ()
    categories = [cat for day in days for cat in day.get("categories", {}).values()]
    return {
        "backend": backend,
        "connected": payload is not None,
        "schema_version": payload.get("schema_version") if payload else None,
        "content_version": payload.get("content_version") if payload else None,
        "days": len(payload["days"]) if payload else 0,
        "category_records": len(categories),
        "source_rating_records": sum(
            cat.get("provenance") == "life_moon_structured_rating" for cat in categories
        ),
        "historical_reference_links": sum(
            len(day.get("historical_sources", ()))
            for day in payload["days"].values()
        ) if payload else 0,
        "historical_prose_enabled": _allow_third_party_prose(payload),
        "historical_prose_records_published": sum(
            len(day.get("historical_texts", ()))
            for day in payload["days"].values()
        ) if _allow_third_party_prose(payload) else 0,
    }


def day_content(day: int, style: str = "editorial") -> dict:
    if not 1 <= day <= 30:
        raise ValueError("Lunar day must be 1..30")
    payload = package()
    record = payload["days"].get(str(day)) if payload else None
    if not record:
        return {"lunar_day": day, "available": False, "description": f"{day}-й лунный день",
                "categories": {}, "alternatives": {}, "content_version": None}
    descriptions = record.get("descriptions", {})
    allow_prose = _allow_third_party_prose(payload)
    categories = {
        slug: ({k: v for k, v in item.items() if k not in {"text", "license_reference"}}
               if item.get("license_reference") and not allow_prose else item)
        for slug, item in record.get("categories", {}).items()
    }
    editorial = descriptions.get(style, descriptions.get("editorial", f"{day}-й лунный день"))
    if record.get("description_source") == "third_party_prose" and not allow_prose:
        editorial = f"{day}-й лунный день"
    return {
        "lunar_day": day, "available": True,
        "description": editorial,
        "categories": categories,
        "alternatives": record.get("alternatives", {}),
        "symbols": record.get("symbols", []),
        "historical_sources": record.get("historical_sources", []),
        "historical_texts": record.get("historical_texts", []) if allow_prose else [],
        "content_version": payload.get("content_version"),
        "provenance": payload.get("provenance", "private-content"),
    }


def categories() -> dict:
    payload = package()
    return payload.get("categories", {}) if payload else {}


def extra_content(kind: str, key: str) -> dict | None:
    if kind not in {"phases", "zodiac"}:
        raise ValueError("Unknown content type")
    payload = package()
    return payload.get(kind, {}).get(key) if payload else None
