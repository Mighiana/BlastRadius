from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="install .[server,dev] for integration tests")
pytest.importorskip("sqlalchemy", reason="install .[server,dev] for integration tests")
pytest.importorskip("stripe", reason="install .[server,dev] for integration tests")

from fastapi.testclient import TestClient

from blastradius.server.analysis import analyze_input
from blastradius.server.app import create_app
from blastradius.server.config import Settings
from blastradius.server.db import Database
from blastradius.server.demos import build_demos
from blastradius.server.fixtures import FIXTURES
from blastradius.server.schemas import AnalysisInput

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def integrated_demos(tmp_path_factory):
    return build_demos(Settings(data_dir=tmp_path_factory.mktemp("integrated-demos")))


@pytest.mark.parametrize("scenario", ["public_ssh", "broad_iam", "public_bucket"])
def test_demo_decisions_and_path_deltas(integrated_demos, scenario):
    reports = [integrated_demos[(scenario, stage)] for stage in ("safe", "risky", "remediated")]
    assert [report["decision"] for report in reports] == [
        "SAFE TO MERGE", "BLOCK CHANGE", "SAFE TO MERGE"
    ]
    safe, risky, fixed = reports
    assert all(report["analysis_complete"] for report in reports)
    assert risky["new_critical_paths"] and not risky["removed_attack_paths"]
    assert fixed["removed_critical_paths"] and not fixed["new_attack_paths"]
    assert fixed["score"]["after"] == safe["score"]["after"]


def test_api_report_preserves_engine_coverage_and_export_diagnostics(tmp_path):
    files = {"main.tf": 'resource "aws_db_instance" "database" { publicly_accessible = true }'}
    report = analyze_input(
        AnalysisInput(project_id="test", before_files=files, after_files=files),
        tmp_path, 300,
    )
    assert report["decision"] == "REVIEW REQUIRED"
    assert report["verdict"] == "INCOMPLETE ANALYSIS"
    assert report["analysis_complete"] is False
    assert report["before"]["complete"] is False
    diagnostics = [d for d in report["diagnostics"] if d.get("blocks_analysis")]
    assert {d["phase"] for d in diagnostics} == {"before", "after"}
    assert any(d["code"] == "UNSUPPORTED_RESOURCE" and "aws_db_instance" in d["message"] for d in diagnostics)
    assert all(not d["source_file"].startswith("/") for d in diagnostics)
    sarif = report["reports"]["sarif"]["runs"][0]
    assert sarif["properties"]["analysisComplete"] is False
    assert any(result["ruleId"] == "BR004" for result in sarif["results"])
    assert str(tmp_path) not in json.dumps(report)


def test_api_report_retains_per_edge_evidence(integrated_demos):
    report = integrated_demos[("public_ssh", "risky")]
    edges = report["new_critical_paths"][0]["edges"]
    assert all({"confidence", "category", "source_file", "remediation"} <= edge.keys() for edge in edges)
    assert any(edge["source_file"] == "main.tf" and edge["evidence"] for edge in edges)


@pytest.mark.parametrize("route", ["/", "/demo", "/dashboard", "/history", "/billing", "/pricing", "/guide"])
def test_static_frontend_routes_and_asset_boundaries(tmp_path, route):
    static = tmp_path / "dist"
    static.mkdir()
    (static / "index.html").write_text("<html>application shell</html>")
    (static / "assets").mkdir()
    (static / "assets" / "app.js").write_text("export const application = true;")
    settings = Settings(
        data_dir=tmp_path / "data", database_url="sqlite:///:memory:", static_dir=static
    )
    app = create_app(settings)
    client = TestClient(app)
    assert client.get(route).text == "<html>application shell</html>"
    assert client.get("/assets/app.js").status_code == 200
    for path in ("/api/unknown", "/health/unknown", "/assets/missing.js", "/.env", "/%2e%2e/pyproject.toml"):
        assert client.get(path).status_code == 404
    assert client.post(route).status_code == 405
    app.state.db.engine.dispose()


def test_release_alembic_entrypoint_matches_module_migration(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'db.sqlite'}"
    env = dict(
        os.environ, BR_ENV="test", BR_AUTH_MODE="disabled",
        BR_DATABASE_URL=database_url, BR_DATA_DIR=str(tmp_path),
        BLASTRADIUS_ALEMBIC_CONFIG=str(ROOT / "alembic.ini"),
        PATH=f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}",
    )
    for command in (
        ["sh", str(ROOT / "scripts/container-entrypoint.sh"), "migrate"],
        [sys.executable, "-m", "blastradius.server.migrate"],
    ):
        subprocess.run(command, env=env, cwd=tmp_path, check=True, capture_output=True)
    db = Database(Settings(data_dir=tmp_path, database_url=database_url))
    assert db.ready()
    db.engine.dispose()


def test_real_iam_remediation_preserves_existing_public_compute_path(tmp_path):
    scenario = FIXTURES["broad_iam"]
    report = analyze_input(AnalysisInput(
        project_id="test", before_files=scenario["after_files"], after_files=scenario["before_files"]
    ), tmp_path, 300)
    assert report["after"]["attack_paths"]
    assert not report["after"]["attack_paths"][0]["reaches_sensitive"]
    assert not report["new_attack_paths"]
    assert report["score"]["after"] == 85
