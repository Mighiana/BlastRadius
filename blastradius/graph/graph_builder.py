"""Turn parsed Terraform into a NetworkX attack graph.

The graph is intentionally small:

    INTERNET -> SECURITY_GROUP -> EC2 -> IAM_ROLE -> S3_BUCKET -> SENSITIVE_DATA

Each edge is only added when a rule in `blastradius.security.rules` says the
relationship really exists, and every edge carries the reason it was created so
the UI can explain itself.
"""

from __future__ import annotations

from typing import Dict, List, Optional

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
)
from blastradius.parser.terraform_parser import references
from blastradius.security import rules

# Words that should stay upper-case when we prettify Terraform names for display.
_ACRONYMS = {"sg": "SG", "iam": "IAM", "s3": "S3", "ec2": "EC2", "db": "DB", "ssh": "SSH", "vpc": "VPC"}


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
    graph.add_node(node.id, node=node)


def _add_edge(graph: nx.DiGraph, edge: GraphEdge) -> None:
    """Add an edge, keeping the highest-risk reason when one already exists."""
    if graph.has_edge(edge.source, edge.target):
        existing = edge_of(graph, edge.source, edge.target)
        if existing.risk.rank >= edge.risk.rank:
            return
    graph.add_edge(edge.source, edge.target, edge=edge)


def sensitive_node_id(bucket_address: str) -> str:
    return f"sensitive_data.{bucket_address.split('.', 1)[1]}"


def build_graph(config: ParsedConfig) -> nx.DiGraph:
    """Build the attack graph for one parsed Terraform configuration."""
    graph = nx.DiGraph()
    graph.graph["source_dir"] = config.source_dir
    graph.graph["source_files"] = {r.address: r.source_file for r in config.resources if r.source_file}
    graph.graph["unsupported"] = config.unsupported

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
                        f"({profile_name or 'instance profile'}); credentials are readable "
                        "from instance metadata"
                    ),
                    risk=Risk.MEDIUM,
                    terraform_resource=instance.address,
                    evidence=f"iam_instance_profile = {profile_name}",
                ),
            )

    # --- IAM_ROLE -> S3_BUCKET --------------------------------------------
    bucket_addresses = [b.address for b in buckets]
    for role in roles:
        for policy_address, document in rules.role_policy_sources(role.address, config.resources):
            for finding in rules.s3_access_findings(document):
                targets = (
                    bucket_addresses if finding.targets_all_buckets else finding.bucket_addresses
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
                            reason=finding.reason,
                            risk=finding.risk,
                            terraform_resource=policy_address,
                            evidence=finding.evidence,
                        ),
                    )

    # --- INTERNET -> S3_BUCKET (directly public bucket) -------------------
    for bucket in buckets:
        for finding in rules.public_bucket_findings(bucket, config.resources):
            _add_edge(
                graph,
                GraphEdge(
                    source=INTERNET_ID,
                    target=bucket.address,
                    relationship=Relationship.PUBLIC_ACCESS,
                    reason=finding.reason,
                    risk=finding.risk,
                    terraform_resource=finding.terraform_resource,
                    evidence=finding.evidence,
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
