"""Remediation suggestions and safer-Terraform generation.

Nothing here talks to AWS. We only rewrite local Terraform text and hand back a
patch, so the "generate fix -> re-analyze -> path eliminated" loop is completely
offline and repeatable.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from blastradius.parser.models import INTERNET_ID, NodeType, ParsedConfig, Relationship, Risk
from blastradius.security import hcl_edit, rules

# The CIDR we recommend instead of 0.0.0.0/0 for administrative access.
RECOMMENDED_ADMIN_CIDR = "10.0.0.0/24"


@dataclass
class Recommendation:
    """A single human-readable remediation suggestion."""

    title: str
    detail: str
    current: str
    recommended: str
    severity: Risk = Risk.HIGH
    resource: str = ""


@dataclass
class RemediationPlan:
    """Recommendations plus the rewritten Terraform, if we could generate it."""

    recommendations: List[Recommendation] = field(default_factory=list)
    patched_files: dict[str, str] = field(default_factory=dict)
    diff: str = ""

    @property
    def can_autofix(self) -> bool:
        return bool(self.patched_files)


def recommend(config: ParsedConfig, graph=None) -> List[Recommendation]:
    """Produce remediation recommendations for a parsed configuration."""
    recommendations: List[Recommendation] = []

    for sg in config.of_type("aws_security_group"):
        for finding in rules.public_ingress_findings(sg):
            scope = "administrative access" if finding.is_admin_port else "inbound access"
            recommendations.append(
                Recommendation(
                    title=f"Restrict {finding.port_label} on {sg.address}",
                    detail=(
                        f"The security group grants {scope} from {finding.cidr}, which means "
                        "any host on the internet can attempt to connect. Limit the CIDR to "
                        "your corporate or VPC range, or place the instance behind a bastion "
                        "host / SSM Session Manager."
                    ),
                    current=f'cidr_blocks = ["{finding.cidr}"]',
                    recommended=f'cidr_blocks = ["{RECOMMENDED_ADMIN_CIDR}"]',
                    severity=finding.risk,
                    resource=sg.address,
                )
            )

    for bucket in config.of_type("aws_s3_bucket"):
        for finding in rules.public_bucket_findings(bucket, config.resources):
            sensitive = " It is also tagged as holding sensitive data." if rules.is_sensitive_bucket(bucket) else ""
            recommendations.append(
                Recommendation(
                    title=f"Remove public access from {bucket.address}",
                    detail=(
                        f"{finding.reason}, so its objects can be read by anyone on the "
                        f"internet without credentials.{sensitive} Use a private ACL and serve "
                        "public content through CloudFront with an origin access identity."
                    ),
                    current=finding.evidence,
                    recommended='acl = "private"',
                    severity=Risk.CRITICAL if rules.is_sensitive_bucket(bucket) else finding.risk,
                    resource=finding.terraform_resource,
                )
            )

    for policy in config.of_type("aws_iam_role_policy", "aws_iam_policy"):
        for finding in rules.s3_access_findings(policy.get("policy")):
            if not (finding.targets_all_buckets or finding.has_wildcard_action):
                continue
            recommendations.append(
                Recommendation(
                    title=f"Narrow S3 permissions on {policy.address}",
                    detail=(
                        "The policy grants broad S3 access, so compromising any principal that "
                        "can assume this role exposes every bucket. Scope the statement to the "
                        "specific bucket ARNs and the minimum actions required."
                    ),
                    current=f'"Action": {finding.actions}, "Resource": "*"',
                    recommended='"Action": ["s3:GetObject"], "Resource": ["<specific-bucket-arn>/*"]',
                    severity=finding.risk,
                    resource=policy.address,
                )
            )

    if graph is not None:
        for source, target, data in graph.edges(data=True):
            edge = data["edge"]
            if edge.relationship != Relationship.CONTAINS:
                continue
            if graph.nodes[target]["node"].type != NodeType.SENSITIVE_DATA:
                continue
            if INTERNET_ID in graph and source in _descendants(graph):
                recommendations.append(
                    Recommendation(
                        title=f"Add defence in depth around {graph.nodes[source]['node'].name}",
                        detail=(
                            "This bucket holds data marked sensitive and is reachable from an "
                            "internet-exposed role. Consider a VPC endpoint policy, bucket "
                            "policy conditions (aws:SourceVpce) and server-side encryption with "
                            "a dedicated KMS key."
                        ),
                        current="bucket reachable from internet-exposed IAM role",
                        recommended="restrict bucket policy to a VPC endpoint",
                        severity=Risk.HIGH,
                        resource=source,
                    )
                )

    recommendations.sort(key=lambda r: -r.severity.rank)
    return recommendations


def _descendants(graph) -> set:
    import networkx as nx

    return nx.descendants(graph, INTERNET_ID) if graph.has_node(INTERNET_ID) else set()


def patch_public_admin_cidrs(
    source: str, replacement_cidr: str = RECOMMENDED_ADMIN_CIDR
) -> Tuple[str, int]:
    """Restrict internet-open administrative ingress.

    Only `ingress` blocks reaching port 22/3389 (or all protocols) are rewritten:
    public `egress` is normal, and a deliberately public listener on 443 must not
    be "fixed" into an outage. See `blastradius.security.hcl_edit`.
    """
    return hcl_edit.restrict_admin_ingress(source, replacement_cidr)


# Patchers applied, in order, by `generate_safer_config`.
PATCHERS = (patch_public_admin_cidrs, hcl_edit.make_bucket_acls_private)


def generate_safer_config(source_dir: str | Path) -> RemediationPlan:
    """Build a remediation plan (recommendations + patched Terraform) for a dir."""
    from blastradius.parser.terraform_parser import parse_directory

    directory = Path(source_dir)
    config = parse_directory(directory)
    plan = RemediationPlan(recommendations=recommend(config))

    diff_chunks: List[str] = []
    for tf_file in sorted(directory.glob("*.tf")):
        original = tf_file.read_text(encoding="utf-8")
        patched, count = original, 0
        for patcher in PATCHERS:
            patched, applied = patcher(patched)
            count += applied
        if not count:
            continue
        plan.patched_files[tf_file.name] = patched
        diff_chunks.extend(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                patched.splitlines(keepends=True),
                fromfile=f"a/{tf_file.name}",
                tofile=f"b/{tf_file.name}",
            )
        )

    plan.diff = "".join(diff_chunks)
    return plan


def write_plan(plan: RemediationPlan, target_dir: str | Path, source_dir: str | Path) -> Path:
    """Materialise a remediation plan into `target_dir` and return that path.

    Files without changes are copied verbatim so the output directory is a
    complete, analysable Terraform configuration.
    """
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    for tf_file in sorted(Path(source_dir).glob("*.tf")):
        content = plan.patched_files.get(tf_file.name, tf_file.read_text(encoding="utf-8"))
        (target / tf_file.name).write_text(content, encoding="utf-8")
    return target
