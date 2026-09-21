"""End-to-end smoke tests: the Streamlit app must render and the demo must click through."""

from pathlib import Path

import pytest

from blastradius.visualization import render_graph

APP = Path(__file__).resolve().parents[1] / "app.py"


def _app(timeout: int = 180):
    at = pytest.importorskip("streamlit.testing.v1").AppTest.from_file(str(APP), default_timeout=timeout)
    return at.run()


def _text(at) -> str:
    return " ".join(block.value for block in at.markdown)


def test_render_graph_produces_standalone_html(vulnerable_result):
    path = vulnerable_result.critical_paths[0]
    html = render_graph(
        vulnerable_result.graph,
        highlight_nodes=path.nodes,
        highlight_edges=[(e.source, e.target) for e in path.edges],
    )
    assert "<html" in html.lower()
    assert "vis-network" in html
    # Pinned layout: physics must stay off so the demo graph never jitters.
    assert '"enabled": false' in html


def test_off_path_nodes_are_dimmed_only_when_a_path_is_highlighted():
    """In the public-bucket scenario the EC2/IAM nodes sit off the attack path."""
    from blastradius import scenarios
    from blastradius.graph import analyze, build_graph
    from blastradius.parser import parse_directory
    from blastradius.parser.models import NodeType
    from blastradius.visualization.graph_renderer import STYLE, _hex_to_rgba

    result = analyze(
        build_graph(parse_directory(scenarios.get("public_bucket").after)), "after"
    )
    path = result.critical_paths[0]
    assert "aws_instance.reporting" not in path.nodes

    faded_ec2 = _hex_to_rgba(str(STYLE[NodeType.EC2]["color"]), 0.28)
    highlighted = render_graph(result.graph, highlight_nodes=path.nodes)
    plain = render_graph(result.graph)

    assert faded_ec2 in highlighted, "off-path compute must be dimmed"
    assert faded_ec2 not in plain, "nothing is dimmed without a highlighted path"


def test_app_runs_without_exceptions():
    at = _app()
    assert not at.exception
    rendered = _text(at)
    assert "BlastRadius" in rendered
    assert "Attack-path change analysis for Terraform pull requests." in rendered


def test_app_opens_on_a_blocking_decision():
    """Default view is the money shot: safe -> one-line change -> BLOCK."""
    at = _app()
    rendered = _text(at)
    assert "BLOCK CHANGE" in rendered
    assert "SECURITY REGRESSION" in rendered
    assert "DEPLOYMENT DECISION" in rendered
    # All four decision reasons are shown.
    for label in (
        "New critical attack paths",
        "Newly reachable sensitive resources",
        "Newly internet-reachable resources",
        "Security score delta",
    ):
        assert label in rendered


def test_app_shows_the_pr_report_and_hop_reasons():
    at = _app()
    code_blocks = " ".join(block.value for block in at.code)
    assert "BlastRadius Security Check" in code_blocks
    assert "FAILED" in code_blocks

    rendered = _text(at)
    assert "Security group allows 0.0.0.0/0 on port 22 (SSH)" in rendered
    assert "aws_iam_role_policy.app_s3_read" in rendered


def test_demo_click_path_simulate_then_remediate():
    """restore safe -> simulate risky change -> generate fix, all via the real engine."""
    at = _app()

    at.button(key="restore_safe").click().run()
    assert not at.exception
    assert "SAFE TO MERGE" in _text(at)

    at.button(key="simulate_risky").click().run()
    assert not at.exception
    assert "BLOCK CHANGE" in _text(at)
    assert "Internet" in _text(at)

    at.button(key="apply_fix").click().run()
    assert not at.exception
    rendered = _text(at)
    assert "SAFE TO MERGE" in rendered
    assert "eliminated" in rendered.lower()


def test_scenario_buttons_switch_configurations():
    at = _app()
    at.button(key="scenario_public_bucket").click().run()
    assert not at.exception
    rendered = _text(at)
    assert "BLOCK CHANGE" in rendered
    assert "Public sensitive S3 bucket" in rendered
    assert "public-read" in rendered


def test_product_tabs_and_demo_mode_transition():
    at = _app()
    assert [tab.label for tab in at.tabs] == [
        'Overview', 'Attack Path', 'Infrastructure Diff', 'Report & exports', 'Remediation'
    ]
    at.toggle(key='demo_mode').set_value(True).run()
    assert not at.exception
    assert not at.text_input
    assert not at.tabs
    assert 'BLOCK CHANGE' in _text(at)
    at.button(key='restore_safe').click().run()
    at.button(key='simulate_risky').click().run()
    assert not at.exception
    assert 'BLOCK CHANGE' in _text(at)
    at.button(key='demo_apply_fix').click().run()
    assert not at.exception
    assert 'SAFE TO MERGE' in _text(at)
    assert any('re-analysis confirms' in item.value for item in at.success)
    at.toggle(key='demo_mode').set_value(False).run()
    assert not at.exception
    assert 'SAFE TO MERGE' in _text(at)
