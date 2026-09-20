"""Turn parsed Terraform into a NetworkX attack graph.

The graph is intentionally small:

    INTERNET -> SECURITY_GROUP -> EC2 -> IAM_ROLE -> S3_BUCKET -> SENSITIVE_DATA

Each edge is only added when a rule in `blastradius.security.rules` says the
relationship really exists, and every edge carries the reason it was created so
the UI can explain itself.
"""

from __future__ import annotations

from typing import Dict, List, Optional
from collections import Counter
from copy import deepcopy

import networkx as nx

from blastradius.parser.models import (
    INTERNET_ID,
    GraphEdge,
    NodeType,
    ParsedConfig,
    Relationship,
    ResourceNode,
    Risk,
    TerraformResource,
    Diagnostic,
)
from blastradius.parser.coverage import config_diagnostics, safe_source
from blastradius.parser.limits import MAX_RESOURCES, InputLimitError, check_structure
from blastradius.parser.terraform_parser import references
from blastradius.security import rules

# Words that should stay upper-case when we prettify Terraform names for display.
_ACRONYMS = {"sg": "SG", "iam": "IAM", "s3": "S3", "ec2": "EC2", "db": "DB", "ssh": "SSH", "vpc": "VPC"}
MAX_GRAPH_EDGES = 20_000


def _display_name(resource: TerraformResource) -> str:
    raw = resource.get("name") or resource.tags().get("Name") or resource.get("bucket") or resource.name
    words = str(raw).replace("-", " ").replace("_", " ").split()
    return " ".join(_ACRONYMS.get(w.lower(), w.capitalize()) for w in words)


def node_of(graph: nx.DiGraph, node_id: str) -> ResourceNode:
    """Return the `ResourceNode` stored on a graph node."""
    return graph.nodes[node_id]["node"]


def edge_of(graph: nx.DiGraph, source: str, target: str) -> GraphEdge:
    """Return the `GraphEdge` stored on a graph edge."""
    return graph.edges[source, target]["edge"]


def nodes_of_type(graph: nx.DiGraph, *types: NodeType) -> List[str]:
    return [n for n, data in graph.nodes(data=True) if data["node"].type in types]


def _add_node(graph: nx.DiGraph, node: ResourceNode) -> None:
    node.attributes = deepcopy(node.attributes)
    graph.add_node(node.id, node=node)


def _add_edge(graph: nx.DiGraph, edge: GraphEdge) -> None:
    """Add an edge, keeping the highest-risk reason when one already exists."""
    if graph.has_edge(edge.source, edge.target):
        existing = edge_of(graph, edge.source, edge.target)
        if existing.risk.rank >= edge.risk.rank:
            return
    elif graph.number_of_edges() >= MAX_GRAPH_EDGES:
        graph.graph["edge_limit_reached"] = True
        return
    graph.add_edge(edge.source, edge.target, edge=edge)


def sensitive_node_id(bucket_address: str) -> str:
    return f"sensitive_data.{bucket_address.split('.', 1)[1]}"


