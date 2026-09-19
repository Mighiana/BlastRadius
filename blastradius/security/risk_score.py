"""Deterministic 0-100 BlastRadius security score.

This is a transparent heuristic, NOT a scientifically validated risk metric. Its
only job is to give the demo a single comparable number. The rules:

    Start at 100, then subtract (each category is capped):

    | Finding                                        | Penalty | Cap |
    |------------------------------------------------|---------|-----|
    | Administrative port (22/3389) open to 0.0.0.0/0|   -20   | -40 |
    | S3 bucket readable directly from the internet  |   -20   | -40 |
    | Compute instance reachable from the internet   |   -15   | -30 |
    | Broad IAM data permission (s3:* or Resource *) |   -10   | -20 |
    | Sensitive resource reachable from the internet |   -25   | -25 |
    | Complete internet -> sensitive-data path       |   -20   | -20 |

    The score is clamped to [0, 100]. Identical input always gives the same
    score, which is what makes the before/after comparison trustworthy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Tuple

from blastradius.parser.models import INTERNET_ID, NodeType, Relationship, Risk

if TYPE_CHECKING:  # pragma: no cover
    from blastradius.graph.attack_paths import AnalysisResult

PENALTIES = {
    "admin_port": (20, 40, "Administrative port open to 0.0.0.0/0"),
    "public_bucket": (20, 40, "Storage bucket readable directly from the internet"),
    "public_compute": (15, 30, "Compute instance reachable from the internet"),
    "broad_iam": (10, 20, "Broad IAM permission to data storage"),
    "sensitive_exposed": (25, 25, "Sensitive resource reachable from the internet"),
    "full_path": (20, 20, "Complete internet -> sensitive-data attack path"),
}

SCORE_BANDS = ((85, Risk.LOW), (65, Risk.MEDIUM), (40, Risk.HIGH))


def _count_findings(result: "AnalysisResult") -> Dict[str, int]:
    from blastradius.graph.graph_builder import node_of

    graph = result.graph
    counts = {key: 0 for key in PENALTIES}

    for source, target, data in graph.edges(data=True):
        edge = data["edge"]
        if (
            source == INTERNET_ID
            and edge.relationship == Relationship.INGRESS_ALLOWS
            and edge.risk == Risk.CRITICAL
        ):
            counts["admin_port"] += 1
        if edge.relationship == Relationship.CAN_ACCESS and edge.risk.rank >= Risk.HIGH.rank:
            counts["broad_iam"] += 1
        if source == INTERNET_ID and edge.relationship == Relationship.PUBLIC_ACCESS:
            counts["public_bucket"] += 1

    counts["public_compute"] = sum(
        1 for n in result.exposed_resources if node_of(graph, n).type == NodeType.EC2
    )
    counts["sensitive_exposed"] = len(result.reachable_sensitive)
    counts["full_path"] = 1 if result.critical_paths else 0
    return counts


def score_analysis(result: "AnalysisResult") -> Tuple[int, List[Dict[str, object]]]:
    """Return `(score, breakdown)` for an analysis result."""
    counts = _count_findings(result)
    score = 100
    breakdown: List[Dict[str, object]] = []

    for key, (penalty, cap, label) in PENALTIES.items():
        count = counts[key]
        if not count:
            continue
        deducted = min(penalty * count, cap)
        score -= deducted
        breakdown.append({"finding": label, "count": count, "points": -deducted})

    return max(0, min(100, score)), breakdown


def score_band(score: int) -> Risk:
    """Map a score to a coarse risk band (used only for display)."""
    for threshold, risk in SCORE_BANDS:
        if score >= threshold:
            return risk
    return Risk.CRITICAL
