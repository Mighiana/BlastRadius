"""Security rules that decide which attack-graph edges exist.

Every rule is a pure function over parsed Terraform. Keeping them here (rather
than inside the graph builder) means new AWS resource support is mostly a matter
of adding a rule plus an edge type.

This is a deliberately simplified model of AWS reachability - see the README.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import Any, Dict, List, Optional, Tuple

from blastradius.parser.models import Risk, TerraformResource
from blastradius.parser.terraform_parser import (
    as_list,
    parse_policy_document,
    policy_statements,
    references,
)

# CIDRs that mean "anyone on the internet".
PUBLIC_CIDRS = {"0.0.0.0/0", "::/0"}

# Ports whose public exposure we treat as administrative access to the host.
ADMIN_PORTS: Dict[int, str] = {22: "SSH", 3389: "RDP"}

# Tag keys/values that mark a resource as holding sensitive data.
SENSITIVE_TAG_KEYS = ("sensitive", "blastradius_sensitive")
SENSITIVE_DATA_CLASSES = ("pii", "phi", "secret", "confidential", "restricted")



@dataclass
class IngressFinding:
    """One security-group ingress rule that exposes a port to the internet."""

    cidr: str
    from_port: int
    to_port: int
    protocol: str
    port_label: str
    is_admin_port: bool
    is_broad_range: bool
    risk: Risk
    reason: str


    @property
    def evidence(self) -> str:
        """The Terraform that proves this exposure, for display in the UI."""
        ports = (
            "all ports"
            if self.protocol in ("-1", "all")
            else f"from_port = {self.from_port}, to_port = {self.to_port}"
        )
        return f'ingress {{ protocol = "{self.protocol}", {ports}, cidr_blocks = ["{self.cidr}"] }}'


@dataclass
class S3AccessFinding:
    """An IAM statement that grants an S3 action, and what it targets."""

    actions: List[str]
    bucket_addresses: List[str] = field(default_factory=list)
    targets_all_buckets: bool = False
    has_wildcard_action: bool = False
    risk: Risk = Risk.MEDIUM
    reason: str = ""
    resources: list[str] = field(default_factory=list)
    data_read: bool = False
    conditional: bool = False

    @property
    def evidence(self) -> str:
        scope = '"*"' if self.targets_all_buckets else "the bucket ARN"
        return f'"Action": {self.actions}, "Resource": {scope}'


def is_public_cidr(cidr: Any) -> bool:
    return isinstance(cidr, str) and cidr.strip() in PUBLIC_CIDRS


def _port_label(from_port: int, to_port: int, protocol: str) -> str:
    if protocol in ("-1", "all"):
        return "all protocols/ports"
    if from_port == to_port:
        named = ADMIN_PORTS.get(from_port)
        return f"port {from_port} ({named})" if named else f"port {from_port}"
    return f"ports {from_port}-{to_port}/{protocol}"


def _covers_admin_port(from_port: int, to_port: int, protocol: str) -> Optional[int]:
    if protocol in ("-1", "all"):
        return next(iter(ADMIN_PORTS))
    if protocol not in ("tcp", "udp", "6", "17"):
        return None
    for port in ADMIN_PORTS:
        if from_port <= port <= to_port:
            return port
    return None


def public_ingress_findings(security_group: TerraformResource) -> List[IngressFinding]:
    """Find every ingress rule on this security group open to the internet.

    A rule is reported when its `cidr_blocks` include 0.0.0.0/0 or ::/0.
    Severity escalates when the rule reaches an administrative port (22/3389)
    or spans an unreasonably wide port range.
    """
    findings: List[IngressFinding] = []
    for rule in as_list(security_group.get("ingress")):
        if not isinstance(rule, dict):
            continue
        protocol = str(rule.get("protocol", "tcp"))
        try:
            from_port = int(rule.get("from_port", 0) or 0)
            to_port = int(rule.get("to_port", from_port) or from_port)
        except (ValueError, TypeError, OverflowError):
            continue
        public = [c for c in as_list(rule.get("cidr_blocks")) if is_public_cidr(c)]
        public += [c for c in as_list(rule.get("ipv6_cidr_blocks")) if is_public_cidr(c)]
        if not public:
            continue

        admin_port = _covers_admin_port(from_port, to_port, protocol)
        is_broad_range = protocol in ("-1", "all") or (to_port - from_port) >= 100
        label = _port_label(from_port, to_port, protocol)

        if admin_port is not None:
            risk = Risk.CRITICAL
        elif is_broad_range:
            risk = Risk.HIGH
        else:
            risk = Risk.MEDIUM

        for cidr in public:
            findings.append(
                IngressFinding(
                    cidr=cidr,
                    from_port=from_port,
                    to_port=to_port,
                    protocol=protocol,
                    port_label=label,
                    is_admin_port=admin_port is not None,
                    is_broad_range=is_broad_range,
                    risk=risk,
                    reason=f"Security group allows {cidr} on {label}",
                )
            )
    return findings


def instance_role_addresses(
    instance: TerraformResource,
    instance_profiles: List[TerraformResource],
) -> List[str]:
    """Resolve the IAM roles an EC2 instance can use via its instance profile.

    Follows `aws_instance.iam_instance_profile -> aws_iam_instance_profile.role
    -> aws_iam_role`, and also accepts a role referenced directly.
    """
    roles: List[str] = []
    for ref in references(instance.get("iam_instance_profile")):
        if ref.startswith("aws_iam_role."):
            roles.append(ref)
            continue
        profile = next((p for p in instance_profiles if p.address == ref), None)
        if profile is None:
            continue
        for role_ref in references(profile.get("role")):
            if role_ref.startswith("aws_iam_role.") and role_ref not in roles:
                roles.append(role_ref)
    return roles


def _statement_s3_actions(statement: Dict[str, Any]) -> List[str]:
    actions = [a for a in as_list(statement.get("Action")) if isinstance(a, str)]
    return [a for a in actions if a == "*" or a.lower().startswith("s3:")]


def permits_object_read(actions: list[str]) -> bool:
    return any(aws_pattern_matches(action, pattern.lower()) for pattern in actions
               for action in ("s3:getobject", "s3:getobjectversion"))


def aws_pattern_matches(value: str, pattern: str) -> bool:
    return fnmatchcase(value, pattern.replace("[", "[[]"))


def anonymous_principal(principal: object) -> bool:
    if principal == "*":
        return True
    return isinstance(principal, dict) and "*" in as_list(principal.get("AWS"))


def bucket_resource_matches(patterns: list[str], bucket: TerraformResource, objects_only: bool = False) -> bool:
    for pattern in patterns:
        if pattern == "*":
            return True
        if bucket.address in references(pattern):
            if not objects_only or ".arn}/" in pattern or ".arn/" in pattern:
                return True
        for arn in (bucket.get("arn"), f"arn:aws:s3:::{bucket.get('bucket')}" if bucket.get("bucket") else None):
            if not isinstance(arn, str):
                continue
            if not objects_only and aws_pattern_matches(arn, pattern):
                return True
            # Any nonempty object key under a matching bucket is a possible target.
            bucket_pattern, separator, key_pattern = pattern.partition("/")
            if separator and key_pattern and aws_pattern_matches(arn, bucket_pattern):
                return True
    return False


def s3_access_findings(policy_document: Any) -> List[S3AccessFinding]:
    """Extract S3 grants from an IAM policy document.

    Recognises three cases that matter for reachability:
      * explicit bucket ARNs  -> edge to those buckets
      * `"Resource": "*"`     -> edge to every bucket in the config
      * `s3:*` or `*` actions -> elevated risk on the resulting edge
    """
    policy = parse_policy_document(policy_document)
    findings: List[S3AccessFinding] = []

    for statement in policy_statements(policy):
        if statement.get("Effect") != "Allow":
            continue
        s3_actions = _statement_s3_actions(statement)
        if not s3_actions:
            continue

        resources = [str(r) for r in as_list(statement.get("Resource"))]
        bucket_addresses = [
            ref for ref in references(resources) if ref.startswith("aws_s3_bucket.")
        ]
        targets_all = any(r.strip() in ("*", "arn:aws:s3:::*", "arn:aws:s3:::*/*") for r in resources)
        wildcard_action = any("*" in a or "?" in a for a in s3_actions)

        if targets_all and wildcard_action:
            risk, reason = Risk.CRITICAL, f"Role allows {', '.join(s3_actions)} on all resources (*)"
        elif targets_all:
            risk, reason = Risk.HIGH, f"Role allows {', '.join(s3_actions)} on all resources (*)"
        elif wildcard_action:
            risk, reason = Risk.HIGH, f"Role allows {', '.join(s3_actions)} on the bucket"
        else:
            risk, reason = Risk.MEDIUM, f"Role allows {', '.join(s3_actions)} on the bucket"

        findings.append(
            S3AccessFinding(
                actions=s3_actions,
                bucket_addresses=bucket_addresses,
                targets_all_buckets=targets_all,
                has_wildcard_action=wildcard_action,
                risk=risk,
                reason=reason,
                resources=resources,
                data_read=permits_object_read(s3_actions),
                conditional="Condition" in statement,
            )
        )
    return findings


def role_policy_sources(
    role_address: str,
    config_resources: List[TerraformResource],
) -> List[Tuple[str, Any]]:
    """Policy documents applying to a role, paired with the resource that owns them.

    The owning address is what lets the UI answer "which Terraform block created
    this edge?".
    """
    sources: List[Tuple[str, Any]] = []
    for resource in config_resources:
        if resource.type == "aws_iam_role_policy":
            if role_address in references(resource.get("role")):
                sources.append((resource.address, resource.get("policy")))
        elif resource.type == "aws_iam_role_policy_attachment":
            if role_address not in references(resource.get("role")):
                continue
            for ref in references(resource.get("policy_arn")):
                managed = next(
                    (r for r in config_resources if r.address == ref and r.type == "aws_iam_policy"),
                    None,
                )
                if managed is not None:
                    sources.append((managed.address, managed.get("policy")))
    return sources


def role_policy_documents(
    role_address: str,
    config_resources: List[TerraformResource],
) -> List[Any]:
    """Collect every inline/attached policy document that applies to a role."""
    return [document for _, document in role_policy_sources(role_address, config_resources)]


PUBLIC_ACLS = ("public-read", "public-read-write")


@dataclass
class PublicBucketFinding:
    """An S3 bucket that is readable directly from the internet."""

    reason: str
    evidence: str
    terraform_resource: str
    risk: Risk = Risk.HIGH
    conditional: bool = False


def bucket_public_access_block(bucket: TerraformResource, config_resources: list[TerraformResource]) -> dict[str, bool]:
    controls = [r for r in config_resources if r.type == "aws_s3_bucket_public_access_block"
                and bucket.address in references(r.get("bucket"))]
    if len(controls) != 1:
        return {}
    return {name: controls[0].get(name) is True for name in (
        "block_public_acls", "ignore_public_acls", "block_public_policy", "restrict_public_buckets"
    )}


def public_bucket_findings(
    bucket: TerraformResource,
    config_resources: List[TerraformResource],
) -> List[PublicBucketFinding]:
    """Detect direct public exposure of an S3 bucket.

    Two mechanisms are recognised:
      * a public canned ACL, set inline on the bucket or via `aws_s3_bucket_acl`
      * a bucket policy that allows an `s3:Get*`/`*` action to Principal `"*"`
    """
    findings: List[PublicBucketFinding] = []
    controls = bucket_public_access_block(bucket, config_resources)

    acl_sources: List[Tuple[str, Any]] = [(bucket.address, bucket.get("acl"))]
    for resource in config_resources:
        if resource.type == "aws_s3_bucket_acl" and bucket.address in references(
            resource.get("bucket")
        ):
            acl_sources.append((resource.address, resource.get("acl")))

    for address, acl in acl_sources:
        if isinstance(acl, str) and acl.strip().lower() in PUBLIC_ACLS and not controls.get("ignore_public_acls"):
            findings.append(
                PublicBucketFinding(
                    reason=f'Bucket ACL is "{acl}", allowing anonymous read access',
                    evidence=f'acl = "{acl}"',
                    terraform_resource=address,
                    risk=Risk.CRITICAL if "write" in acl else Risk.HIGH,
                )
            )

    for resource in config_resources:
        if resource.type != "aws_s3_bucket_policy":
            continue
        if bucket.address not in references(resource.get("bucket")):
            continue
        for statement in policy_statements(parse_policy_document(resource.get("policy"))):
            if statement.get("Effect") != "Allow":
                continue
            principals = statement.get("Principal")
            if not anonymous_principal(principals):
                continue
            actions = [a for a in as_list(statement.get("Action")) if isinstance(a, str)]
            if not permits_object_read(actions):
                continue
            resources = [r for r in as_list(statement.get("Resource")) if isinstance(r, str)]
            if not bucket_resource_matches(resources, bucket, objects_only=True):
                continue
            if controls.get("restrict_public_buckets") and "Condition" not in statement:
                continue
            findings.append(
                PublicBucketFinding(
                    reason=(
                        f"Bucket policy allows {', '.join(actions)} to Principal \"*\" "
                        "(anyone on the internet)"
                    ),
                    evidence=f'"Principal": "*", "Action": {actions}',
                    terraform_resource=resource.address,
                    risk=Risk.CRITICAL,
                    conditional="Condition" in statement,
                )
            )

    return findings


def is_sensitive_bucket(bucket: TerraformResource) -> bool:
    """A bucket is sensitive if its tags say so.

    Supported markers: `Sensitive = "true"` or a `DataClass`/`DataClassification`
    tag set to a known sensitive class (pii, phi, secret, ...).
    """
    return sensitive_tag(bucket) is not None


def sensitive_tag(bucket: TerraformResource) -> Optional[str]:
    """Return the tag that marks this bucket sensitive, as `Key = "value"`."""
    for key, value in bucket.tags().items():
        normalized_key = key.strip().lower()
        normalized_value = str(value).strip().lower()
        if normalized_key in SENSITIVE_TAG_KEYS and normalized_value in ("true", "yes", "1"):
            return f'{key} = "{value}"'
        if "dataclass" in normalized_key and normalized_value in SENSITIVE_DATA_CLASSES:
            return f'{key} = "{value}"'
    return None
