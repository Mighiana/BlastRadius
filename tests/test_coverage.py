"""Input budgets, incomplete analysis decisions, and diagnostic export contracts."""

import copy
import io
import json

import pytest

from blastradius.cli import run
from blastradius.graph import analyze, build_graph, compare
from blastradius.parser import parse_directory, parse_file
from blastradius.parser import limits
from blastradius.parser.coverage import config_diagnostics
from blastradius.parser.limits import InputLimitError
from blastradius.parser.models import ParsedConfig, TerraformResource
from blastradius.parser.plan_parser import PlanParseError, load_plan, parse_plan
from blastradius.report import build_pr_comment, build_report
from blastradius.sarif import build_sarif
from blastradius.security.decision import Decision, decide
from tests.conftest import EXAMPLES


def codes(config):
    return {d.code for d in config_diagnostics(config)}


def test_hcl_unexpanded_constructs_and_jsonencode_are_explicit(tmp_path):
    (tmp_path / "main.tf").write_text('''
module "external" { source = "./module" }
resource "aws_security_group" "web" {
  count = var.count
  ingress {
    protocol = "tcp"
    from_port = 443
    to_port = 443
    cidr_blocks = var.cidrs
  }
}
resource "aws_iam_role_policy" "json" {
  role = var.role
  for_each = var.roles
  policy = jsonencode({Statement = []})
}
''')
    config = parse_directory(tmp_path)
    assert {"UNEXPANDED_MODULE", "UNEXPANDED_RESOURCE", "UNRESOLVED_EXPRESSION",
            "INVALID_POLICY", "UNRESOLVED_RELATIONSHIP"} <= codes(config)
    assert not config.complete
    result = analyze(build_graph(config))
    assert decide(compare(result, result)).decision is Decision.REVIEW


@pytest.mark.parametrize("raw", [
    "not JSON", "[]", "{}", '{"Statement":[]}', '{"Statement":[null]}',
    '{"Statement":[{"Effect":"Allow","Action":["s3:GetObject",null],"Resource":"*"}]}',
    {"Statement": {"Effect": "Permit", "Action": "s3:GetObject", "Resource": "*"}},
], ids=["text", "array", "empty", "empty-statements", "null-statement", "null-action", "bad-effect"])
def test_malformed_policies_cannot_claim_complete(raw):
    config = ParsedConfig(resources=[TerraformResource("aws_iam_policy", "bad", {"policy": raw})])
    assert "INVALID_POLICY" in codes(config)
    result = analyze(build_graph(config))
    assert not result.complete
    assert decide(compare(result, result)).decision is Decision.REVIEW


@pytest.mark.parametrize(("extra", "code"), [
    ({"Condition": {"StringEquals": {"aws:SourceVpc": "vpc-1"}}}, "UNSUPPORTED_IAM_SEMANTICS"),
    ({"Effect": "Deny"}, "IAM_DENY_NOT_EVALUATED"),
    ({"NotAction": "s3:GetObject"}, "UNSUPPORTED_IAM_SEMANTICS"),
    ({"NotResource": "*"}, "UNSUPPORTED_IAM_SEMANTICS"),
    ({"NotPrincipal": "*"}, "UNSUPPORTED_IAM_SEMANTICS"),
    ({"Resource": "${var.bucket}/*"}, "UNRESOLVED_EXPRESSION"),
])
def test_iam_semantics_and_expressions_are_diagnosed(extra, code):
    statement = {"Effect": "Allow", "Action": "s3:GetObject", "Resource": "*", **extra}
    resource = TerraformResource("aws_iam_policy", "policy", {"policy": {"Statement": [statement]}})
    assert code in codes(ParsedConfig(resources=[resource]))


def test_permissions_boundary_and_external_attachment_are_explicit():
    config = ParsedConfig(resources=[
        TerraformResource("aws_iam_role", "role", {"permissions_boundary": "arn:aws:iam::123456789012:policy/boundary"}),
        TerraformResource("aws_iam_role_policy_attachment", "attached", {
            "role": "aws_iam_role.role.name", "policy_arn": "arn:aws:iam::aws:policy/ReadOnlyAccess",
        }),
    ])
    assert {"UNSUPPORTED_CONTROL", "EXTERNAL_POLICY"} <= codes(config)
    assert not analyze(build_graph(config)).complete


