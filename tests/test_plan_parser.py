"""Terraform plan JSON support (Phase 3)."""

import copy
import io
import json

import pytest

from blastradius.cli import run
from blastradius.graph import analyze, build_graph, compare
from blastradius.parser import parse_directory
from blastradius.parser.plan_parser import (
    PlanParseError,
    load_plan,
    parse_plan,
    parse_plan_file,
    parse_plan_pair,
)
from blastradius.security.decision import Decision, decide

from tests.conftest import EXAMPLES, SAFE_DIR, VULNERABLE_DIR

PLAN = EXAMPLES / "plans" / "ssh_open_plan.json"


def _analyze(config, label="x"):
    return analyze(build_graph(config), label)


# --- Parsing ---------------------------------------------------------------
def test_plan_parses_the_supported_resources():
    config = parse_plan_file(PLAN, "after")
    assert {r.address for r in config.resources} == {
        "aws_security_group.web",
        "aws_instance.web_server",
        "aws_iam_role.app",
        "aws_iam_instance_profile.app",
        "aws_iam_role_policy.app_s3_read",
        "aws_s3_bucket.customer_data",
    }


def test_unsupported_resources_are_reported_not_dropped_silently():
    config = parse_plan_file(PLAN, "after")
    assert config.unsupported == ["aws_cloudwatch_log_group"]
    assert not any(r.type == "aws_cloudwatch_log_group" for r in config.resources)


def test_resolved_values_are_relinked_to_terraform_addresses():
    config = parse_plan_file(PLAN, "after")
    instance = config.by_address("aws_instance.web_server")
    assert instance.get("vpc_security_group_ids") == ["aws_security_group.web.id"]
    assert instance.get("iam_instance_profile") == "aws_iam_instance_profile.app.name"

    profile = config.by_address("aws_iam_instance_profile.app")
    assert profile.get("role") == "aws_iam_role.app.name"

    policy = config.by_address("aws_iam_role_policy.app_s3_read")
    assert "${aws_s3_bucket.customer_data.arn}" in policy.get("policy")
    assert "arn:aws:s3:::acme-customer-data" not in policy.get("policy")


def test_prior_state_and_planned_values_differ_on_the_cidr():
    before, after = parse_plan_pair(PLAN)
    before_sg = before.by_address("aws_security_group.web")
    after_sg = after.by_address("aws_security_group.web")
    assert before_sg.get("ingress")[0]["cidr_blocks"] == ["10.0.0.0/24"]
    assert after_sg.get("ingress")[0]["cidr_blocks"] == ["0.0.0.0/0"]


# --- HCL / plan normalization compatibility --------------------------------
def test_plan_mode_matches_source_mode_exactly():
    """The same change analysed from source and from plan JSON must agree."""
    plan_before, plan_after = parse_plan_pair(PLAN)
    plan_diff = compare(_analyze(plan_before, "before"), _analyze(plan_after, "after"))
    src_diff = compare(
        _analyze(parse_directory(SAFE_DIR), "before"),
        _analyze(parse_directory(VULNERABLE_DIR), "after"),
    )

    assert decide(plan_diff).decision is decide(src_diff).decision is Decision.BLOCK
    assert plan_diff.before.score == src_diff.before.score == 100
    assert plan_diff.after.score == src_diff.after.score == 20
    assert [p.key for p in plan_diff.new_critical_paths] == [
        p.key for p in src_diff.new_critical_paths
    ]
    assert plan_diff.newly_reachable_sensitive == src_diff.newly_reachable_sensitive


def test_plan_graph_has_the_same_edges_as_source_graph():
    plan_after = _analyze(parse_plan_pair(PLAN)[1], "plan")
    source_after = _analyze(parse_directory(VULNERABLE_DIR), "source")
    assert sorted(plan_after.graph.edges) == sorted(source_after.graph.edges)


# --- Fallbacks -------------------------------------------------------------
def test_value_matching_works_without_a_configuration_block():
    """Some producers omit `configuration`; ids/ARNs must still resolve."""
    data = load_plan(PLAN)
    data.pop("configuration")
    config = parse_plan(data, "after")

    instance = config.by_address("aws_instance.web_server")
    assert instance.get("vpc_security_group_ids") == ["aws_security_group.web.id"]
    assert instance.get("iam_instance_profile") == "aws_iam_instance_profile.app.name"
    assert len(_analyze(config).critical_paths) == 1


