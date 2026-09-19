"""Before/after comparison of two infrastructure graphs.

This is the heart of BlastRadius: not "is this config bad?" but "what did this
change make reachable that was not reachable before?".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Tuple

from blastradius.graph.attack_paths import AnalysisResult
from blastradius.graph.graph_builder import node_of
from blastradius.parser.models import AttackPath, GraphEdge, Risk
from blastradius.security import explain


class Verdict(str, Enum):
    REGRESSION = "SECURITY REGRESSION"
    IMPROVED = "SECURITY IMPROVED"
    UNCHANGED = "NO SECURITY CHANGE"
    INCOMPLETE = "INCOMPLETE ANALYSIS"


@dataclass
class GraphDiff:
    """Structural and reachability delta between two analyses."""

    before: AnalysisResult
    after: AnalysisResult

    new_nodes: List[str] = field(default_factory=list)
    removed_nodes: List[str] = field(default_factory=list)
    new_edges: List[GraphEdge] = field(default_factory=list)
    removed_edges: List[GraphEdge] = field(default_factory=list)

    newly_exposed: List[str] = field(default_factory=list)
    no_longer_exposed: List[str] = field(default_factory=list)
    newly_reachable_sensitive: List[str] = field(default_factory=list)
    no_longer_reachable_sensitive: List[str] = field(default_factory=list)

    new_attack_paths: List[AttackPath] = field(default_factory=list)
    removed_attack_paths: List[AttackPath] = field(default_factory=list)

    verdict: Verdict = Verdict.UNCHANGED
    summary: str = ""

    # --- convenience for the UI -------------------------------------------
    @property
    def complete(self) -> bool:
        return self.before.complete and self.after.complete

    @property
    def new_critical_paths(self) -> List[AttackPath]:
        return [p for p in self.new_attack_paths if p.reaches_sensitive]

    @property
    def removed_critical_paths(self) -> List[AttackPath]:
        return [p for p in self.removed_attack_paths if p.reaches_sensitive]

    @property
    def score_delta(self) -> int:
        return self.after.score - self.before.score

    @property
    def is_regression(self) -> bool:
        return self.verdict is Verdict.REGRESSION

    def metric_rows(self) -> List[Dict[str, object]]:
        """Before/after table rows for the comparison screen."""
        return [
            _row("Risk level", self.before.risk_level.value, self.after.risk_level.value),
            _row("Security score", self.before.score, self.after.score),
            _row("Internet-reachable resources", len(self.before.exposed_resources), len(self.after.exposed_resources)),
            _row("Sensitive resources reachable", len(self.before.reachable_sensitive), len(self.after.reachable_sensitive)),
            _row("Critical attack paths", len(self.before.critical_paths), len(self.after.critical_paths)),
        ]

    def display_path(self, path: AttackPath, source: str = "after") -> List[str]:
        """Human-readable node labels for a path, from whichever graph has it."""
        result = self.after if source == "after" else self.before
        graph = result.graph
        return [
            node_of(graph, n).name if graph.has_node(n) else n
            for n in path.nodes
        ]


def _row(metric: str, before: object, after: object) -> Dict[str, object]:
    return {"metric": metric, "before": before, "after": after, "changed": before != after}


def _edge_key(edge: GraphEdge) -> Tuple[str, str]:
    return edge.source, edge.target


def _edges(result: AnalysisResult) -> Dict[Tuple[str, str], GraphEdge]:
    return {_edge_key(data["edge"]): data["edge"] for _, _, data in result.graph.edges(data=True)}


def _determine_verdict(diff: GraphDiff) -> Verdict:
    """Prioritise sensitive-data reachability, then paths, then score."""
    if diff.newly_reachable_sensitive or diff.new_critical_paths:
        return Verdict.REGRESSION
    if not diff.complete:
        return Verdict.INCOMPLETE
    if diff.no_longer_reachable_sensitive or diff.removed_critical_paths:
        return Verdict.IMPROVED
    if diff.after.score < diff.before.score or diff.new_attack_paths or diff.newly_exposed:
        return Verdict.REGRESSION
    if diff.after.score > diff.before.score or diff.removed_attack_paths or diff.no_longer_exposed:
        return Verdict.IMPROVED
    return Verdict.UNCHANGED


def compare(before: AnalysisResult, after: AnalysisResult) -> GraphDiff:
    """Compute the security diff between a BEFORE and an AFTER analysis."""
    diff = GraphDiff(before=before, after=after)

    before_nodes, after_nodes = set(before.graph.nodes), set(after.graph.nodes)
    diff.new_nodes = sorted(after_nodes - before_nodes)
    diff.removed_nodes = sorted(before_nodes - after_nodes)

    before_edges, after_edges = _edges(before), _edges(after)
    diff.new_edges = [after_edges[k] for k in sorted(set(after_edges) - set(before_edges))]
    diff.removed_edges = [before_edges[k] for k in sorted(set(before_edges) - set(after_edges))]

    before_exposed, after_exposed = set(before.exposed_resources), set(after.exposed_resources)
    diff.newly_exposed = sorted(after_exposed - before_exposed)
    diff.no_longer_exposed = sorted(before_exposed - after_exposed)

    before_sensitive = set(before.reachable_sensitive)
    after_sensitive = set(after.reachable_sensitive)
    diff.newly_reachable_sensitive = sorted(after_sensitive - before_sensitive)
    diff.no_longer_reachable_sensitive = sorted(before_sensitive - after_sensitive)

    before_paths = {p.key: p for p in before.attack_paths}
    after_paths = {p.key: p for p in after.attack_paths}
    diff.new_attack_paths = [after_paths[k] for k in after_paths if k not in before_paths]
    diff.removed_attack_paths = [before_paths[k] for k in before_paths if k not in after_paths]
    diff.new_attack_paths.sort(key=lambda p: (-p.severity.rank, len(p)))
    diff.removed_attack_paths.sort(key=lambda p: (-p.severity.rank, len(p)))

    diff.verdict = _determine_verdict(diff)
    diff.summary = explain.summarize_regression(
        diff.new_attack_paths,
        len(before.reachable_sensitive),
        len(after.reachable_sensitive),
    )
    if not diff.complete:
        diff.summary += " Analysis is incomplete; absent or removed paths do not establish safety."
    return diff


def highlight_nodes(diff: GraphDiff) -> List[str]:
    """Node ids on newly-created critical paths (for graph highlighting)."""
    highlighted: List[str] = []
    for path in diff.new_critical_paths or diff.new_attack_paths:
        for node_id in path.nodes:
            if node_id not in highlighted:
                highlighted.append(node_id)
    return highlighted


def highlight_edges(diff: GraphDiff) -> List[Tuple[str, str]]:
    """Edges on newly-created critical paths (for graph highlighting)."""
    edges: List[Tuple[str, str]] = []
    for path in diff.new_critical_paths or diff.new_attack_paths:
        for edge in path.edges:
            key = _edge_key(edge)
            if key not in edges:
                edges.append(key)
    return edges


def worst_risk(*results: AnalysisResult) -> Risk:
    return Risk.max(*[r.risk_level for r in results]) if results else Risk.LOW
