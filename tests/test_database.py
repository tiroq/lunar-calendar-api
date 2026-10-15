"""Optional integration smoke test against ephemeral PostgreSQL, run by CI."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from lunar_api.api import app

@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="Requires CI PostgreSQL service")
def test_migrate_activate_and_serve(tmp_path, monkeypatch):
    repo = Path(__file__).resolve().parents[1]
    path = tmp_path / "private-test.json"
    data = {
        "schema_version": 1,
        "content_version": "ci-database-snapshot",
        "provenance": "synthetic_ci_fixture",
        "categories": {"business": {"name": "Бизнес"}},
        "days": {"5": {
            "descriptions": {"editorial": "Fixture available only after import"},
            "categories": {"business": {"score": 4, "text": "Fixture score"}}
        }},
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    subprocess.run([sys.executable, str(repo / "scripts/content_db.py"), "migrate"],
                   cwd=repo, check=True)
    subprocess.run([sys.executable, str(repo / "scripts/content_db.py"), "import",
                    "--file", str(path), "--activate"], cwd=repo, check=True)
    monkeypatch.setenv("LUNAR_CONTENT_BACKEND", "postgres")
    client = TestClient(app)
    result = client.get("/v1/content/lunar-days/5")
    assert result.status_code == 200, result.text
    assert result.json()["description"] == "Fixture available only after import"
    assert client.get("/v1/content/status").json()["content_version"] == data["content_version"]
    assert client.get("/v1/content/lunar-days/5/categories/business").json()["score"] == 4