def test_resource_changes_fallback_when_planned_values_missing():
    data = load_plan(PLAN)
    data.pop("planned_values")
    config = parse_plan(data, "after")
    assert config.by_address("aws_security_group.web") is not None


def test_child_modules_are_walked():
    data = load_plan(PLAN)
    root = data["planned_values"]["root_module"]
    moved = [r for r in root["resources"] if r["type"] == "aws_s3_bucket"]
    root["resources"] = [r for r in root["resources"] if r["type"] != "aws_s3_bucket"]
    root["child_modules"] = [{"address": "module.data", "resources": moved}]

    config = parse_plan(data, "after")
    assert config.by_address("aws_s3_bucket.customer_data") is not None


def test_data_sources_are_ignored():
    data = load_plan(PLAN)
    data["planned_values"]["root_module"]["resources"].append(
        {
            "address": "data.aws_ami.latest",
            "mode": "data",
            "type": "aws_ami",
            "name": "latest",
            "values": {"id": "ami-123"},
        }
    )
    config = parse_plan(data, "after")
    assert all(not r.address.startswith("data.") for r in config.resources)
    assert "aws_ami" not in config.unsupported


# --- Errors ----------------------------------------------------------------
def test_missing_plan_file(tmp_path):
    with pytest.raises(PlanParseError, match="not found"):
        parse_plan_file(tmp_path / "nope.json")


def test_invalid_json(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(PlanParseError, match="not valid JSON"):
        parse_plan_file(bad)


def test_json_that_is_not_a_plan(tmp_path):
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
    with pytest.raises(PlanParseError, match="terraform show"):
        parse_plan_file(other)


def test_invalid_phase():
    with pytest.raises(ValueError):
        parse_plan(load_plan(PLAN), phase="sideways")


def test_empty_plan_produces_empty_config(tmp_path):
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"planned_values": {"root_module": {}}}), encoding="utf-8")
    config = parse_plan_file(empty)
    assert config.resources == []
    assert list(build_graph(config).nodes) == ["INTERNET"]


# --- CLI -------------------------------------------------------------------
def test_cli_plan_mode_blocks():
    stream = io.StringIO()
    code = run(["--plan", str(PLAN)], stream=stream)
    output = stream.getvalue()
    assert code == 1
    assert "BLOCK CHANGE" in output
    assert "outside current model coverage" in output
    assert "aws_cloudwatch_log_group" in output


def test_cli_plan_mode_json_format():
    stream = io.StringIO()
    run(["--plan", str(PLAN), "--format", "json"], stream=stream)
    payload = json.loads(stream.getvalue())
    assert payload["decision"] == "BLOCK CHANGE"
    assert payload["score"]["delta"] == -80


def test_cli_plan_mode_rejects_mixed_inputs():
    stream = io.StringIO()
    code = run(["--plan", str(PLAN), "--before", str(SAFE_DIR), "--after", str(SAFE_DIR)], stream=stream)
    assert code == 2
    assert "cannot be combined" in stream.getvalue()


def test_cli_plan_mode_reports_bad_file(tmp_path):
    stream = io.StringIO()
    code = run(["--plan", str(tmp_path / "missing.json")], stream=stream)
    assert code == 2
    assert "error:" in stream.getvalue()


def test_plan_with_no_regression_exits_zero(tmp_path):
    """Swap the sides: planned state is safer than prior state."""
    data = load_plan(PLAN)
    swapped = copy.deepcopy(data)
    swapped["prior_state"]["values"]["root_module"] = data["planned_values"]["root_module"]
    swapped["planned_values"]["root_module"] = data["prior_state"]["values"]["root_module"]
    path = tmp_path / "improved.json"
    path.write_text(json.dumps(swapped), encoding="utf-8")

    stream = io.StringIO()
    assert run(["--plan", str(path)], stream=stream) == 0
    assert "SAFE TO MERGE" in stream.getvalue()
