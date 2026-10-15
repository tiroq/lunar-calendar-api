"""Astronomical computation using local Swiss Ephemeris / Moshier (no live API).

Conventions: tropical geocentric zodiac, lunar day 1 at conjunction and
subsequent lunar days at local lunar rises. Local rise times depend on latitude,
longitude, elevation and atmospheric settings. Return no fabricated rises in
polar regions where the Moon does not rise in the requested interval.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date, time, timedelta, timezone
from functools import lru_cache
from math import floor
from zoneinfo import ZoneInfo
import swisseph as swe

EPOCH_JD = 2440587.5
FLAGS = swe.FLG_MOSEPH
UTC = timezone.utc
ZODIAC = ["Овен", "Телец", "Близнецы", "Рак", "Лев", "Дева", "Весы", "Скорпион", "Стрелец", "Козерог", "Водолей", "Рыбы"]
ZODIAC_IDS = ["aries", "taurus", "gemini", "cancer", "leo", "virgo", "libra", "scorpio", "sagittarius", "capricorn", "aquarius", "pisces"]
PHASE_NAMES = ["первая фаза", "вторая фаза", "третья фаза", "четвёртая фаза"]
PHASE_EVENTS = {0: "new_moon", 90: "first_quarter", 180: "full_moon", 270: "last_quarter"}


def to_jd(dt: datetime) -> float:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("datetime must include timezone")
    return dt.timestamp() / 86400.0 + EPOCH_JD


def from_jd(jd: float) -> datetime:
    return datetime.fromtimestamp((jd-EPOCH_JD)*86400.0, UTC)


def iso(jd: float, tz: ZoneInfo) -> str:
    return from_jd(jd).astimezone(tz).isoformat(timespec="seconds")


def elongation(jd: float) -> float:
    moon = swe.calc_ut(jd, swe.MOON, FLAGS)[0][0]
    sun = swe.calc_ut(jd, swe.SUN, FLAGS)[0][0]
    return (moon - sun) % 360


def signed_cross(jd: float, target: float) -> float:
    return (elongation(jd) - target + 180) % 360 - 180


def _phase_crossings(start_jd: float, end_jd: float, targets: tuple[int, ...]) -> list[tuple[float, int]]:
    # At most ~15 deg/day: 0.5d scan avoids skipping phase thresholds.
    step = 0.5
    t = start_jd
    events = []
    while t < end_jd:
        nxt = min(t + step, end_jd)
        for target in targets:
            a, b = signed_cross(t, target), signed_cross(nxt, target)
            if a <= 0 < b and b-a < 30:
                lo, hi = t, nxt
                for _ in range(40):
                    mid = (lo + hi) / 2
                    if signed_cross(mid, target) > 0:
                        hi = mid
                    else:
                        lo = mid
                    if hi-lo < 1e-9:
                        break
                root = (lo+hi)/2
                events.append((root, target))
        t = nxt
    return sorted(events)


@lru_cache(maxsize=500)
def _new_moons_near_month(year: int, month: int) -> tuple[float, ...]:
    # Cached by UTC month: one scan covers every date and lunation boundary.
    first = to_jd(datetime(year, month, 1, tzinfo=UTC))
    return tuple(jd for jd, _ in _phase_crossings(first-40, first+75, (0,)))


def _new_moons_near_day(day_utc: date) -> tuple[float, ...]:
    return _new_moons_near_month(day_utc.year, day_utc.month)


def lunar_month_bounds(jd: float) -> tuple[float, float]:
    events = _new_moons_near_day(from_jd(jd).date())
    prev = [x for x in events if x <= jd]
    after = [x for x in events if x > jd]
    if not prev or not after:
        raise ValueError("unable to establish lunation boundaries")
    return prev[-1], after[0]


def zodiac_idx(jd: float) -> int:
    return int(swe.calc_ut(jd, swe.MOON, FLAGS)[0][0] // 30) % 12


def rise_set_after(jd: float, longitude: float, latitude: float, altitude: float, rise: bool) -> float | None:
    mode = swe.CALC_RISE if rise else swe.CALC_SET
    try:
        code, result = swe.rise_trans(jd + 1e-7, swe.MOON, mode,
                                      (longitude, latitude, altitude), flags=FLAGS)
        if code != 0:
            return None
        when = float(result[0])
        return when if when >= jd else None
    except swe.Error:
        return None


@lru_cache(maxsize=4096)
def local_lunar_boundaries(new_jd: float, next_new_jd: float,
                           longitude: float, latitude: float, altitude: float) -> list[float]:
    result = [new_jd]
    cursor = new_jd
    for _ in range(33):
        nxt = rise_set_after(cursor, longitude, latitude, altitude, rise=True)
        if nxt is None or nxt >= next_new_jd - 1e-8:
            break
        if nxt - cursor < 1e-5:
            break
        result.append(nxt)
        cursor = nxt + 0.00001
    return result


def lunar_day_state(jd: float, longitude: float, latitude: float, altitude: float) -> dict:
    start, finish = lunar_month_bounds(jd)
    boundaries = local_lunar_boundaries(start, finish, longitude, latitude, altitude)
    idx = max(i for i, b in enumerate(boundaries) if b <= jd)
    next_boundary = boundaries[idx+1] if idx+1 < len(boundaries) else finish
    # Near polar regions the moon may have no daily rise; day number then has
    # no normal day-by-day interpretation. Signal this rather than guessing.
    observable = len(boundaries) >= 25
    return {
        "number": min(idx+1, 30) if observable else None,
        "starts_at_jd": boundaries[idx],
        "ends_at_jd": next_boundary,
        "lunation_starts_at_jd": start,
        "lunation_ends_at_jd": finish,
        "rise_count_in_lunation": len(boundaries)-1,
        "observable": observable,
    }


def phase_snapshot(jd: float) -> dict:
    el = elongation(jd)
    moon_position = swe.calc_ut(jd, swe.MOON, FLAGS)[0][0]
    fraction = swe.pheno_ut(jd, swe.MOON, FLAGS)[1]
    q = min(int(el // 90), 3)
    z = zodiac_idx(jd)
    return {
        "elongation_degrees": round(el, 3),
        "moon_longitude_degrees": round(moon_position, 3),
        "illuminated_fraction": round(fraction, 4),
        "phase_index": q+1,
        "phase_name": PHASE_NAMES[q],
        "waxing": el < 180,
        "zodiac": {"id": ZODIAC_IDS[z], "name": ZODIAC[z], "index": z+1},
    }


def events_in_interval(start_jd: float, end_jd: float,
                       longitude: float, latitude: float, altitude: float) -> list[dict]:
    events: list[dict] = []
    for t, angle in _phase_crossings(start_jd, end_jd, (0, 90, 180, 270)):
        events.append({"jd": t, "type": PHASE_EVENTS[angle]})
    z = zodiac_idx(start_jd)
    t = start_jd
    for _ in range(5):
        try:
            nxt = swe.mooncross_ut((z+1)*30 % 360, t + 1e-7, FLAGS)
        except swe.Error:
            break
        if nxt >= end_jd:
            break
        z = (z+1) % 12
        events.append({"jd": nxt, "type": "zodiac_ingress", "zodiac": ZODIAC_IDS[z]})
        t = nxt + 1e-5
    for rise, event_type in [(True, "moonrise"), (False, "moonset")]:
        t = start_jd
        for _ in range(4):
            nxt = rise_set_after(t, longitude, latitude, altitude, rise)
            if nxt is None or nxt >= end_jd:
                break
            events.append({"jd": nxt, "type": event_type})
            t = nxt + 1e-5
    # Conjunction always resets to lunar day 1; moonrises after conjunction
    # increment the day, not moonrises before it.
    for event in events:
        if event["type"] in {"moonrise", "new_moon"}:
            event["lunar_day_after"] = lunar_day_state(event["jd"]+1e-5, longitude, latitude, altitude)["number"]
    return sorted(events, key=lambda x: (x["jd"], x["type"]))


def daily_calendar(day: date, latitude: float, longitude: float, altitude: float, tzname: str,
                   include_events: bool = True) -> dict:
    tz = ZoneInfo(tzname)
    start_local = datetime.combine(day, time(), tzinfo=tz)
    end_local = datetime.combine(day+timedelta(days=1), time(), tzinfo=tz)
    start_jd, end_jd = to_jd(start_local), to_jd(end_local)
    first = lunar_day_state(start_jd, longitude, latitude, altitude)
    phase = phase_snapshot(start_jd)
    events = events_in_interval(start_jd, end_jd, longitude, latitude, altitude) if include_events else []
    timeline = []
    if include_events:
        # Split at every observable change, preserving exact local transition time.
        points = sorted({start_jd, end_jd, *(ev["jd"] for ev in events if ev["type"] in
                                                     {"moonrise", "new_moon", "zodiac_ingress", "first_quarter", "full_moon", "last_quarter"})})
        for a, b in zip(points, points[1:]):
            if b-a < 1e-9:
                continue
            state = lunar_day_state(a+1e-6, longitude, latitude, altitude)
            ps = phase_snapshot(a+1e-6)
            timeline.append({"from": iso(a, tz), "to": iso(b, tz),
                             "lunar_day": state["number"], "zodiac": ps["zodiac"]["id"],
                             "phase_index": ps["phase_index"]})
    out = {
        "date": day.isoformat(),
        "location": {"lat": latitude, "lon": longitude, "altitude_m": altitude, "timezone": tzname},
        "start_local": start_local.isoformat(), "end_local": end_local.isoformat(),
        "moon": phase,
        "lunar_day_at_start": first["number"],
        "lunar_day_observable": first["observable"],
        "lunar_day_starts_at": iso(first["starts_at_jd"], tz),
        "lunar_day_ends_at": iso(first["ends_at_jd"], tz),
        "lunation_starts_at": iso(first["lunation_starts_at_jd"], tz),
        "lunation_ends_at": iso(first["lunation_ends_at_jd"], tz),
        "events": [{"at": iso(e["jd"], tz), **{k:v for k,v in e.items() if k!="jd"}} for e in events],
        "timeline": timeline,
        "method": {"ephemeris": "Swiss Ephemeris / Moshier", "zodiac": "tropical_geocentric",
                   "lunar_day": "conjunction_then_local_moonrises", "precision": "approximate"},
    }
    return out


def instant_calendar(at: datetime, latitude: float, longitude: float, altitude: float, tzname: str) -> dict:
    tz = ZoneInfo(tzname)
    local = at.astimezone(tz)
    jd = to_jd(local)
    state = lunar_day_state(jd, longitude, latitude, altitude)
    return {
        "at": local.isoformat(),
        "location": {"lat": latitude, "lon": longitude, "altitude_m": altitude, "timezone": tzname},
        "moon": phase_snapshot(jd),
        "lunar_day": state["number"], "lunar_day_observable": state["observable"],
        "lunar_day_starts_at": iso(state["starts_at_jd"], tz),
        "lunar_day_ends_at": iso(state["ends_at_jd"], tz),
        "lunation_starts_at": iso(state["lunation_starts_at_jd"], tz),
        "method": {"ephemeris": "Swiss Ephemeris / Moshier", "zodiac": "tropical_geocentric",
                   "lunar_day": "conjunction_then_local_moonrises", "precision": "approximate"},
    }
