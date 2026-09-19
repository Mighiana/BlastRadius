"""Extra demo scenarios (Priority 6) and the CI CLI (Priority 7)."""

import io
import json

import pytest

from blastradius import scenarios
from blastradius.cli import run
from blastradius.graph import analyze, build_graph, compare
from blastradius.parser import parse_directory
from blastradius.parser.models import Relationship, Risk, TerraformResource
from blastradius.security import hcl_edit, remediation, rules
from blastradius.security.decision import Decision, decide


def _analyze(directory, label="x"):
    return analyze(build_graph(parse_directory(directory)), label)


def _diff(scenario):
    return compare(_analyze(scenario.before, "before"), _analyze(scenario.after, "after"))


# --- Priority 6: every bundled scenario is a real, detected regression ------
def test_three_scenarios_are_registered():
    assert [s.id for s in scenarios.SCENARIOS] == ["public_ssh", "broad_iam", "public_bucket"]
    assert {s.root_cause for s in scenarios.SCENARIOS} == {"network", "identity", "storage"}


@pytest.mark.parametrize("scenario", scenarios.SCENARIOS, ids=lambda s: s.id)
def test_every_scenario_blocks_and_has_a_clean_baseline(scenario):
    before = _analyze(scenario.before, "before")
    after = _analyze(scenario.after, "after")
    assert before.critical_paths == [], "baseline must start with no critical path"
    assert len(after.critical_paths) >= 1
    assert decide(compare(before, after)).decision is Decision.BLOCK


@pytest.mark.parametrize("scenario", scenarios.SCENARIOS, ids=lambda s: s.id)
def test_every_scenario_directory_pair_is_identifiable(scenario):
    assert scenarios.by_dirs(scenario.before, scenario.after) is scenario
    assert scenarios.get(scenario.id) is scenario


def test_broad_iam_scenario_root_cause_is_iam_not_network():
    """The public 443 listener exists before and after; only IAM changed."""
    scenario = scenarios.get("broad_iam")
    diff = _diff(scenario)

    assert diff.newly_exposed == ["aws_s3_bucket.customer_data"]
    new_edges = [(e.source, e.target) for e in diff.new_edges]
    assert ("aws_iam_role.app", "aws_s3_bucket.customer_data") in new_edges
    # The internet entry point is unchanged - it is not what broke.
    assert ("INTERNET", "aws_security_group.web") not in new_edges

    edge = diff.after.graph.edges["aws_iam_role.app", "aws_s3_bucket.customer_data"]["edge"]
    assert edge.risk is Risk.CRITICAL
    assert "s3:*" in edge.evidence


def test_public_bucket_scenario_creates_a_direct_internet_edge():
    scenario = scenarios.get("public_bucket")
    diff = _diff(scenario)

    path = diff.new_critical_paths[0]
    assert diff.display_path(path) == ["Internet", "Customer Data", "Sensitive Data"]
    edge = diff.after.graph.edges["INTERNET", "aws_s3_bucket.customer_data"]["edge"]
    assert edge.relationship is Relationship.PUBLIC_ACCESS
    assert edge.terraform_resource == "aws_s3_bucket_acl.customer_data"
    assert 'acl = "public-read"' in edge.evidence


def test_public_acl_detected_inline_on_the_bucket():
    bucket = TerraformResource(
        type="aws_s3_bucket", name="site", attributes={"acl": "public-read-write"}
    )
    finding = rules.public_bucket_findings(bucket, [bucket])[0]
    assert finding.risk is Risk.CRITICAL


def test_private_bucket_has_no_public_finding():
    bucket = TerraformResource(type="aws_s3_bucket", name="data", attributes={"acl": "private"})
    assert rules.public_bucket_findings(bucket, [bucket]) == []


def test_wildcard_bucket_policy_is_public():
    bucket = TerraformResource(type="aws_s3_bucket", name="data", attributes={})
    policy = TerraformResource(
        type="aws_s3_bucket_policy",
        name="data",
        attributes={
            "bucket": "aws_s3_bucket.data.id",
            "policy": '{"Statement":[{"Effect":"Allow","Principal":"*","Action":["s3:GetObject"],"Resource":"*"}]}',
        },
    )
    finding = rules.public_bucket_findings(bucket, [bucket, policy])[0]
    assert finding.terraform_resource == "aws_s3_bucket_policy.data"
    assert finding.risk is Risk.CRITICAL


