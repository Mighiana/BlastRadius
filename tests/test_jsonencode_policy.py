"""jsonencode() IAM policy modeling: reproduction of the hosted INVALID_POLICY
case plus acceptance, negative and false-positive regressions.

Hosted failure reproduced here: a public SSH change whose aws_iam_role_policy
uses `policy = jsonencode({...})` surfaced INVALID_POLICY / REVIEW REQUIRED
instead of the intended BLOCK CHANGE. The AST hcl2 hands us is a string
`${jsonencode({Version = "...", Statement = [...]})}` — a serialized expression,
not JSON — which is what the bounded evaluator in
blastradius/parser/expression.py normalizes.
"""

import json

import pytest

from blastradius.graph import analyze, build_graph, compare
from blastradius.parser import parse_directory
from blastradius.parser.coverage import config_diagnostics
from blastradius.security.decision import Decision, decide


def _write_config(directory, cidr, policy_source="jsonencode"):
    if policy_source == "jsonencode":
        policy = """\
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:GetObject",
        "s3:ListBucket"
      ]
      Resource = [
        aws_s3_bucket.customer_data.arn,
        "${aws_s3_bucket.customer_data.arn}/*"
      ]
    }]
  })
"""
    else:
        policy = f'  policy = {policy_source}\n'
    (directory / "main.tf").write_text(f'''\
resource "aws_security_group" "web" {{
  ingress {{
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["{cidr}"]
  }}
}}

resource "aws_instance" "web" {{
  vpc_security_group_ids = [aws_security_group.web.id]
  iam_instance_profile   = aws_iam_instance_profile.app_profile.name
}}

resource "aws_iam_instance_profile" "app_profile" {{
  role = aws_iam_role.app_role.id
}}

resource "aws_iam_role" "app_role" {{
  assume_role_policy = <<POLICY
{{"Version": "2012-10-17", "Statement": []}}
POLICY
}}

resource "aws_iam_role_policy" "app_data_access" {{
  name = "app-data-access"
  role = aws_iam_role.app_role.id
{policy}}}

resource "aws_s3_bucket" "customer_data" {{
  bucket = "customer-data"
  tags = {{
    Name        = "Customer Data"
    Sensitivity = "high"
    DataClass   = "sensitive"
  }}
}}
''')


def _diff(tmp_path, policy_source="jsonencode"):
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    baseline.mkdir()
    candidate.mkdir()
    _write_config(baseline, "10.0.0.0/24", policy_source)
    _write_config(candidate, "0.0.0.0/0", policy_source)
    before = analyze(build_graph(parse_directory(baseline)))
    after = analyze(build_graph(parse_directory(candidate)))
    return before, after, compare(before, after)


def test_jsonencode_role_policy_produces_block_not_invalid_policy(tmp_path):
    """The hosted acceptance case: public SSH + jsonencode policy -> BLOCK."""
    before, after, diff = _diff(tmp_path)
    codes = {d.code for d in after.diagnostics}
    assert "INVALID_POLICY" not in codes
    assert "IAM_POLICY_EXPRESSION_UNRESOLVED" not in codes
    decision = decide(diff)
    assert decision.decision is Decision.BLOCK
    assert diff.new_critical_paths


def test_jsonencode_models_role_to_bucket_edge(tmp_path):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    _write_config(candidate, "0.0.0.0/0")
    graph = build_graph(parse_directory(candidate))
    edge = graph.edges["aws_iam_role.app_role", "aws_s3_bucket.customer_data"]["edge"]
    assert edge.relationship.value == "CAN_ACCESS"


def test_jsonencode_policy_normalizes_to_canonical_document(tmp_path):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    _write_config(candidate, "10.0.0.0/24")
    config = parse_directory(candidate)
    policy_resource = next(r for r in config.resources if r.type == "aws_iam_role_policy")
    from blastradius.parser.values import parse_policy_document
    document = parse_policy_document(policy_resource.get("policy"))
    assert document["Version"] == "2012-10-17"
    statement = document["Statement"][0]
    assert statement["Effect"] == "Allow"
    assert "s3:GetObject" in statement["Action"]
    assert any("aws_s3_bucket.customer_data" in str(r) for r in statement["Resource"])


@pytest.mark.parametrize("policy_source", [
    'jsonencode({Version = "2012-10-17", Statement = var.security_policy})',
    'jsonencode({Version = "2012-10-17", Statement = concat([], [])})',
    'jsonencode({Version = "2012-10-17", Statement = local.doc})',
    '"not a policy at all"',
    'jsonencode({Version = "2012-10-17"})',
], ids=["var-ref", "unsupported-function", "local-ref", "malformed", "missing-statement"])
def test_unresolvable_policy_stays_review_required(tmp_path, policy_source):
    """Unknown/unsupported policy semantics must never become SAFE."""
    before, after, diff = _diff(tmp_path, policy_source)
    codes = {d.code for d in after.diagnostics}
    assert codes & {"INVALID_POLICY", "IAM_POLICY_EXPRESSION_UNRESOLVED"}
    assert decide(diff).decision is Decision.REVIEW