def build_graph(config: ParsedConfig) -> nx.DiGraph:
    """Build the attack graph for one parsed Terraform configuration."""
    graph = nx.DiGraph()
    if len(config.resources) > MAX_RESOURCES:
        raise InputLimitError(f"Graph input exceeds {MAX_RESOURCES} resources")
    check_structure([r.attributes for r in config.resources])
    graph.graph["source_dir"] = safe_source(config.source_dir)
    graph.graph["source_files"] = {r.address: safe_source(r.source_file) for r in config.resources if r.source_file}
    graph.graph["unsupported"] = list(config.unsupported)
    graph.graph["diagnostics"] = config_diagnostics(config)
    counts = Counter(r.address for r in config.resources)
    config = ParsedConfig(resources=[r for r in config.resources if counts[r.address] == 1])

    _add_node(
        graph,
        ResourceNode(id=INTERNET_ID, type=NodeType.INTERNET, name="Internet", risk=Risk.NONE),
    )

    security_groups = config.of_type("aws_security_group")
    instances = config.of_type("aws_instance")
    roles = config.of_type("aws_iam_role")
    profiles = config.of_type("aws_iam_instance_profile")
    buckets = config.of_type("aws_s3_bucket")

    # --- Nodes -------------------------------------------------------------
    for sg in security_groups:
        _add_node(
            graph,
            ResourceNode(
                id=sg.address,
                type=NodeType.SECURITY_GROUP,
                name=_display_name(sg),
                attributes=sg.attributes,
            ),
        )
    for instance in instances:
        _add_node(
            graph,
            ResourceNode(
                id=instance.address,
                type=NodeType.EC2,
                name=_display_name(instance),
                attributes=instance.attributes,
            ),
        )
    for role in roles:
        _add_node(
            graph,
            ResourceNode(
                id=role.address,
                type=NodeType.IAM_ROLE,
                name=_display_name(role),
                attributes=role.attributes,
            ),
        )
    for bucket in buckets:
        sensitive = rules.is_sensitive_bucket(bucket)
        _add_node(
            graph,
            ResourceNode(
                id=bucket.address,
                type=NodeType.S3_BUCKET,
                name=_display_name(bucket),
                attributes=bucket.attributes,
                sensitive=sensitive,
            ),
        )
        if sensitive:
            _add_node(
                graph,
                ResourceNode(
                    id=sensitive_node_id(bucket.address),
                    type=NodeType.SENSITIVE_DATA,
                    name="Sensitive Data",
                    attributes={"bucket": bucket.address},
                    sensitive=True,
                    risk=Risk.HIGH,
                ),
            )

    # --- INTERNET -> SECURITY_GROUP ---------------------------------------
    for sg in security_groups:
        for finding in rules.public_ingress_findings(sg):
            _add_edge(
                graph,
                GraphEdge(
                    source=INTERNET_ID,
                    target=sg.address,
                    relationship=Relationship.INGRESS_ALLOWS,
                    reason=finding.reason,
                    risk=finding.risk,
                    terraform_resource=sg.address,
                    evidence=finding.evidence,
                    metadata={
                        "cidr": finding.cidr,
                        "from_port": finding.from_port,
                        "to_port": finding.to_port,
                        "protocol": finding.protocol,
                        "admin_port": finding.is_admin_port,
                    },
                ),
            )

    # --- SECURITY_GROUP -> EC2 --------------------------------------------
    for instance in instances:
        attached = references(instance.get("vpc_security_group_ids")) + references(
            instance.get("security_groups")
        )
        for sg_address in attached:
            if not graph.has_node(sg_address):
                continue
            _add_edge(
                graph,
                GraphEdge(
                    source=sg_address,
                    target=instance.address,
                    relationship=Relationship.PROTECTS,
                    reason=f"Security group is attached to {_display_name(instance)}",
                    risk=Risk.LOW,
                    terraform_resource=instance.address,
                    evidence=f"vpc_security_group_ids = [{sg_address}.id]",
                ),
            )

        # --- EC2 -> IAM_ROLE ----------------------------------------------
        profile_name = instance.get("iam_instance_profile")
        for role_address in rules.instance_role_addresses(instance, profiles):
            if not graph.has_node(role_address):
                continue
            _add_edge(
                graph,
                GraphEdge(
                    source=instance.address,
                    target=role_address,
                    relationship=Relationship.ASSUMES_ROLE,
                    reason=(
                        "IAM role attached through instance profile "
                        f"({profile_name or 'instance profile'}); compromised compute may "
                        "obtain metadata credentials"
                    ),
                    risk=Risk.MEDIUM,
                    terraform_resource=instance.address,
                    evidence=f"iam_instance_profile = {profile_name}",
                    confidence="conditional",
                ),
            )

    # --- IAM_ROLE -> S3_BUCKET --------------------------------------------
    bucket_addresses = [b.address for b in buckets]
    for role in roles:
        for policy_address, document in rules.role_policy_sources(role.address, config.resources):
            for access in rules.s3_access_findings(document):
                targets = (
                    bucket_addresses if access.targets_all_buckets else [
                        b.address for b in buckets if b.address in access.bucket_addresses
                        or rules.bucket_resource_matches(access.resources, b)
                    ]
                )
                for bucket_address in targets:
                    if not graph.has_node(bucket_address):
                        continue
                    _add_edge(
                        graph,
                        GraphEdge(
                            source=role.address,
                            target=bucket_address,
                            relationship=Relationship.CAN_ACCESS,
                            reason=access.reason,
                            risk=access.risk,
                            terraform_resource=policy_address,
                            evidence=access.evidence,
                            category="data_access" if access.data_read else "privilege",
                            confidence="conditional" if access.conditional else "conservative",
                            metadata={"actions": access.actions, "data_read": access.data_read,
                                      "resources": access.resources},
                        ),
                    )

    # --- INTERNET -> S3_BUCKET (directly public bucket) -------------------
    for bucket in buckets:
        for public_access in rules.public_bucket_findings(bucket, config.resources):
            _add_edge(
                graph,
                GraphEdge(
                    source=INTERNET_ID,
                    target=bucket.address,
                    relationship=Relationship.PUBLIC_ACCESS,
                    reason=public_access.reason,
                    risk=public_access.risk,
                    terraform_resource=public_access.terraform_resource,
                    evidence=public_access.evidence,
                    confidence="conditional" if public_access.conditional else "modeled",
                ),
            )

    # --- S3_BUCKET -> SENSITIVE_DATA --------------------------------------
    for bucket in buckets:
        if not rules.is_sensitive_bucket(bucket):
            continue
        _add_edge(
            graph,
            GraphEdge(
                source=bucket.address,
                target=sensitive_node_id(bucket.address),
                relationship=Relationship.CONTAINS,
                reason="Bucket is tagged as holding sensitive data",
                risk=Risk.HIGH,
                terraform_resource=bucket.address,
                evidence=f"tags = {{ {rules.sensitive_tag(bucket)} }}",
            ),
        )

    categories = {
        Relationship.INGRESS_ALLOWS: "exposure", Relationship.PROTECTS: "reachability",
        Relationship.ASSUMES_ROLE: "privilege", Relationship.PUBLIC_ACCESS: "exposure",
        Relationship.CONTAINS: "impact",
    }
    remediation = {
        Relationship.INGRESS_ALLOWS: "Restrict ingress to intended CIDRs and ports.",
        Relationship.PROTECTS: "Review the instance security-group attachment and network routes.",
        Relationship.ASSUMES_ROLE: "Use least-privilege instance roles and protect metadata credentials.",
        Relationship.CAN_ACCESS: "Narrow IAM actions and bucket ARNs; verify effective policies.",
        Relationship.PUBLIC_ACCESS: "Remove public ACL/policy grants or apply effective public access controls.",
        Relationship.CONTAINS: "Verify sensitivity classification and restrict access to this bucket.",
    }
    for edge in graph_edges(graph):
        edge.category = categories.get(edge.relationship, edge.category)
        edge.source_file = graph.graph["source_files"].get(edge.terraform_resource, "")
        edge.remediation = remediation[edge.relationship]
    if graph.graph.get("edge_limit_reached"):
        graph.graph["diagnostics"].append(Diagnostic("GRAPH_TRUNCATED", f"Graph exceeded {MAX_GRAPH_EDGES} edges."))
    return graph


def graph_edges(graph: nx.DiGraph) -> List[GraphEdge]:
    return [data["edge"] for _, _, data in graph.edges(data=True)]


def node_summary(graph: nx.DiGraph) -> Dict[str, ResourceNode]:
    return {n: data["node"] for n, data in graph.nodes(data=True)}


def find_instance_for_role(graph: nx.DiGraph, role_id: str) -> Optional[str]:
    """First EC2 node that can assume `role_id` (used by explanations)."""
    return next(
        (
            predecessor
            for predecessor in graph.predecessors(role_id)
            if node_of(graph, predecessor).type == NodeType.EC2
        ),
        None,
    )
