"""Before/after comparison, scoring and remediation - the demo narrative."""

from blastradius.graph import analyze, build_graph, compare
from blastradius.graph.diff_engine import Verdict, highlight_edges, highlight_nodes
from blastradius.parser import parse_directory
from blastradius.parser.models import Risk
from blastradius.security import remediation
from blastradius.security.risk_score import score_band

from tests.conftest import SAFE_DIR, VULNERABLE_DIR


def test_safe_to_vulnerable_is_a_regression(safe_result, vulnerable_result):
    diff = compare(safe_result, vulnerable_result)
    assert diff.verdict is Verdict.REGRESSION
    assert diff.is_regression
    assert diff.score_delta < 0


def test_diff_identifies_the_new_attack_path(safe_result, vulnerable_result):
    diff = compare(safe_result, vulnerable_result)
    assert len(diff.new_critical_paths) == 1
    assert diff.new_critical_paths[0].nodes[0] == "INTERNET"
    assert diff.new_critical_paths[0].nodes[-1] == "sensitive_data.customer_data"


def test_diff_identifies_the_single_new_edge(safe_result, vulnerable_result):
    diff = compare(safe_result, vulnerable_result)
    assert [(e.source, e.target) for e in diff.new_edges] == [
        ("INTERNET", "aws_security_group.web")
    ]
    assert diff.removed_edges == []


def test_diff_reports_newly_reachable_sensitive_data(safe_result, vulnerable_result):
    diff = compare(safe_result, vulnerable_result)
    assert diff.newly_reachable_sensitive == ["aws_s3_bucket.customer_data"]
    assert diff.newly_exposed == [
        "aws_iam_role.app",
        "aws_instance.web_server",
        "aws_s3_bucket.customer_data",
    ]


def test_no_nodes_added_or_removed_by_the_change(safe_result, vulnerable_result):
    """The change is purely a reachability change, not a structural one."""
    diff = compare(safe_result, vulnerable_result)
    assert diff.new_nodes == []
    assert diff.removed_nodes == []


def test_metric_rows_show_the_regression(safe_result, vulnerable_result):
    rows = {r["metric"]: r for r in compare(safe_result, vulnerable_result).metric_rows()}
    assert rows["Critical attack paths"]["before"] == 0
    assert rows["Critical attack paths"]["after"] == 1
    assert rows["Sensitive resources reachable"]["before"] == 0
    assert rows["Sensitive resources reachable"]["after"] == 1
    assert rows["Risk level"]["before"] == "LOW"
    assert rows["Risk level"]["after"] == "CRITICAL"
    assert all(row["changed"] for row in rows.values())


def test_identical_configs_report_no_change(safe_result):
    other = analyze(build_graph(parse_directory(SAFE_DIR)), "safe-copy")
    diff = compare(safe_result, other)
    assert diff.verdict is Verdict.UNCHANGED
    assert diff.new_attack_paths == [] and diff.removed_attack_paths == []


def test_highlight_helpers_cover_the_new_path(safe_result, vulnerable_result):
    diff = compare(safe_result, vulnerable_result)
    assert len(highlight_nodes(diff)) == 6
    assert len(highlight_edges(diff)) == 5


def test_scores_are_bounded_and_ordered(safe_result, vulnerable_result):
    assert safe_result.score == 100
    assert 0 <= vulnerable_result.score < safe_result.score
    assert score_band(safe_result.score) is Risk.LOW
    assert score_band(vulnerable_result.score) is Risk.CRITICAL


def test_score_breakdown_matches_score(vulnerable_result):
    deducted = sum(item["points"] for item in vulnerable_result.score_breakdown)
    assert vulnerable_result.score == 100 + deducted


# --- Remediation loop ------------------------------------------------------
def test_recommendation_generated_for_public_ssh(vulnerable_config):
    recs = remediation.recommend(vulnerable_config)
    assert any("0.0.0.0/0" in r.current for r in recs)
    assert recs[0].severity is Risk.CRITICAL


def test_patch_rewrites_ingress_but_not_egress():
    source = VULNERABLE_DIR.joinpath("main.tf").read_text(encoding="utf-8")
    patched, count = remediation.patch_public_admin_cidrs(source)
    assert count == 1
    assert '"0.0.0.0/0"' in patched, "egress rule must be preserved"
    assert patched.count('"0.0.0.0/0"') == 1


def test_generated_fix_eliminates_the_attack_path(tmp_path, vulnerable_result):
    plan = remediation.generate_safer_config(VULNERABLE_DIR)
    assert plan.can_autofix
    fixed_dir = remediation.write_plan(plan, tmp_path / "fixed", VULNERABLE_DIR)

    fixed = analyze(build_graph(parse_directory(fixed_dir)), "fixed")
    assert fixed.critical_paths == []
    assert fixed.reachable_sensitive == []
    assert fixed.risk_level is Risk.LOW
    assert fixed.score == 100

    diff = compare(vulnerable_result, fixed)
    assert diff.verdict is Verdict.IMPROVED
    assert len(diff.removed_critical_paths) == 1
    assert diff.score_delta > 0


def test_generated_fix_matches_the_safe_baseline(tmp_path, safe_result):
    plan = remediation.generate_safer_config(VULNERABLE_DIR)
    fixed_dir = remediation.write_plan(plan, tmp_path / "fixed", VULNERABLE_DIR)
    fixed = analyze(build_graph(parse_directory(fixed_dir)), "fixed")
    assert fixed.path_keys == safe_result.path_keys
    assert fixed.score == safe_result.score


def test_safe_config_needs_no_autofix():
    plan = remediation.generate_safer_config(SAFE_DIR)
    assert not plan.can_autofix
    assert plan.recommendations == []