def test_missing_policy_and_invalid_acl_are_not_treated_as_known_private():
    config = ParsedConfig(resources=[
        TerraformResource("aws_iam_policy", "missing", {}),
        TerraformResource("aws_s3_bucket", "bad", {"acl": "made-up"}),
    ])
    assert {"INVALID_POLICY", "INVALID_ACL"} <= codes(config)


@pytest.mark.parametrize("block", [
    'resource "aws_s3_bucket_public_access_block" "unknown" { bucket = aws_s3_bucket.data.id\n ignore_public_acls = var.ignore }',
    'resource "aws_s3_bucket_public_access_block" "a" { bucket = aws_s3_bucket.data.id\n ignore_public_acls = true }\n'
    'resource "aws_s3_bucket_public_access_block" "b" { bucket = aws_s3_bucket.data.id\n ignore_public_acls = false }',
], ids=["unknown", "conflicting"])
def test_hcl_unknown_and_conflicting_controls_cannot_suppress_public_acl(tmp_path, block):
    (tmp_path / "main.tf").write_text(
        'resource "aws_s3_bucket" "data" { acl = "public-read"\n tags = { Sensitive = "true" } }\n' + block
    )
    result = analyze(build_graph(parse_directory(tmp_path)))
    assert result.critical_paths and not result.complete


def test_duplicate_hcl_addresses_are_not_silently_merged(tmp_path):
    for name, acl in (("first.tf", "private"), ("second.tf", "public-read")):
        (tmp_path / name).write_text(f'resource "aws_s3_bucket" "data" {{ acl = "{acl}" }}')
    config = parse_directory(tmp_path)
    assert "DUPLICATE_ADDRESS" in codes(config)
    assert not build_graph(config).has_node("aws_s3_bucket.data")
    assert not config.complete


def test_duplicate_json_keys_are_rejected_in_policy_and_plan(tmp_path):
    resource = TerraformResource("aws_iam_policy", "x", {
        "policy": '{"Statement":{"Effect":"Allow","Effect":"Deny","Action":"s3:*","Resource":"*"}}',
    })
    assert "INVALID_POLICY" in codes(ParsedConfig(resources=[resource]))
    path = tmp_path / "plan.json"
    path.write_text('{"planned_values":{},"planned_values":{}}')
    with pytest.raises(PlanParseError, match="not valid JSON"):
        load_plan(path)


def test_hcl_json_and_partial_snapshots_are_diagnosed(tmp_path):
    (tmp_path / "main.tf").write_text('resource "aws_s3_bucket" "data" {}')
    (tmp_path / "other.tf.json").write_text("{}")
    assert "UNSUPPORTED_HCL_JSON" in codes(parse_directory(tmp_path))
    assert "PARTIAL_PLAN_SNAPSHOT" in codes(parse_plan({"resource_changes": []}))


def test_unknown_plan_security_values_propagate_without_mutating_input():
    plan = load_plan(EXAMPLES / "plans" / "ssh_open_plan.json")
    plan["resource_changes"][0]["change"]["after_unknown"] = {"ingress": True, "id": True}
    snapshot = copy.deepcopy(plan)
    config = parse_plan(plan, source="/private/snapshot/plan.json")
    assert plan == snapshot
    unknown = [d for d in config.diagnostics if d.code == "UNKNOWN_PLAN_VALUE"]
    assert len(unknown) == 1 and unknown[0].attribute == "ingress"
    assert unknown[0].source_file == "plan.json"
    assert not config.complete and not analyze(build_graph(config)).complete
    assert "UNKNOWN_PLAN_VALUE" not in codes(parse_plan(plan, "before"))