def test_policy_against_unrelated_bucket_creates_no_edge(tmp_path):
    """jsonencode must not invent paths to buckets it does not reference."""
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    _write_config(candidate, "0.0.0.0/0")
    (candidate / "main.tf").write_text(
        (candidate / "main.tf").read_text().replace(
            "aws_s3_bucket.customer_data.arn", "aws_s3_bucket.other_bucket.arn"
        ).replace('"${aws_s3_bucket.other_bucket.arn}/*"', '"${aws_s3_bucket.other_bucket.arn}/*"')
        + '''
resource "aws_s3_bucket" "other_bucket" {
  bucket = "other"
}
'''
    )
    config = parse_directory(candidate)
    graph = build_graph(config)
    assert not graph.has_edge("aws_iam_role.app_role", "aws_s3_bucket.customer_data")


def test_deny_statement_creates_no_access_edge(tmp_path):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    _write_config(candidate, "0.0.0.0/0", 'jsonencode({Version = "2012-10-17", Statement = [{Effect = "Deny", Action = "s3:GetObject", Resource = "${aws_s3_bucket.customer_data.arn}"}]})')
    graph = build_graph(parse_directory(candidate))
    assert not graph.has_edge("aws_iam_role.app_role", "aws_s3_bucket.customer_data")


def test_private_security_group_has_no_internet_path(tmp_path):
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    _write_config(baseline, "10.0.0.0/24")
    graph = build_graph(parse_directory(baseline))
    assert not any(source == "INTERNET" for source, _ in graph.edges)


def test_managed_policy_attachment_with_jsonencode_is_modeled(tmp_path):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    _write_config(candidate, "0.0.0.0/0")
    text = (candidate / "main.tf").read_text()
    start = text.index('resource "aws_iam_role_policy"')
    end = text.index('resource "aws_s3_bucket"')
    text = text[:start] + '''resource "aws_iam_policy" "data" {
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = {
      Effect   = "Allow"
      Action   = "s3:GetObject"
      Resource = "${aws_s3_bucket.customer_data.arn}/*"
    }
  })
}

resource "aws_iam_role_policy_attachment" "data" {
  role       = aws_iam_role.app_role.name
  policy_arn = aws_iam_policy.data.arn
}

''' + text[end:]
    (candidate / "main.tf").write_text(text)
    config = parse_directory(candidate)
    assert not {d.code for d in config_diagnostics(config)} & {"INVALID_POLICY", "IAM_POLICY_EXPRESSION_UNRESOLVED"}
    assert build_graph(config).has_edge("aws_iam_role.app_role", "aws_s3_bucket.customer_data")


def test_interpolated_variable_inside_resource_string_stays_review(tmp_path):
    before, after, diff = _diff(
        tmp_path,
        'jsonencode({Version = "2012-10-17", Statement = [{Effect = "Allow", Action = "s3:GetObject", Resource = "${var.bucket_arn}/*"}]})',
    )
    assert "UNRESOLVED_EXPRESSION" in {d.code for d in after.diagnostics}
    assert decide(diff).decision is Decision.REVIEW


def test_sensitive_bucket_without_iam_relationship_has_no_critical_path(tmp_path):
    before, after, diff = _diff(
        tmp_path,
        'jsonencode({Version = "2012-10-17", Statement = [{Effect = "Allow", Action = "ec2:DescribeInstances", Resource = "*"}]})',
    )
    assert not diff.new_critical_paths


@pytest.mark.parametrize("tags, sensitive", [
    ('Sensitive = "true"', True),
    ('Sensitivity = "high"', True),
    ('Sensitivity = "Critical"', True),
    ('DataClass = "pii"', True),
    ('DataClass = "restricted"', True),
    ('DataClass = "sensitive"', True),
    ('Sensitivity = "low"', False),
    ('DataClass = "public"', False),
    ('Name = "sensitive-customer-data"', False),
], ids=lambda v: str(v).replace(" ", "")[:30])
def test_sensitivity_tag_conventions(tmp_path, tags, sensitive):
    from blastradius.security.rules import is_sensitive_bucket
    (tmp_path / "main.tf").write_text(f'resource "aws_s3_bucket" "b" {{\n  tags = {{ {tags} }}\n}}\n')
    bucket = parse_directory(tmp_path).resources[0]
    assert is_sensitive_bucket(bucket) is sensitive


@pytest.mark.parametrize("text", [
    "{" * 200 + "}" * 200,
    "[" + ", ".join(["1"] * 5000) + "]",
    '{A = "unterminated}',
    '{A = __import__("os").system("id")}',
    '{A = aws_s3_bucket.b.arn + 1}',
    '{A = true ? "x" : "y"}',
], ids=["deep-nesting", "huge-list", "unterminated", "python-injection", "operator", "conditional"])
def test_evaluator_rejects_or_flags_hostile_input(text):
    from blastradius.parser.expression import ExpressionError, evaluate_expression
    try:
        _value, problems = evaluate_expression(text)
    except ExpressionError:
        return
    assert problems


def test_unresolved_diagnostic_is_bounded_and_omits_policy_source(tmp_path):
    secret_like = "AKIA" + "X" * 400
    before, after, diff = _diff(
        tmp_path,
        f'jsonencode({{Version = "2012-10-17", Statement = {secret_like}(1)}})',
    )
    messages = [d.message for d in after.diagnostics if d.code == "IAM_POLICY_EXPRESSION_UNRESOLVED"]
    assert messages
    assert all(len(m) < 300 for m in messages)
    assert all("X" * 150 not in m for m in messages)


def test_plan_json_resolved_policy_still_modeled():
    from blastradius.parser.plan_parser import parse_plan_file
    from tests.conftest import EXAMPLES
    config = parse_plan_file(EXAMPLES / "plans" / "ssh_open_plan.json")
    assert "INVALID_POLICY" not in {d.code for d in config_diagnostics(config)}
