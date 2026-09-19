"""Terraform parsing and normalization."""

from blastradius.parser.terraform_parser import (
    as_list,
    parse_policy_document,
    policy_statements,
    references,
)


def test_parses_all_supported_resources(safe_config):
    addresses = {r.address for r in safe_config.resources}
    assert addresses == {
        "aws_security_group.web",
        "aws_instance.web_server",
        "aws_iam_role.app",
        "aws_iam_instance_profile.app",
        "aws_iam_role_policy.app_s3_read",
        "aws_s3_bucket.customer_data",
    }


def test_string_values_are_unquoted(safe_config):
    sg = safe_config.by_address("aws_security_group.web")
    assert sg.get("name") == "web-sg"


def test_ingress_blocks_are_normalized_to_dicts(safe_config):
    ingress = safe_config.by_address("aws_security_group.web").get("ingress")
    assert isinstance(ingress, list)
    assert ingress[0]["from_port"] == 22
    assert ingress[0]["cidr_blocks"] == ["10.0.0.0/24"]


def test_interpolations_are_unwrapped(safe_config):
    instance = safe_config.by_address("aws_instance.web_server")
    assert instance.get("iam_instance_profile") == "aws_iam_instance_profile.app.name"


def test_heredoc_policy_is_valid_json(safe_config):
    policy = safe_config.by_address("aws_iam_role_policy.app_s3_read").get("policy")
    document = parse_policy_document(policy)
    assert document["Version"] == "2012-10-17"
    assert len(policy_statements(document)) == 1


def test_references_finds_terraform_addresses(safe_config):
    policy = safe_config.by_address("aws_iam_role_policy.app_s3_read")
    assert references(policy.attributes) == ["aws_iam_role.app", "aws_s3_bucket.customer_data"]


def test_unparseable_policy_degrades_gracefully():
    assert parse_policy_document("jsonencode({})") == {}
    assert parse_policy_document(None) == {}


def test_as_list_coerces_scalars():
    assert as_list("s3:GetObject") == ["s3:GetObject"]
    assert as_list(["a", "b"]) == ["a", "b"]
    assert as_list(None) == []


def test_safe_and_vulnerable_differ_by_one_line(safe_config, vulnerable_config):
    """The demo relies on the two configs differing only in the SSH ingress CIDR."""
    safe_ingress = safe_config.by_address("aws_security_group.web").get("ingress")
    vuln_ingress = vulnerable_config.by_address("aws_security_group.web").get("ingress")
    assert safe_ingress[0]["cidr_blocks"] == ["10.0.0.0/24"]
    assert vuln_ingress[0]["cidr_blocks"] == ["0.0.0.0/0"]


def test_demo_configs_differ_by_exactly_one_line():
    """The headline demo claim, enforced literally so it cannot rot."""
    import difflib

    from tests.conftest import SAFE_DIR, VULNERABLE_DIR

    safe = (SAFE_DIR / "main.tf").read_text(encoding="utf-8").splitlines()
    vulnerable = (VULNERABLE_DIR / "main.tf").read_text(encoding="utf-8").splitlines()
    assert len(safe) == len(vulnerable)

    changed = [
        (a, b) for a, b in zip(safe, vulnerable) if a != b
    ]
    assert len(changed) == 1
    assert changed[0][0].strip() == 'cidr_blocks = ["10.0.0.0/24"]'
    assert changed[0][1].strip() == 'cidr_blocks = ["0.0.0.0/0"]'
    # Guard against the files drifting apart anywhere else.
    assert len(list(difflib.unified_diff(safe, vulnerable, n=0, lineterm=""))) == 5
