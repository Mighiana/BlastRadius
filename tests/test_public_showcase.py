"""Public showcase content and hosted Streamlit validation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

import app
from blastradius.server.plans import PLANS
from blastradius.showcase import (
    BETA_LOOKING_FOR,
    DOC_LINKS,
    HERO_SUBTITLE,
    HERO_TITLE,
    LIMITATIONS,
    PRICING,
    PRICING_DISCLAIMER,
    beta_contact,
)

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("BLASTRADIUS_DEMO_STORAGE_ROOT", str(tmp_path / "sessions"))
    monkeypatch.delenv("BLASTRADIUS_TRUSTED_LOCAL", raising=False)


def _app():
    return pytest.importorskip("streamlit.testing.v1").AppTest.from_file(
        str(APP), default_timeout=240
    ).run()


def _text(at) -> str:
    return " ".join(block.value for block in at.markdown)


def test_hero_is_public_and_contains_no_legacy_text():
    at = _app()
    text = _text(at)
    assert HERO_TITLE in text
    assert HERO_SUBTITLE in text
    assert "You're using the public BlastRadius demo." in text
    assert "legacy" not in text.lower()


def test_pricing_matches_platform_plan_catalog():
    for tier in PRICING:
        plan = PLANS[tier.code]
        if plan.monthly_price_usd is None:
            assert tier.price_label == "Custom"
        else:
            assert str(plan.monthly_price_usd) in tier.price_label
        numbers = [int(value.replace(",", "")) for value in re.findall(r"\d[\d,]*", " ".join(tier.features))]
        if tier.code != "enterprise":
            assert plan.projects in numbers
            assert plan.analyses_per_month in numbers
            assert plan.retention_days in numbers
    at = _app()
    at.radio(key="page").set_value("Pricing").run()
    text = _text(at)
    assert PRICING_DISCLAIMER in text
    assert "checkout" not in text.lower()


def test_beta_contact_validation_and_precedence():
    assert not beta_contact({}, None).configured
    assert beta_contact({"BLASTRADIUS_BETA_FORM_URL": "https://example.com/form"}, None).form_url
    assert beta_contact({"BLASTRADIUS_BETA_FORM_URL": "http://example.com"}, None).form_url is None
    assert beta_contact({"BLASTRADIUS_BETA_FORM_URL": "javascript:alert(1)"}, None).form_url is None
    assert beta_contact({"BLASTRADIUS_BETA_CONTACT": "hello@example.com"}, None).email
    assert beta_contact({"BLASTRADIUS_BETA_CONTACT": "a@b"}, None).email is None
    result = beta_contact(
        {"BLASTRADIUS_BETA_CONTACT": "env@example.com"},
        {"BLASTRADIUS_BETA_CONTACT": "secret@example.com"},
    )
    assert result.email == "env@example.com"


def test_exports_match_displayed_result():
    at = _app()
    assert at.download_button(key="download_json")
    assert at.download_button(key="download_sarif")
    from blastradius.graph import analyze, build_graph, compare
    from blastradius.parser import parse_directory
    from blastradius.security.decision import decide

    before = analyze(build_graph(parse_directory(ROOT / "examples" / "safe")), "before")
    after = analyze(build_graph(parse_directory(ROOT / "examples" / "vulnerable")), "after")
    diff = compare(before, after)
    json_data = app.export_payload(diff, decide(diff), ROOT / "examples" / "safe", ROOT / "examples" / "vulnerable")
    assert json_data["decision"] == "BLOCK CHANGE"
    assert json_data["score"] == {"before": 100, "after": 20, "delta": -80}
    assert json_data["new_critical_paths"]
    assert json_data["limitations"] == list(LIMITATIONS)
    assert json_data["responsible_change"]
    sarif_data = json.loads(json.dumps(app.build_sarif(diff, decide(diff))))
    assert sarif_data["runs"][0]["results"]
    assert "Model limitations" in app.report_markdown("displayed report")


def test_navigation_to_beta_and_safe_demo():
    at = _app()
    at.button(key="cta_beta").click().run()
    assert at.radio(key="page").value == "Beta access"
    text = _text(at)
    assert all(item in text for item in BETA_LOOKING_FOR)
    at.radio(key="page").set_value("Pricing").run()
    at.button(key="pricing_free").click().run()
    assert at.radio(key="page").value == "Demo"
    assert "SAFE TO MERGE" in _text(at)


def test_path_chip_has_mobile_markup_and_css():
    markup = app.path_chip(["Internet", "Web SG"])
    assert 'class="a-v"' in markup
    assert "&darr;" in markup
    assert "@media (max-width: 640px)" in app.CSS
    assert ".br-path" in app.CSS


def test_hosting_independence_and_doc_links():
    source = APP.read_text(encoding="utf-8") + (ROOT / "blastradius" / "showcase.py").read_text(
        encoding="utf-8"
    )
    for forbidden in ("blastradius.server", "fastapi", "sqlalchemy", "psycopg"):
        assert forbidden not in source
    for _, path in DOC_LINKS:
        if path:
            assert (ROOT / path).exists()


def test_config_hides_streamlit_error_details():
    config = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    assert 'showErrorDetails = "none"' in config


def test_incomplete_input_fails_closed(monkeypatch):
    monkeypatch.delenv("BLASTRADIUS_TRUSTED_LOCAL", raising=False)
    with patch("blastradius.parser.parse_directory", side_effect=ValueError("private path")):
        at = _app()
    text = _text(at)
    assert "ANALYSIS INCOMPLETE" in text
    assert "MANUAL REVIEW REQUIRED" in text
    assert "SAFE TO MERGE" not in text
    assert "private path" not in text
    assert str(ROOT) not in text
