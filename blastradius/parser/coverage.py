"""Coverage validation for normalized resources; never evaluates Terraform."""

from collections import Counter
from pathlib import PurePosixPath
from ipaddress import ip_network
import re

from blastradius.parser.models import Diagnostic, ParsedConfig, TerraformResource
from blastradius.parser.values import as_list, parse_policy_document, references

SECURITY_ATTRIBUTES = {
    "aws_security_group": ("ingress",),
    "aws_instance": ("vpc_security_group_ids", "security_groups", "iam_instance_profile"),
    "aws_iam_role": ("permissions_boundary", "inline_policy", "managed_policy_arns"),
    "aws_iam_instance_profile": ("role",),
    "aws_iam_role_policy": ("role", "policy"),
    "aws_iam_policy": ("policy",),
    "aws_iam_role_policy_attachment": ("role", "policy_arn"),
    "aws_s3_bucket": ("bucket", "arn", "acl", "tags", "policy", "grant"),
    "aws_s3_bucket_acl": ("bucket", "acl", "access_control_policy"),
    "aws_s3_bucket_policy": ("bucket", "policy"),
    "aws_s3_bucket_public_access_block": (
        "bucket", "block_public_acls", "ignore_public_acls",
        "block_public_policy", "restrict_public_buckets",
    ),
}
_REFERENCE = re.compile(r"aws_[a-z0-9_]+\.[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?")
_EXPRESSION = re.compile(r"\$\{|(?:var|local|module|data|each|count)\.|\b\w+\s*\(")
_NON_SECURITY_TYPES = frozenset({"aws_cloudwatch_log_group"})
_LINK_ATTRIBUTES = {
    "aws_instance": ("vpc_security_group_ids", "security_groups", "iam_instance_profile"),
    "aws_iam_instance_profile": ("role",),
    "aws_iam_role_policy": ("role",),
    "aws_iam_role_policy_attachment": ("role", "policy_arn"),
    "aws_s3_bucket_acl": ("bucket",),
    "aws_s3_bucket_policy": ("bucket",),
    "aws_s3_bucket_public_access_block": ("bucket",),
}