def test_proposed_unknown_masks_are_checked():
    plan = {"planned_values": {}, "proposed_unknown": {"root_module": {"resources": [
        {"address": "aws_s3_bucket.x", "type": "aws_s3_bucket", "values": {"tags": True}},
    ]}}}
    assert "UNKNOWN_PLAN_VALUE" in codes(parse_plan(plan))


def test_missing_resource_type_is_not_silently_treated_as_empty_plan():
    plan = {"planned_values": {"root_module": {"resources": [{"values": {}}]}}}
    assert "INVALID_RESOURCE" in codes(parse_plan(plan))


def test_unknown_bucket_identity_cannot_hide_literal_policy_scope():
    resource = {"address": "aws_s3_bucket.data", "type": "aws_s3_bucket", "name": "data",
                "values": {"bucket": None}}
    plan = {"planned_values": {"root_module": {"resources": [resource]}},
            "resource_changes": [{**resource, "change": {"after_unknown": {"bucket": True}}}]}
    assert "UNKNOWN_PLAN_VALUE" in codes(parse_plan(plan))


def test_plan_relink_keeps_unresolved_members_of_a_relationship_list():
    plan = {"planned_values": {"root_module": {"resources": [
        {"address": "aws_security_group.web", "type": "aws_security_group", "name": "web", "values": {"id": "sg-known"}},
        {"address": "aws_instance.web", "type": "aws_instance", "name": "web",
         "values": {"vpc_security_group_ids": ["sg-known", "sg-missing"]}},
    ]}}}
    config = parse_plan(plan)
    assert config.by_address("aws_instance.web").get("vpc_security_group_ids") == ["aws_security_group.web.id", "sg-missing"]
    assert "UNRESOLVED_RELATIONSHIP" in codes(config)


def test_plan_expression_attribute_names_are_not_confused_with_plan_schema():
    plan = {"planned_values": {}, "configuration": {"root_module": {"resources": [{
        "address": "aws_iam_role.x", "type": "aws_iam_role", "name": "x",
        "expressions": {"name": {"constant_value": "role"},
                        "inline_policy": {"constant_value": [{"name": "policy", "policy": "{}"}]},
                        "tags": {"constant_value": {"resources": "test", "type": [1]}}},
    }]}}}
    assert parse_plan(plan).complete


@pytest.mark.parametrize("resource_type", [
    "aws_route_table", "aws_db_instance", "aws_lambda_function", "aws_kms_key",
    "aws_vpc_security_group_ingress_rule",
])
def test_unsupported_security_resources_require_review(tmp_path, resource_type):
    (tmp_path / "main.tf").write_text(f'resource "{resource_type}" "external" {{}}')
    result = analyze(build_graph(parse_directory(tmp_path)))
    assert not result.complete
    assert decide(compare(result, result)).decision is Decision.REVIEW


def test_missing_relationship_never_claims_safe():
    resource = TerraformResource("aws_instance", "web", {"iam_instance_profile": "aws_iam_instance_profile.absent.name"})
    result = analyze(build_graph(ParsedConfig(resources=[resource])))
    assert "UNRESOLVED_REFERENCE" in {d.code for d in result.diagnostics}
    assert decide(compare(result, result)).decision is Decision.REVIEW


@pytest.mark.parametrize("shape", [
    {"planned_values": []},
    {"planned_values": {"root_module": {"resources": [None]}}},
    {"prior_state": {"values": {"root_module": {"resources": [42]}}}},
    {"configuration": {"root_module": {"module_calls": {"x": 5}}}},
    {"planned_values": {"root_module": {"resources": [{"type": []}]}}},
    {"proposed_unknown": {"root_module": {"resources": [None]}}},
], ids=["values", "resources", "prior", "module", "type", "unknown"])
def test_malformed_plan_structure_fails_cleanly(shape):
    with pytest.raises(PlanParseError):
        parse_plan(shape)


