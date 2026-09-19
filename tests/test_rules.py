"""Security rule detection."""

from blastradius.parser.models import Risk, TerraformResource
from blastradius.security import rules


def _sg(ingress) -> TerraformResource:
    return TerraformResource(type="aws_security_group", name="test", attributes={"ingress": ingress})


def test_detects_public_ssh_as_critical():
    findings = rules.public_ingress_findings(
        _sg([{"from_port": 22, "to_port": 22, "protocol": "tcp", "cidr_blocks": ["0.0.0.0/0"]}])
    )
    assert len(findings) == 1
    assert findings[0].is_admin_port
    assert findings[0].risk is Risk.CRITICAL
    assert "0.0.0.0/0" in findings[0].reason


def test_detects_public_rdp():
    findings = rules.public_ingress_findings(
        _sg([{"from_port": 3389, "to_port": 3389, "protocol": "tcp", "cidr_blocks": ["0.0.0.0/0"]}])
    )
    assert findings[0].risk is Risk.CRITICAL


def test_private_cidr_is_not_public():
    assert rules.public_ingress_findings(
        _sg([{"from_port": 22, "to_port": 22, "protocol": "tcp", "cidr_blocks": ["10.0.0.0/24"]}])
    ) == []


def test_all_protocols_open_is_critical_and_broad():
    finding = rules.public_ingress_findings(
        _sg([{"from_port": 0, "to_port": 0, "protocol": "-1", "cidr_blocks": ["0.0.0.0/0"]}])
    )[0]
    assert finding.is_broad_range and finding.is_admin_port


def test_public_https_only_is_medium():
    finding = rules.public_ingress_findings(
        _sg([{"from_port": 443, "to_port": 443, "protocol": "tcp", "cidr_blocks": ["0.0.0.0/0"]}])
    )[0]
    assert finding.risk is Risk.MEDIUM and not finding.is_admin_port


def test_port_range_covering_ssh_is_critical():
    finding = rules.public_ingress_findings(
        _sg([{"from_port": 1, "to_port": 1024, "protocol": "tcp", "cidr_blocks": ["0.0.0.0/0"]}])
    )[0]
    assert finding.is_admin_port and finding.is_broad_range


def test_ipv6_public_cidr_detected():
    finding = rules.public_ingress_findings(
        _sg([{"from_port": 22, "to_port": 22, "protocol": "tcp", "ipv6_cidr_blocks": ["::/0"]}])
    )[0]
    assert finding.cidr == "::/0"


def test_egress_is_ignored():
    sg = TerraformResource(
        type="aws_security_group",
        name="test",
        attributes={"egress": [{"from_port": 0, "to_port": 0, "protocol": "-1", "cidr_blocks": ["0.0.0.0/0"]}]},
    )
    assert rules.public_ingress_findings(sg) == []


def test_instance_role_resolved_through_instance_profile(vulnerable_config):
    instance = vulnerable_config.by_address("aws_instance.web_server")
    profiles = vulnerable_config.of_type("aws_iam_instance_profile")
    assert rules.instance_role_addresses(instance, profiles) == ["aws_iam_role.app"]


def test_s3_access_finding_targets_specific_bucket(safe_config):
    policy = safe_config.by_address("aws_iam_role_policy.app_s3_read").get("policy")
    finding = rules.s3_access_findings(policy)[0]
    assert finding.bucket_addresses == ["aws_s3_bucket.customer_data"]
    assert not finding.targets_all_buckets
    assert finding.risk is Risk.MEDIUM


def test_wildcard_s3_policy_is_critical():
    document = {
        "Statement": [{"Effect": "Allow", "Action": "s3:*", "Resource": "*"}]
    }
    finding = rules.s3_access_findings(document)[0]
    assert finding.targets_all_buckets and finding.has_wildcard_action
    assert finding.risk is Risk.CRITICAL


def test_deny_statements_are_ignored():
    document = {"Statement": [{"Effect": "Deny", "Action": "s3:*", "Resource": "*"}]}
    assert rules.s3_access_findings(document) == []


def test_non_s3_actions_are_ignored():
    document = {"Statement": [{"Effect": "Allow", "Action": "ec2:Describe*", "Resource": "*"}]}
    assert rules.s3_access_findings(document) == []


def test_sensitive_bucket_detected_by_tag(safe_config):
    bucket = safe_config.by_address("aws_s3_bucket.customer_data")
    assert rules.is_sensitive_bucket(bucket)


def test_untagged_bucket_is_not_sensitive():
    bucket = TerraformResource(type="aws_s3_bucket", name="logs", attributes={"tags": {"Name": "logs"}})
    assert not rules.is_sensitive_bucket(bucket)


def test_dataclass_tag_marks_sensitive():
    bucket = TerraformResource(
        type="aws_s3_bucket", name="phi", attributes={"tags": {"DataClassification": "PHI"}}
    )
    assert rules.is_sensitive_bucket(bucket)


def test_role_policy_documents_follows_role_reference(safe_config):
    documents = rules.role_policy_documents("aws_iam_role.app", safe_config.resources)
    assert len(documents) == 1
