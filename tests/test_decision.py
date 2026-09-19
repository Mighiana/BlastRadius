"""Deployment decision gate (Priority 1) and edge explainability (Priority 4)."""

from blastradius.graph import analyze, build_graph, compare
from blastradius.parser import parse_directory
from blastradius.parser.models import Relationship, Risk
from blastradius.security import remediation
from blastradius.security.decision import Decision, decide

from tests.conftest import SAFE_DIR, VULNERABLE_DIR


# --- Priority 1: the gate --------------------------------------------------
def test_new_critical_path_blocks_the_change(safe_result, vulnerable_result):
    decision = decide(compare(safe_result, vulnerable_result))
    assert decision.decision is Decision.BLOCK
    assert not decision.passed
    assert decision.exit_code == 1
    assert "sensitive" in decision.headline.lower()


def test_block_decision_lists_all_four_reasons(safe_result, vulnerable_result):
    decision = decide(compare(safe_result, vulnerable_result))
    labels = [r.label for r in decision.reasons]
    assert labels == [
        "New critical attack paths",
        "Newly reachable sensitive resources",
        "Newly internet-reachable resources",
        "Security score delta",
    ]
    by_label = {r.label: r for r in decision.reasons}
    assert by_label["New critical attack paths"].delta == 1
    assert by_label["Newly reachable sensitive resources"].delta == 1
    assert by_label["Newly internet-reachable resources"].delta == 3
    assert by_label["Security score delta"].delta == 80


def test_blocking_reasons_are_the_critical_ones(safe_result, vulnerable_result):
    decision = decide(compare(safe_result, vulnerable_result))
    assert [r.label for r in decision.blocking_reasons] == [
        "New critical attack paths",
        "Newly reachable sensitive resources",
    ]


def test_identical_configs_are_safe_to_merge(safe_result):
    other = analyze(build_graph(parse_directory(SAFE_DIR)), "safe-copy")
    decision = decide(compare(safe_result, other))
    assert decision.decision is Decision.SAFE
    assert decision.passed and decision.exit_code == 0
    assert all(r.delta == 0 for r in decision.reasons)


def test_remediation_flips_decision_to_safe_to_merge(tmp_path, vulnerable_result):
    plan = remediation.generate_safer_config(VULNERABLE_DIR)
    fixed_dir = remediation.write_plan(plan, tmp_path / "fixed", VULNERABLE_DIR)
    fixed = analyze(build_graph(parse_directory(fixed_dir)), "fixed")

    decision = decide(compare(vulnerable_result, fixed))
    assert decision.decision is Decision.SAFE
    assert decision.exit_code == 0
    assert "removed" in decision.headline.lower()


def test_exposure_without_sensitive_data_requires_review(tmp_path):
    """Public port + no sensitive reachable => REVIEW, not BLOCK."""
    source = (SAFE_DIR / "main.tf").read_text(encoding="utf-8")
    before = source.replace('Sensitive = "true"', 'Sensitive = "false"').replace(
        'DataClass = "pii"', 'DataClass = "public"'
    )
    after = before.replace('cidr_blocks = ["10.0.0.0/24"]', 'cidr_blocks = ["0.0.0.0/0"]', 1)

    (tmp_path / "before").mkdir()
    (tmp_path / "after").mkdir()
    (tmp_path / "before" / "main.tf").write_text(before, encoding="utf-8")
    (tmp_path / "after" / "main.tf").write_text(after, encoding="utf-8")

    before_result = analyze(build_graph(parse_directory(tmp_path / "before")), "b")
    after_result = analyze(build_graph(parse_directory(tmp_path / "after")), "a")
    assert after_result.critical_paths == []

    decision = decide(compare(before_result, after_result))
    assert decision.decision is Decision.REVIEW
    assert decision.passed, "review must not fail CI"
    assert decision.exit_code == 0


def test_decision_is_deterministic(safe_result, vulnerable_result):
    diff = compare(safe_result, vulnerable_result)
    first, second = decide(diff), decide(diff)
    assert first.decision is second.decision
    assert [r.detail for r in first.reasons] == [r.detail for r in second.reasons]


def test_decision_icons_and_colors_are_distinct():
    icons = {d.icon for d in Decision}
    colors = {d.color for d in Decision}
    assert len(icons) == 3 and len(colors) == 3


# --- Priority 4: explainable edges ----------------------------------------
def test_every_edge_records_its_terraform_resource(vulnerable_result):
    for _, _, data in vulnerable_result.graph.edges(data=True):
        edge = data["edge"]
        assert edge.terraform_resource, f"{edge.source}->{edge.target} has no owning resource"
        assert edge.evidence, f"{edge.source}->{edge.target} has no evidence"


def test_ingress_edge_evidence_shows_the_open_cidr(vulnerable_result):
    edge = vulnerable_result.graph.edges["INTERNET", "aws_security_group.web"]["edge"]
    assert edge.terraform_resource == "aws_security_group.web"
    assert '"0.0.0.0/0"' in edge.evidence
    assert "from_port = 22" in edge.evidence


def test_instance_profile_edge_evidence(vulnerable_result):
    edge = vulnerable_result.graph.edges["aws_instance.web_server", "aws_iam_role.app"]["edge"]
    assert edge.relationship is Relationship.ASSUMES_ROLE
    assert edge.terraform_resource == "aws_instance.web_server"
    assert "iam_instance_profile" in edge.evidence


def test_iam_to_s3_edge_points_at_the_policy_resource(vulnerable_result):
    edge = vulnerable_result.graph.edges["aws_iam_role.app", "aws_s3_bucket.customer_data"]["edge"]
    assert edge.terraform_resource == "aws_iam_role_policy.app_s3_read"
    assert "s3:GetObject" in edge.evidence


def test_sensitive_edge_evidence_shows_the_tag(vulnerable_result):
    edge = vulnerable_result.graph.edges[
        "aws_s3_bucket.customer_data", "sensitive_data.customer_data"
    ]["edge"]
    assert edge.terraform_resource == "aws_s3_bucket.customer_data"
    assert 'Sensitive = "true"' in edge.evidence


def test_security_group_to_ec2_evidence(vulnerable_result):
    edge = vulnerable_result.graph.edges[
        "aws_security_group.web", "aws_instance.web_server"
    ]["edge"]
    assert edge.evidence == "vpc_security_group_ids = [aws_security_group.web.id]"
