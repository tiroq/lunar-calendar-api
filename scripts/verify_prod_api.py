#!/usr/bin/env python3
"""Read-only Lunar API deployment probe. Never print keys, URLs or payloads."""
from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class ProbeError(Exception):
    pass


def check_origin(raw: str) -> str:
    parsed = urlsplit(raw)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment):
        raise ProbeError("LUNAR_API_BASE_URL must be an HTTPS origin with no path, query or credentials")
    return raw.rstrip("/")


def fetch_json(origin: str, path: str, api_key: str = "", opener=urlopen) -> object:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    try:
        with opener(Request(origin + path, headers=headers), timeout=90) as response:
            if response.status != 200:
                raise ProbeError(f"{path}: HTTP {response.status}")
            return json.load(response)
    except ProbeError:
        raise
    except Exception:
        # Avoid printing exception URLs: HTTP libraries may include embedded auth.
        raise ProbeError(f"{path}: HTTP request or JSON parsing failed") from None


def verify(origin: str, *, api_key: str = "", ready: bool = True,
           expected_version: str = "", opener=urlopen) -> None:
    origin = check_origin(origin)
    health = fetch_json(origin, "/healthz", api_key, opener)
    if not isinstance(health, dict) or health.get("status") != "ok":
        raise ProbeError("/healthz: expected status=ok")
    print("PASS /healthz")

    locations = fetch_json(origin, "/v1/locations", api_key, opener)
    if not isinstance(locations, list) or not any(
        isinstance(location, dict) and location.get("id") == "bangkok"
        and location.get("tz") == "Asia/Bangkok" for location in locations
    ):
        raise ProbeError("/v1/locations: Bangkok IANA timezone is missing")
    print("PASS /v1/locations")

    if not ready:
        return

    status = fetch_json(origin, "/v1/content/status", api_key, opener)
    if not isinstance(status, dict) or any((
        status.get("connected") is not True,
        status.get("backend") != "postgres",
        status.get("days") != 30,
        status.get("category_records") != 720,
        status.get("historical_prose_records_published") != 0,
    )):
        raise ProbeError("/v1/content/status: PostgreSQL/private content not ready or prose publishing enabled")
    if expected_version and status.get("content_version") != expected_version:
        raise ProbeError("/v1/content/status: content_version is not the expected release")
    print("PASS /v1/content/status (30 days, 720 ratings; source prose disabled)")

    categories = fetch_json(origin, "/v1/content/categories", api_key, opener)
    if not isinstance(categories, dict) or not isinstance(categories.get("categories"), dict) or len(categories["categories"]) != 24:
        raise ProbeError("/v1/content/categories: expected 24 categories")
    print("PASS /v1/content/categories")

    today = fetch_json(origin, "/v1/calendar/today?city=bangkok", api_key, opener)
    if not isinstance(today, dict) or not isinstance(today.get("timeline"), list):
        raise ProbeError("/v1/calendar/today: invalid lunar timeline")
    print("PASS /v1/calendar/today?city=bangkok")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", action="store_true", help="Check HTTP service only; private content may be pending")
    parser.add_argument("--expected-version", default="", help="Require an exact active content_version")
    args = parser.parse_args()
    try:
        verify(os.environ.get("LUNAR_API_BASE_URL", ""), api_key=os.environ.get("LUNAR_API_KEY", ""),
               ready=not args.bootstrap, expected_version=args.expected_version)
    except ProbeError as exc:
        print("FAIL " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
