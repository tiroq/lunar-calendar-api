from datetime import date
import json

import pytest
from fastapi.testclient import TestClient

from lunar_api.api import app
from lunar_api.astro import daily_calendar
from lunar_api.content_provider import validate_package

client = TestClient(app)


def test_public_api_defaults_to_anonymous_astronomy(monkeypatch):
    monkeypatch.delenv("LUNAR_CONTENT_BACKEND", raising=False)
    data = client.get("/v1/calendar/day", params={"date": "2026-10-14", "city": "moscow"})
    assert data.status_code == 200, data.text
    row = data.json()
    assert row["lunar_day_at_start"] == 4
    assert row["summary"]["text"].endswith("лунный день")
    assert row["summary"]["starts_at"].startswith("2026")
    assert row["summary"]["ends_at"].startswith("2026")
    assert row["summary"]["enriched"] is False
    assert "category" not in str(row["summary"]).lower()
    assert client.get("/v1/content/lunar-days/5").json()["available"] is False
    assert client.get("/v1/content/status").json()["connected"] is False
    assert client.get("/v1/content/categories").json()["categories"] == {}
    assert client.get("/v1/content/lunar-days/5/categories/business").status_code == 404


def test_private_file_mount_enriches_without_redeploy(tmp_path, monkeypatch):
    path = tmp_path / "private.json"
    payload = {
        "schema_version": 1, "content_version": "local-2026-10",
        "provenance": "private-editorial",
        "categories": {"business": {"name": "Бизнес"}},
        "days": {"5": {"symbols": ["единорог"],
                        "descriptions": {"editorial": "Текст из закрытого пакета"},
                        "alternatives": {"short": "Краткая версия"},
                        "categories": {"business": {"score": 4, "text": "Описание бизнеса"}}}}
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("LUNAR_CONTENT_BACKEND", "file")
    monkeypatch.setenv("LUNAR_CONTENT_FILE", str(path))
    response = client.get("/v1/content/lunar-days/5")
    assert response.status_code == 200, response.text
    assert response.json()["available"] is True
    assert response.json()["description"] == "Текст из закрытого пакета"
    cat = client.get("/v1/content/lunar-days/5/categories/business").json()
    assert cat["score"] == 4 and cat["text"] == "Описание бизнеса"
    day = client.get("/v1/calendar/day?date=2026-10-14&city=moscow").json()
    assert day["content_by_lunar_day"]["5"]["available"] is True
    assert client.get("/v1/content/status").json()["days"] == 1
    assert client.get("/v1/calendar/today?city=bangkok").status_code == 200


def test_invalid_private_package_rejected(tmp_path, monkeypatch):
    file = tmp_path / "private.json"
    file.write_text('{"schema_version":1,"days":{"6":{"categories":{"business":{"score":10}}}}}}')
    monkeypatch.setenv("LUNAR_CONTENT_BACKEND", "file")
    monkeypatch.setenv("LUNAR_CONTENT_FILE", str(file))
    assert client.get("/v1/content/lunar-days/6").status_code == 503


def test_location_and_offsets(monkeypatch):
    monkeypatch.setenv("LUNAR_CONTENT_BACKEND", "none")
    m = client.get("/v1/calendar/day?date=2026-10-14&city=moscow").json()
    b = client.get("/v1/calendar/day?date=2026-10-14&city=bangkok").json()
    assert m["start_local"].endswith("+03:00")
    assert b["start_local"].endswith("+07:00")
    assert next(x["at"] for x in m["events"] if x["type"] == "moonrise") != next(
        x["at"] for x in b["events"] if x["type"] == "moonrise"
    )
    assert client.get("/v1/calendar/day?date=2026-10-14").status_code == 422


def test_schema_fails_closed():
    with pytest.raises(ValueError):
        validate_package({"schema_version": 1, "days": {"5": {"categories": {"x": {"score": 20}}}}})