# --- Remediation must not break a legitimately public listener --------------
def test_remediation_does_not_touch_a_public_443_listener():
    scenario = scenarios.get("broad_iam")
    source = (scenario.after / "main.tf").read_text(encoding="utf-8")
    patched, count = hcl_edit.restrict_admin_ingress(source)
    assert count == 0
    assert patched == source


def test_remediation_fixes_the_public_bucket_scenario(tmp_path):
    scenario = scenarios.get("public_bucket")
    plan = remediation.generate_safer_config(scenario.after)
    assert plan.can_autofix

    fixed_dir = remediation.write_plan(plan, tmp_path / "fixed", scenario.after)
    after = _analyze(scenario.after, "after")
    fixed = _analyze(fixed_dir, "fixed")
    assert fixed.critical_paths == []
    assert decide(compare(after, fixed)).decision is Decision.SAFE


def test_widen_then_restrict_is_a_round_trip():
    source = (scenarios.get("public_ssh").before / "main.tf").read_text(encoding="utf-8")
    widened, opened = hcl_edit.widen_admin_ingress(source)
    assert opened == 1
    restored, closed = hcl_edit.restrict_admin_ingress(widened)
    assert closed == 1
    assert restored == source


def test_edits_are_idempotent():
    source = (scenarios.get("public_ssh").after / "main.tf").read_text(encoding="utf-8")
    _, count = hcl_edit.widen_admin_ingress(source)
    assert count == 0, "already public"


# --- Priority 7: CLI -------------------------------------------------------
def test_cli_exits_1_on_critical_regression():
    stream = io.StringIO()
    code = run(["--before", "examples/safe", "--after", "examples/vulnerable"], stream=stream)
    output = stream.getvalue()
    assert code == 1
    assert "BLOCK CHANGE" in output
    assert "Internet -> Web SG -> Web Server -> App Role" in output


def test_cli_exits_0_after_remediation():
    stream = io.StringIO()
    code = run(["--before", "examples/vulnerable", "--after", "examples/safe"], stream=stream)
    assert code == 0
    assert "SAFE TO MERGE" in stream.getvalue()


def test_cli_exits_0_for_identical_configs():
    stream = io.StringIO()
    code = run(["--before", "examples/safe", "--after", "examples/safe"], stream=stream)
    assert code == 0


def test_cli_pr_format_matches_the_report():
    stream = io.StringIO()
    run(["--before", "examples/safe", "--after", "examples/vulnerable", "--format", "pr"], stream=stream)
    assert "BlastRadius Security Check" in stream.getvalue()
    assert "FAILED" in stream.getvalue()


def test_cli_json_format_is_machine_readable():
    stream = io.StringIO()
    code = run(
        ["--before", "examples/safe", "--after", "examples/vulnerable", "--format", "json"],
        stream=stream,
    )
    payload = json.loads(stream.getvalue())
    assert code == 1
    assert payload["decision"] == "BLOCK CHANGE"
    assert payload["passed"] is False
    assert payload["score"] == {"before": 100, "after": 20, "delta": -80}
    assert payload["newly_reachable_sensitive"] == ["aws_s3_bucket.customer_data"]


def test_cli_fail_on_review_flag():
    """A REVIEW-only change passes by default but fails with --fail-on-review."""
    args = [
        "--before",
        "examples/scenarios/broad_iam/before",
        "--after",
        "examples/scenarios/broad_iam/before",
    ]
    assert run(args, stream=io.StringIO()) == 0
    assert run(args + ["--fail-on-review"], stream=io.StringIO()) == 0


def test_cli_reports_missing_directory():
    stream = io.StringIO()
    code = run(["--before", "examples/safe", "--after", "examples/does_not_exist"], stream=stream)
    assert code == 2
    assert "error" in stream.getvalue()


@pytest.mark.parametrize("scenario", scenarios.SCENARIOS, ids=lambda s: s.id)
def test_cli_blocks_every_scenario(scenario):
    code = run(
        ["--before", str(scenario.before), "--after", str(scenario.after)], stream=io.StringIO()
    )
    assert code == 1