def safe_source(source: str | None) -> str:
    if not source:
        return ""
    path = PurePosixPath(source.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or re.match(r"^[A-Za-z]:", str(path)):
        return path.name
    return path.as_posix()


def diagnostic(resource: TerraformResource, code: str, message: str, attribute: str = "") -> Diagnostic:
    return Diagnostic(code, message, resource=resource.address, attribute=attribute,
                      source_file=safe_source(resource.source_file))


def _strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _string_list(value: object) -> bool:
    return isinstance(value, str) and bool(value) or (
        isinstance(value, list) and bool(value)
        and all(isinstance(item, str) and bool(item) for item in value)
    )


def policy_diagnostics(resource: TerraformResource, raw: object, attribute: str = "policy") -> list[Diagnostic]:
    policy = parse_policy_document(raw)
    findings = []
    if not policy or not isinstance(policy.get("Statement"), (dict, list)):
        return [diagnostic(resource, "INVALID_POLICY", "Policy is not a JSON object with statements.", attribute)]
    statements = as_list(policy["Statement"])
    if not statements:
        return [diagnostic(resource, "INVALID_POLICY", "Policy contains no statements.", attribute)]
    for statement in statements:
        if not isinstance(statement, dict):
            findings.append(diagnostic(resource, "INVALID_POLICY", "Policy statement must be an object.", attribute))
            continue
        if (statement.get("Effect") not in ("Allow", "Deny")
                or not _string_list(statement.get("Action"))
                or not _string_list(statement.get("Resource"))):
            findings.append(diagnostic(resource, "INVALID_POLICY", "Policy requires Effect, Action and Resource.", attribute))
        for construct in ("Condition", "NotAction", "NotResource", "NotPrincipal"):
            if construct in statement:
                findings.append(diagnostic(resource, "UNSUPPORTED_IAM_SEMANTICS",
                    f"{construct} is not evaluated; grants are possible permissions only.", attribute))
        if statement.get("Effect") == "Deny":
            findings.append(diagnostic(resource, "IAM_DENY_NOT_EVALUATED",
                "Explicit deny precedence is not evaluated; allow edges are conservative.", attribute))
        if resource.type == "aws_s3_bucket_policy":
            principal = statement.get("Principal")
            valid = isinstance(principal, str) and bool(principal) or (
                isinstance(principal, dict) and bool(principal)
                and all(key in ("AWS", "Service", "Federated", "CanonicalUser") and _string_list(value)
                        for key, value in principal.items())
            )
            if not valid:
                findings.append(diagnostic(resource, "INVALID_PRINCIPAL", "Bucket policy has an invalid or absent Principal.", attribute))
        for name in ("Action", "Resource", "Principal"):
            for text in _strings(statement.get(name)):
                without_refs = re.sub(r"\$\{aws_[a-z0-9_]+\.[A-Za-z_][A-Za-z0-9_-]*\.arn\}", "", text)
                if _EXPRESSION.search(without_refs):
                    findings.append(diagnostic(resource, "UNRESOLVED_EXPRESSION",
                        "Policy expression is not resolved.", attribute))
        if resource.type == "aws_s3_bucket_policy":
            for text in _strings(statement.get("Principal")):
                if text != "*" and ("*" in text or "?" in text):
                    findings.append(diagnostic(resource, "INVALID_PRINCIPAL",
                        "Partial wildcard principals are not modeled as anonymous access.", attribute))
    return findings


def config_diagnostics(config: ParsedConfig) -> list[Diagnostic]:
    findings = list(config.diagnostics)
    addresses = Counter(r.address for r in config.resources)
    for unsupported in config.unsupported:
        findings.append(Diagnostic("UNSUPPORTED_RESOURCE", f"Outside modeled coverage: {unsupported}",
                                   blocks_analysis=unsupported not in _NON_SECURITY_TYPES))
    for resource in config.resources:
        if addresses[resource.address] > 1:
            findings.append(diagnostic(resource, "DUPLICATE_ADDRESS", "Duplicate resource address; relationships are ambiguous."))
        if resource.type in ("aws_iam_policy", "aws_iam_role_policy", "aws_s3_bucket_policy") and "policy" not in resource.attributes:
            findings.append(diagnostic(resource, "INVALID_POLICY", "Required policy document is absent.", "policy"))
        for name in ("count", "for_each", "dynamic"):
            if name in resource.attributes:
                findings.append(diagnostic(resource, "UNEXPANDED_RESOURCE", f"{name} is not expanded.", name))
        for name in SECURITY_ATTRIBUTES.get(resource.type, ()):
            if name not in resource.attributes:
                continue
            value = resource.attributes[name]
            if name == "policy":
                findings.extend(policy_diagnostics(resource, value))
            elif any(_EXPRESSION.search(text) and not _REFERENCE.fullmatch(text) for text in _strings(value)):
                findings.append(diagnostic(resource, "UNRESOLVED_EXPRESSION", "Security-relevant expression is not resolved.", name))
            elif value is None:
                findings.append(diagnostic(resource, "UNKNOWN_VALUE", "Security-relevant value is null or unknown.", name))
            for ref in references(value):
                if ref not in addresses:
                    findings.append(diagnostic(resource, "UNRESOLVED_REFERENCE", "Referenced resource is absent from the model.", name))
        for name in ("permissions_boundary", "inline_policy", "managed_policy_arns", "grant", "access_control_policy"):
            if resource.get(name):
                findings.append(diagnostic(resource, "UNSUPPORTED_CONTROL", f"{name} is not evaluated.", name))
        if resource.type == "aws_s3_bucket" and resource.get("policy"):
            findings.append(diagnostic(resource, "UNSUPPORTED_CONTROL",
                "Inline bucket policy is not modeled; use aws_s3_bucket_policy.", "policy"))
        for name in _LINK_ATTRIBUTES.get(resource.type, ()):
            value = resource.get(name)
            optional = resource.type == "aws_instance"
            if (value or not optional) and (
                not references(value) or any(not references(v) for v in as_list(value))
            ):
                findings.append(diagnostic(resource, "UNRESOLVED_RELATIONSHIP",
                    "Relationship needs a modeled resource reference or resolved plan identity.", name))
        if resource.type == "aws_s3_bucket_public_access_block":
            linked = references(resource.get("bucket"))
            if any(other.address != resource.address and other.type == resource.type
                   and set(linked) & set(references(other.get("bucket"))) for other in config.resources):
                findings.append(diagnostic(resource, "AMBIGUOUS_CONTROL",
                    "Multiple public access blocks target the same bucket; suppression is disabled."))
        if resource.type == "aws_iam_role_policy_attachment" and not references(resource.get("policy_arn")):
            findings.append(diagnostic(resource, "EXTERNAL_POLICY", "Attached policy content is unavailable.", "policy_arn"))
        if resource.type in ("aws_s3_bucket", "aws_s3_bucket_acl") and resource.get("acl") == "authenticated-read":
            findings.append(diagnostic(resource, "AUTHENTICATED_S3_ACL",
                "ACL grants AWS authenticated users access; this is not anonymous internet access.", "acl"))
        if resource.type in ("aws_s3_bucket", "aws_s3_bucket_acl") and "acl" in resource.attributes:
            acl = resource.get("acl")
            if not isinstance(acl, str) or acl not in (
                "private", "public-read", "public-read-write", "authenticated-read",
                "aws-exec-read", "bucket-owner-read", "bucket-owner-full-control", "log-delivery-write",
            ):
                findings.append(diagnostic(resource, "INVALID_ACL", "ACL is invalid or unresolved.", "acl"))
        if resource.type == "aws_s3_bucket_public_access_block":
            for name in SECURITY_ATTRIBUTES[resource.type][1:]:
                if name in resource.attributes and not isinstance(resource.get(name), bool):
                    findings.append(diagnostic(resource, "INVALID_CONTROL", "Public access block flag must be a known boolean.", name))
        if resource.type == "aws_security_group":
            for ingress in as_list(resource.get("ingress")):
                if not isinstance(ingress, dict):
                    findings.append(diagnostic(resource, "INVALID_INGRESS", "Ingress must be a rule object.", "ingress"))
                    continue
                protocol = ingress.get("protocol")
                if protocol not in ("tcp", "udp", "icmp", "icmpv6", "-1", "all", "6", "17", "1", "58", -1, 6, 17, 1, 58):
                    findings.append(diagnostic(resource, "INVALID_INGRESS", "Ingress protocol is missing or unsupported.", "ingress"))
                if str(protocol) not in ("-1", "all") and any(
                    not isinstance(ingress.get(port), int) or isinstance(ingress.get(port), bool)
                    for port in ("from_port", "to_port")
                ):
                    findings.append(diagnostic(resource, "INVALID_INGRESS", "Ingress ports must be known integers.", "ingress"))
                for name in ("cidr_blocks", "ipv6_cidr_blocks"):
                    for cidr in as_list(ingress.get(name)):
                        try:
                            if not isinstance(cidr, str):
                                raise ValueError
                            ip_network(cidr)
                        except ValueError:
                            findings.append(diagnostic(resource, "INVALID_INGRESS", "Ingress CIDR is invalid or unresolved.", name))
                if ingress.get("security_groups") or ingress.get("self"):
                    findings.append(diagnostic(resource, "UNMODELED_SG_HOP", "Security-group-to-security-group traffic is not modeled.", "ingress"))
    return sorted(set(findings), key=lambda d: (d.code, d.resource, d.attribute, d.source_file, d.message))
