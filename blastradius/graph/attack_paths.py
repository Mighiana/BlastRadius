"""Attack-path detection over the infrastructure graph.

Reachability question: starting at the INTERNET node, which resources can be
reached, and does any route terminate at data marked sensitive?
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List
from collections import deque

import networkx as nx

from blastradius.graph.graph_builder import edge_of, node_of, nodes_of_type
from blastradius.parser.models import (
    INTERNET_ID,
    AttackPath,
    GraphEdge,
    NodeType,
    ResourceNode,
    Risk,
    Diagnostic,
)
from blastradius.security import explain
from blastradius.security.risk_score import score_analysis
from blastradius.parser.limits import InputLimitError

# Node types counted as "resources" in the exposure metrics. Security groups are
# controls rather than assets, and SENSITIVE_DATA is a marker, so both are
# excluded to keep the headline numbers intuitive.
RESOURCE_TYPES = (NodeType.EC2, NodeType.IAM_ROLE, NodeType.S3_BUCKET)

# Safety valve so a pathological config cannot hang the UI.
MAX_PATHS_PER_TARGET = 25
MAX_PATHS = 500
MAX_PATH_DEPTH = 32
MAX_PATH_WORK = 100_000


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
    diagnostics: list[Diagnostic] = field(default_factory=list)
    paths_truncated: bool = False
    path_work: int = 0

    @property
    def complete(self) -> bool:
        return not self.paths_truncated and not any(d.blocks_analysis for d in self.diagnostics)

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
        explanation=explain.RuleBasedExplainer().explain_path(resource_nodes, edges),
        reaches_sensitive=reaches_sensitive,
    )


def _determine_risk_level(result: AnalysisResult) -> Risk:
    if result.critical_paths or result.reachable_sensitive:
        return Risk.CRITICAL
    if result.attack_paths:
        worst = Risk.max(*[p.severity for p in result.attack_paths])
        return Risk.HIGH if worst.rank >= Risk.HIGH.rank else Risk.MEDIUM
    if result.exposed_resources:
        return Risk.MEDIUM
    return Risk.LOW


def analyze(graph: nx.DiGraph, label: str = "") -> AnalysisResult:
    """Run full reachability + attack-path analysis on a graph."""
    if len(graph) > 2500 or graph.number_of_edges() > 20_000:
        raise InputLimitError("Analysis graph exceeds node or edge budget")
    result = AnalysisResult(graph=graph, label=label,
                            diagnostics=list(graph.graph.get("diagnostics", [])))

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

    paths: List[AttackPath] = []
    targets = sorted(set(sensitive_markers) & set(reachable))
    if not targets:
        targets = sorted(n for n in result.exposed_resources if node_of(graph, n).type == NodeType.EC2)
    adjacency = {n: sorted(graph.successors(n)) for n in graph}
    parent = {INTERNET_ID: INTERNET_ID}
    queue = deque([INTERNET_ID])
    while queue:
        current = queue.popleft()
        for neighbor in adjacency[current]:
            if neighbor not in parent:
                parent[neighbor] = current
                queue.append(neighbor)
    for target in targets:
        witness = [target]
        while witness[-1] != INTERNET_ID and len(witness) <= MAX_PATH_DEPTH:
            witness.append(parent[witness[-1]])
        if witness[-1] != INTERNET_ID:
            result.paths_truncated = True
            continue
        witness.reverse()
        if len(paths) >= MAX_PATHS or result.path_work >= MAX_PATH_WORK:
            result.paths_truncated = True
            break
        paths.append(_build_attack_path(graph, witness))
        emitted = {tuple(witness)}
        stack = [(INTERNET_ID, iter(adjacency[INTERNET_ID]))]
        route = [INTERNET_ID]
        visited = {INTERNET_ID}
        while stack:
            if result.path_work >= MAX_PATH_WORK or len(paths) >= MAX_PATHS:
                result.paths_truncated = True
                break
            neighbor = next(stack[-1][1], None)
            result.path_work += 1
            if neighbor is None:
                stack.pop()
                visited.remove(route.pop())
                continue
            if neighbor in visited:
                continue
            if neighbor == target:
                key = tuple([*route, target])
                if key not in emitted:
                    emitted.add(key)
                    paths.append(_build_attack_path(graph, list(key)))
                if len(emitted) >= MAX_PATHS_PER_TARGET:
                    result.paths_truncated = True
                    break
            elif len(route) >= MAX_PATH_DEPTH:
                result.paths_truncated = True
            else:
                route.append(neighbor)
                visited.add(neighbor)
                stack.append((neighbor, iter(adjacency[neighbor])))
    if result.paths_truncated:
        result.diagnostics.append(Diagnostic("PATHS_TRUNCATED",
            "Path enumeration reached a work, depth or output budget; path counts are lower bounds."))

    paths.sort(key=lambda p: (-p.severity.rank, len(p), p.key))
    result.attack_paths = paths
    result.risk_level = _determine_risk_level(result)
    result.score, result.score_breakdown = score_analysis(result)
    return result
