import io
import json
from urllib.parse import urlsplit

import pytest

from scripts.verify_prod_api import ProbeError, check_origin, verify


def fake_opener(status_overrides=None):
    payloads = {
        "/healthz": {"status": "ok"},
        "/v1/locations": [{"id": "bangkok", "tz": "Asia/Bangkok"}],
        "/v1/content/status": {
            "connected": True, "backend": "postgres", "days": 30,
            "category_records": 720, "historical_prose_records_published": 0,
            "content_version": "private-v1",
        },
        "/v1/content/categories": {"categories": {f"category-{i}": {} for i in range(24)}},
        "/v1/calendar/today?city=bangkok": {"timeline": []},
    }
    payloads.update(status_overrides or {})

    def opener(request, timeout):
        assert timeout <= 90
        path = urlsplit(request.full_url).path + (
            "?" + urlsplit(request.full_url).query if urlsplit(request.full_url).query else "")
        response = io.BytesIO(json.dumps(payloads[path]).encode())
        response.status = 200
        return response
    return opener


def test_bootstrap_requires_only_service_and_locations():
    verify("https://lunar-api.example.org", ready=False, opener=fake_opener())


def test_ready_requires_complete_private_content_and_exact_version():
    verify("https://lunar-api.example.org", expected_version="private-v1",
           opener=fake_opener())


@pytest.mark.parametrize("status", [
    {"connected": False},
    {"days": 0},
    {"category_records": 719},
    {"historical_prose_records_published": 5},
    {"backend": "file"},
])
def test_fail_closed_on_bad_content_state(status):
    current = {
        "connected": True, "backend": "postgres", "days": 30,
        "category_records": 720, "historical_prose_records_published": 0,
        "content_version": "private-v1",
    }
    current.update(status)
    with pytest.raises(ProbeError, match="content/status"):
        verify("https://lunar-api.example.org",
               opener=fake_opener({"/v1/content/status": current}))


def test_version_mismatch_rejected():
    with pytest.raises(ProbeError, match="content_version"):
        verify("https://lunar-api.example.org", expected_version="other",
               opener=fake_opener())


@pytest.mark.parametrize("origin", [
    "http://lunar.example.org", "https://user:password@lunar.example.org",
    "https://lunar.example.org/v1", "https://lunar.example.org?token=123",
    "https://lunar.example.org/#fragment", "", "not-a-url",
])
def test_origin_must_be_public_https_root(origin):
    with pytest.raises(ProbeError):
        check_origin(origin)
