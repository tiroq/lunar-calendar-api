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


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="Requires CI PostgreSQL service")
def test_private_snapshot_immutability_and_rollback(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    cli = str(repo / "scripts/content_db.py")
    def run(*args, check=True):
        return subprocess.run([sys.executable, cli, *args], cwd=repo,
                              capture_output=True, text=True, check=check)
    def make_package(name, body):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps({
            "schema_version": 1, "content_version": name,
            "days": {"5": {"descriptions": {"editorial": body}}},
        }))
        return path

    run("migrate")
    first = make_package("ci-first-snapshot", "version one")
    second = make_package("ci-second-snapshot", "version two")
    run("import", "--file", str(first), "--activate")
    run("import", "--file", str(second))  # Stage only; must not deactivate the first.
    rows = json.loads(run("status").stdout)
    assert [x["version"] for x in rows if x["activated_at"]] == ["ci-first-snapshot"]

    run("import", "--file", str(second), "--activate")
    rows = json.loads(run("status").stdout)
    assert [x["version"] for x in rows if x["activated_at"]] == ["ci-second-snapshot"]

    run("activate", "--version", "ci-first-snapshot")
    rows = json.loads(run("status").stdout)
    assert [x["version"] for x in rows if x["activated_at"]] == ["ci-first-snapshot"]

    first.write_text(json.dumps({
        "schema_version": 1, "content_version": "ci-first-snapshot",
        "days": {"5": {"descriptions": {"editorial": "tampered with same version"}}},
    }))
    rejection = run("import", "--file", str(first), "--activate", check=False)
    assert rejection.returncode == 2
    assert "Immutable snapshot conflict" in rejection.stderr
    rows = json.loads(run("status").stdout)
    assert [x["version"] for x in rows if x["activated_at"]] == ["ci-first-snapshot"]

    invalid = run("activate", "--version", "ci-version-not-found", check=False)
    assert invalid.returncode == 2
    rows = json.loads(run("status").stdout)
    assert [x["version"] for x in rows if x["activated_at"]] == ["ci-first-snapshot"]
