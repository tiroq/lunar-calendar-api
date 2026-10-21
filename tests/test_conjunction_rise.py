"""Regression for near-simultaneous conjunction / moonrise in the Python oracle."""
from datetime import datetime, timezone

from lunar_api import astro


def test_subsecond_moonrise_does_not_end_lunation(monkeypatch):
    start = astro.to_jd(datetime(2030, 8, 28, 23, 7, tzinfo=timezone.utc))
    # A rise occurs 0.17 seconds after conjunction; remaining days still rise.
    rises = [start + 0.000002] + [start + index * 1.02 for index in range(1, 29)]

    def find_rise(cursor, longitude, latitude, altitude, rise):
        return next((jd for jd in rises if jd >= cursor), None)

    monkeypatch.setattr(astro, "rise_set_after", find_rise)
    astro.local_lunar_boundaries.cache_clear()
    try:
        result = astro.local_lunar_boundaries(start, start + 29.5, 100.5, 13.76, 0)
        assert len(result) == 29, "Near-conjunction rise must not abort later daily rises"
        assert result[0] == start
        assert result[1] == rises[1], "Sub-second duplicate near conjunction must not create a new day"
    finally:
        astro.local_lunar_boundaries.cache_clear()


def test_bangkok_september_2030_has_normal_observable_lunar_days():
    # Historical production-parity fixture exposed an erroneous null lunar day.
    instant = datetime(2030, 9, 5, 23, 9, tzinfo=timezone.utc)
    state = astro.lunar_day_state(astro.to_jd(instant), 100.5018, 13.7563, 0)
    assert state["observable"] is True
    assert isinstance(state["number"], int) and 1 <= state["number"] <= 30
    assert state["rise_count_in_lunation"] >= 24