def test_default_byte_budget_rejects_large_hcl_and_plan(tmp_path):
    hcl = tmp_path / "main.tf"
    hcl.write_text("#" + "x" * limits.MAX_INPUT_BYTES)
    with pytest.raises(InputLimitError):
        parse_file(hcl)
    plan = tmp_path / "plan.json"
    plan.write_text(" " * (limits.MAX_INPUT_BYTES + 1))
    with pytest.raises(PlanParseError):
        load_plan(plan)
    out = io.StringIO()
    assert run(["--before", str(tmp_path), "--after", str(tmp_path)], stream=out) == 2
    assert str(tmp_path) not in out.getvalue()


def test_depth_budget_rejects_hcl_plan_and_embedded_policy(tmp_path):
    nested = "[" * (limits.MAX_DEPTH + 1) + "0" + "]" * (limits.MAX_DEPTH + 1)
    (tmp_path / "main.tf").write_text(f"locals {{ value = {nested} }}")
    with pytest.raises(InputLimitError):
        parse_directory(tmp_path)
    plan = tmp_path / "plan.json"
    plan.write_text(nested)
    with pytest.raises(PlanParseError):
        load_plan(plan)
    resource = TerraformResource("aws_iam_policy", "deep", {"policy": nested})
    assert "INVALID_POLICY" in codes(ParsedConfig(resources=[resource]))


def test_file_resource_and_value_budgets(tmp_path):
    for index in range(limits.MAX_FILES + 1):
        (tmp_path / f"{index}.tf").write_text("")
    with pytest.raises(InputLimitError, match="files"):
        parse_directory(tmp_path)
    resource_file = tmp_path / "many.tf"
    resource_file.write_text("\n".join(
        f'resource "aws_s3_bucket" "bucket_{index}" {{}}' for index in range(limits.MAX_RESOURCES + 1)
    ))
    with pytest.raises(InputLimitError, match="resources"):
        parse_file(resource_file)
    with pytest.raises(InputLimitError, match="structure"):
        limits.check_structure([0] * limits.MAX_VALUES)


def test_symlink_inputs_are_rejected(tmp_path):
    target = tmp_path / "real.txt"
    target.write_text('resource "aws_s3_bucket" "data" {}')
    link = tmp_path / "main.tf"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Symlinks unavailable on this platform")
    with pytest.raises(InputLimitError, match="symlink"):
        parse_directory(tmp_path)


@pytest.mark.parametrize("fmt", ["summary", "pr", "json", "sarif"])
def test_cli_diagnostics_and_fail_on_review_contract(tmp_path, fmt):
    (tmp_path / "main.tf").write_text('resource "aws_s3_bucket" "data" { acl = var.acl }')
    out = io.StringIO()
    args = ["--before", str(tmp_path), "--after", str(tmp_path), "--format", fmt]
    assert run(args, stream=out) == 0
    assert str(tmp_path) not in out.getvalue()
    assert "UNRESOLVED_EXPRESSION" in out.getvalue()
    if fmt == "json":
        payload = json.loads(out.getvalue())
        assert payload["analysis_complete"] is False
        assert payload["coverage_diagnostics"][0]["source_file"] == "main.tf"
        assert payload["decision"] == "REVIEW REQUIRED"
    elif fmt == "sarif":
        payload = json.loads(out.getvalue())
        assert payload["runs"][0]["properties"]["analysisComplete"] is False
        assert any(r["ruleId"] == "BR004" for r in payload["runs"][0]["results"])
    assert run([*args, "--fail-on-review"], stream=io.StringIO()) == 1


def test_reports_show_incomplete_baseline_and_no_host_paths():
    config = ParsedConfig(resources=[TerraformResource("aws_s3_bucket", "data", {
        "acl": "var.acl",
    }, "/private/snapshot/main.tf")])
    before = analyze(build_graph(config))
    after = analyze(build_graph(ParsedConfig()))
    diff = compare(before, after)
    assert not diff.complete and decide(diff).decision is Decision.REVIEW
    for output in (build_report(diff), build_pr_comment(diff), json.dumps(build_sarif(diff))):
        assert "UNRESOLVED_EXPRESSION" in output
        assert "/private/snapshot" not in output
