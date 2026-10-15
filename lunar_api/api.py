"""HTTP API; the OpenAPI schema is available at /openapi.json and docs at /docs."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import os
import hmac
from functools import lru_cache
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import __version__
from .astro import daily_calendar, instant_calendar
from .content_provider import ContentConfigurationError, day_content, status as provider_status, categories as provider_categories, extra_content

app = FastAPI(title="Lunar Calendar API", version=__version__,
              description="Location-aware astronomical lunar days. Private descriptions are provided only by an optional content plugin.")

_ALLOWED_ORIGINS = [x.strip() for x in os.getenv("LUNAR_CORS_ORIGINS", "").split(",") if x.strip()]
if _ALLOWED_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=_ALLOWED_ORIGINS,
                       allow_methods=["GET"], allow_headers=["X-API-Key", "Content-Type"])

_API_KEYS = [x.strip() for x in os.getenv("LUNAR_API_KEYS", "").split(",") if x.strip()]

@app.middleware("http")
async def optional_api_key(request: Request, call_next):
    if _API_KEYS and request.url.path.startswith("/v1/"):
        supplied = request.headers.get("X-API-Key", "")
        if not any(hmac.compare_digest(supplied, key) for key in _API_KEYS):
            return JSONResponse(status_code=401, content={"detail":"Invalid or missing API key"})
    return await call_next(request)

# Exact coordinates, timezone: this is an intentionally small built-in convenience catalog.
CITY_CATALOG = {
    "moscow": (55.7558, 37.6173, "Europe/Moscow", "Москва"),
    "bangkok": (13.7563, 100.5018, "Asia/Bangkok", "Бангкок"),
    "phuket": (7.8804, 98.3923, "Asia/Bangkok", "Пхукет"),
    "london": (51.5074, -0.1278, "Europe/London", "Лондон"),
    "new-york": (40.7128, -74.0060, "America/New_York", "Нью-Йорк"),
    "tbilisi": (41.7151, 44.8271, "Asia/Tbilisi", "Тбилиси"),
    "berlin": (52.5200, 13.4050, "Europe/Berlin", "Берлин"),
    "tokyo": (35.6762, 139.6503, "Asia/Tokyo", "Токио"),
    "sydney": (-33.8688, 151.2093, "Australia/Sydney", "Сидней"),
}

class Geo(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    tz: str
    altitude_m: float = Field(default=0.0, ge=-500, le=9000)
    city: str | None = None


def geo_params(
    city: Annotated[str | None, Query(description="Preset city id (see /v1/locations)")] = None,
    lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    lon: Annotated[float | None, Query(ge=-180, le=180)] = None,
    tz: Annotated[str | None, Query(description="IANA timezone; mandatory for arbitrary coordinates unless timezonefinder is installed")] = None,
    altitude_m: Annotated[float, Query(ge=-500, le=9000)] = 0.0,
) -> Geo:
    if city:
        entry = CITY_CATALOG.get(city.lower())
        if entry is None:
            raise HTTPException(422, detail="Unknown preset city. Use lat, lon, tz or /v1/locations.")
        if lat is not None or lon is not None:
            raise HTTPException(422, detail="Specify city OR coordinates, not both")
        lat, lon, preset_tz, _ = entry
        tz = tz or preset_tz
    else:
        if lat is None or lon is None:
            raise HTTPException(422, detail="Provide city or both lat and lon")
        if tz is None:
            try:
                from timezonefinder import TimezoneFinder
                tz = TimezoneFinder(in_memory=True).timezone_at(lat=lat, lng=lon)
            except ImportError:
                raise HTTPException(422, detail="Pass tz=IANA/Timezone or install the 'geo' extra for coordinate-to-timezone lookup")
            if not tz:
                raise HTTPException(422, detail="Timezone not found for coordinates; pass tz explicitly")
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise HTTPException(422, detail="Unknown IANA timezone")
    return Geo(lat=lat, lon=lon, tz=tz, altitude_m=altitude_m, city=city)


def validate_date_range(start: date, end: date, max_days: int) -> None:
    if start.year < 1900 or end.year > 2100 or end < start or (end-start).days > max_days:
        raise HTTPException(422, detail=f"Dates must be 1900..2100, ordered, and at most {max_days} days apart")


def _content(n: int, style: str = "editorial") -> dict:
    try:
        return day_content(n, style)
    except ContentConfigurationError as exc:
        raise HTTPException(503, detail=f"Content backend not ready: {type(exc).__name__}") from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(503, detail="Invalid content package") from exc


def _summary(snapshot: dict, style: str = "editorial") -> dict:
    n = snapshot.get("lunar_day")
    payload = _content(n, style) if n else None
    label = payload["description"] if payload and payload["available"] else (
        f"{n}-й лунный день" if n else "Лунные сутки не определены для данного местоположения"
    )
    return {
        "lunar_day": n,
        "text": label,
        "starts_at": snapshot.get("lunar_day_starts_at"),
        "ends_at": snapshot.get("lunar_day_ends_at"),
        "enriched": bool(payload and payload["available"]),
        "content": payload if payload and payload["available"] else None,
    }


def get_day(d: date, geo: Geo, with_content: bool = True, include_events: bool = True) -> dict:
    snapshot = daily_calendar(d, geo.lat, geo.lon, geo.altitude_m, geo.tz,
                              include_events=include_events)
    if with_content:
        at_start = datetime.fromisoformat(snapshot["start_local"]) + timedelta(seconds=1)
        instant = instant_calendar(at_start, geo.lat, geo.lon, geo.altitude_m, geo.tz)
        snapshot["summary"] = _summary(instant)
        if include_events:
            snapshot["content_by_lunar_day"] = {
                str(n): _content(n)
                for n in sorted({x["lunar_day"] for x in snapshot["timeline"] if x["lunar_day"]})
            }
    return snapshot


@app.get("/healthz")
def health():
    return {"status": "ok", "version": __version__}


@app.get("/v1/locations")
def locations():
    return [{"id": k, "name": v[3], "lat": v[0], "lon": v[1], "tz": v[2]}
            for k, v in CITY_CATALOG.items()]


@app.get("/v1/content/status")
@app.get("/v1/content/source-status")
def content_status():
    try:
        return provider_status()
    except (ContentConfigurationError, ValueError, OSError) as exc:
        raise HTTPException(503, detail="Content backend not ready") from exc


@app.get("/v1/calendar/day")
def calendar_day(date_: Annotated[date, Query(alias="date")],
                 geo: Annotated[Geo, Depends(geo_params)], recommendations: bool = True):
    validate_date_range(date_, date_, 0)
    return get_day(date_, geo, recommendations)


@app.get("/v1/calendar/today")
def calendar_today(geo: Annotated[Geo, Depends(geo_params)], recommendations: bool = True):
    now = datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo(geo.tz)).date()
    result = get_day(today, geo, recommendations)
    if recommendations:
        result["summary"] = _summary(instant_calendar(now, geo.lat, geo.lon, geo.altitude_m, geo.tz))
    return result


@app.get("/v1/calendar/tomorrow")
def calendar_tomorrow(geo: Annotated[Geo, Depends(geo_params)], recommendations: bool = True):
    today = datetime.now(timezone.utc).astimezone(ZoneInfo(geo.tz)).date()
    return get_day(today+timedelta(days=1), geo, recommendations)


@app.get("/v1/calendar/instant")
def calendar_instant(at: datetime, geo: Annotated[Geo, Depends(geo_params)],
                     recommendations: bool = True, style: str = "editorial"):
    if at.tzinfo is None or at.utcoffset() is None:
        raise HTTPException(422, detail="at must have a timezone offset")
    if not 1900 <= at.year <= 2100:
        raise HTTPException(422, detail="Supported years: 1900..2100")
    result = instant_calendar(at, geo.lat, geo.lon, geo.altitude_m, geo.tz)
    if recommendations:
        result["summary"] = _summary(result, style)
    return result


@app.get("/v1/calendar/month")
def calendar_month(year: Annotated[int, Query(ge=1900, le=2100)],
                   month: Annotated[int, Query(ge=1, le=12)],
                   geo: Annotated[Geo, Depends(geo_params)], detail: bool = False):
    start = date(year, month, 1)
    end = date(year+1, 1, 1) if month == 12 else date(year, month+1, 1)
    rows = []
    current = start
    while current < end:
        rows.append(get_day(current, geo, detail))
        current += timedelta(days=1)
    return {"year": year, "month": month, "location": geo.model_dump(), "days": rows}


@app.get("/v1/calendar/year")
def calendar_year(year: Annotated[int, Query(ge=1900, le=2100)],
                  geo: Annotated[Geo, Depends(geo_params)]):
    rows = []
    current, end = date(year, 1, 1), date(year+1, 1, 1)
    while current < end:
        data = daily_calendar(current, geo.lat, geo.lon, geo.altitude_m, geo.tz,
                              include_events=False)
        rows.append({"date": data["date"], "lunar_day": data["lunar_day_at_start"],
                     "phase_index": data["moon"]["phase_index"]})
        current += timedelta(days=1)
    return {"year": year, "location": geo.model_dump(), "days": rows}


@app.get("/v1/content/categories")
def content_categories():
    try:
        return {"categories": provider_categories()}
    except (ContentConfigurationError, ValueError, OSError) as exc:
        raise HTTPException(503, detail="Content backend not ready") from exc


@app.get("/v1/content/phases/{phase_index}")
def content_phase(phase_index: int):
    if not 1 <= phase_index <= 4:
        raise HTTPException(422, detail="phase_index must be 1..4")
    try:
        data = extra_content("phases", str(phase_index))
    except (ContentConfigurationError, ValueError, OSError) as exc:
        raise HTTPException(503, detail="Content backend not ready") from exc
    if data is None:
        raise HTTPException(404, detail="No private phase description loaded")
    return {"phase_index": phase_index, **data}


@app.get("/v1/content/zodiac/{sign}")
def content_zodiac(sign: str):
    try:
        data = extra_content("zodiac", sign)
    except (ContentConfigurationError, ValueError, OSError) as exc:
        raise HTTPException(503, detail="Content backend not ready") from exc
    if data is None:
        raise HTTPException(404, detail="No private zodiac description loaded")
    return {"sign": sign, **data}


@app.get("/v1/content/lunar-days/{lunar_day}")
def content_day(lunar_day: int, style: str = "editorial"):
    if not 1 <= lunar_day <= 30:
        raise HTTPException(422, detail="lunar_day must be 1..30")
    return _content(lunar_day, style)


@app.get("/v1/content/lunar-days/{lunar_day}/categories/{category}")
def content_category(lunar_day: int, category: str, style: str = "editorial"):
    if not 1 <= lunar_day <= 30:
        raise HTTPException(422, detail="lunar_day must be 1..30")
    day = _content(lunar_day, style)
    item = day["categories"].get(category)
    if item is None:
        raise HTTPException(404, detail="Category not available from content plugin")
    return {"day": lunar_day, "category": category, **item,
            "content_version": day["content_version"]}


@app.get("/v1/recommendations/best-days")
def best_days(category: str, date_from: date, date_to: date,
              geo: Annotated[Geo, Depends(geo_params)],
              min_score: Annotated[int, Query(ge=1, le=5)] = 4):
    validate_date_range(date_from, date_to, 90)
    results = []
    current = date_from
    while current <= date_to:
        day = daily_calendar(current, geo.lat, geo.lon, geo.altitude_m, geo.tz)
        windows = []
        for segment in day["timeline"]:
            n = segment["lunar_day"]
            item = _content(n)["categories"].get(category) if n else None
            if item and item.get("score") is not None and item["score"] >= min_score:
                windows.append({"from": segment["from"], "to": segment["to"],
                                "lunar_day": n, "score": item["score"]})
        if windows:
            results.append({"date": current.isoformat(), "windows": windows})
        current += timedelta(days=1)
    return {"category": category, "dates": results,
            "source": "private-content" if results else "no_qualifying_content"}


@app.get("/v1/birth")
def birth(geo: Annotated[Geo, Depends(geo_params)], at: datetime | None = None,
          date_: Annotated[date | None, Query(alias="date")] = None):
    if (at is None) == (date_ is None):
        raise HTTPException(422, detail="Specify exactly one of at or date")
    if at is not None:
        if at.tzinfo is None or at.utcoffset() is None:
            raise HTTPException(422, detail="at must have a timezone offset")
        result = instant_calendar(at, geo.lat, geo.lon, geo.altitude_m, geo.tz)
        result["summary"] = _summary(result)
        return result
    validate_date_range(date_, date_, 0)
    result = get_day(date_, geo)
    result["possible_lunar_days"] = sorted({
        x["lunar_day"] for x in result["timeline"] if x["lunar_day"]
    })
    return result
