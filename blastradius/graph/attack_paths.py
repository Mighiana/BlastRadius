"""Attack-path detection over the infrastructure graph.

Reachability question: starting at the INTERNET node, which resources can be
reached, and does any route terminate at data marked sensitive?
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

import networkx as nx

from blastradius.graph.graph_builder import edge_of, node_of, nodes_of_type
from blastradius.parser.models import (
    INTERNET_ID,
    AttackPath,
    GraphEdge,
    NodeType,
    ResourceNode,
    Risk,
)
from blastradius.security import explain

# Node types counted as "resources" in the exposure metrics. Security groups are
# controls rather than assets, and SENSITIVE_DATA is a marker, so both are
# excluded to keep the headline numbers intuitive.
RESOURCE_TYPES = (NodeType.EC2, NodeType.IAM_ROLE, NodeType.S3_BUCKET)

# Safety valve so a pathological config cannot hang the UI.
MAX_PATHS_PER_TARGET = 25


@dataclass
class AnalysisResult:
    """Everything the UI needs about a single configuration."""

    graph: nx.DiGraph
    reachable: List[str] = field(default_factory=list)
    exposed_resources: List[str] = field(default_factory=list)
    reachable_sensitive: List[str] = field(default_factory=list)
    sensitive_resources: List[str] = field(default_factory=list)
    attack_paths: List[AttackPath] = field(default_factory=list)
    risk_level: Risk = Risk.LOW
    score: int = 100
    score_breakdown: List[Dict[str, object]] = field(default_factory=list)
    label: str = ""

    @property
    def critical_paths(self) -> List[AttackPath]:
        """Paths that start on the internet and end at sensitive data."""
        return [p for p in self.attack_paths if p.reaches_sensitive]

    @property
    def shortest_critical_path(self) -> AttackPath | None:
        critical = self.critical_paths
        return min(critical, key=len) if critical else None

    @property
    def path_keys(self) -> List[str]:
        return [p.key for p in self.attack_paths]

    def node(self, node_id: str) -> ResourceNode:
        return node_of(self.graph, node_id)

    def display_path(self, path: AttackPath) -> List[str]:
        return [self.node(n).name for n in path.nodes]


def _path_edges(graph: nx.DiGraph, nodes: List[str]) -> List[GraphEdge]:
    return [edge_of(graph, a, b) for a, b in zip(nodes, nodes[1:])]


def _build_attack_path(graph: nx.DiGraph, node_ids: List[str]) -> AttackPath:
    edges = _path_edges(graph, node_ids)
    resource_nodes = [node_of(graph, n) for n in node_ids]
    reaches_sensitive = any(n.type == NodeType.SENSITIVE_DATA for n in resource_nodes)
    return AttackPath(
        nodes=node_ids,
        edges=edges,
        severity=explain.path_severity(edges, reaches_sensitive),
        explanation=explain.explain_path(resource_nodes, edges),
        reaches_sensitive=reaches_sensitive,
    )


def _determine_risk_level(result: AnalysisResult) -> Risk:
    if result.critical_paths:
        return Risk.CRITICAL
    if result.attack_paths:
        worst = Risk.max(*[p.severity for p in result.attack_paths])
        return Risk.HIGH if worst.rank >= Risk.HIGH.rank else Risk.MEDIUM
    if result.exposed_resources:
        return Risk.MEDIUM
    return Risk.LOW


def analyze(graph: nx.DiGraph, label: str = "") -> AnalysisResult:
    """Run full reachability + attack-path analysis on a graph."""
    from blastradius.security.risk_score import score_analysis  # local: avoids a cycle

    result = AnalysisResult(graph=graph, label=label)

    if not graph.has_node(INTERNET_ID):
        return result

    reachable = sorted(nx.descendants(graph, INTERNET_ID))
    result.reachable = reachable
    result.exposed_resources = [n for n in reachable if node_of(graph, n).type in RESOURCE_TYPES]

    sensitive_markers = nodes_of_type(graph, NodeType.SENSITIVE_DATA)
    result.sensitive_resources = sorted(
        n for n in graph.nodes if node_of(graph, n).sensitive and node_of(graph, n).type != NodeType.SENSITIVE_DATA
    )
    result.reachable_sensitive = [n for n in result.sensitive_resources if n in reachable]

    # Enumerate every route from the internet to each sensitive-data marker.
    paths: List[AttackPath] = []
    for target in sorted(sensitive_markers):
        if target not in reachable:
            continue
        for count, node_ids in enumerate(nx.all_simple_paths(graph, INTERNET_ID, target)):
            if count >= MAX_PATHS_PER_TARGET:
                break
            paths.append(_build_attack_path(graph, node_ids))

    # If nothing sensitive is reachable, still surface internet-exposed compute
    # so the "safe" configuration is not just an empty screen.
    if not paths:
        for target in sorted(n for n in result.exposed_resources if node_of(graph, n).type == NodeType.EC2):
            for count, node_ids in enumerate(nx.all_simple_paths(graph, INTERNET_ID, target)):
                if count >= MAX_PATHS_PER_TARGET:
                    break
                paths.append(_build_attack_path(graph, node_ids))

    paths.sort(key=lambda p: (-p.severity.rank, len(p), p.key))
    result.attack_paths = paths
    result.risk_level = _determine_risk_level(result)
    result.score, result.score_breakdown = score_analysis(result)
    return result
