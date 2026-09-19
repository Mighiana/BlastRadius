"""Attack-path explanations.

The MVP explainer is deterministic and rule-based, which is exactly what a live
demo needs. It is written behind a tiny provider interface so an LLM-backed
explainer can be dropped in later without touching the analysis code:

    from blastradius.security import explain
    explain.set_provider(MyLLMExplainer())
"""

from __future__ import annotations

from typing import List, Protocol, Sequence

from blastradius.parser.models import GraphEdge, NodeType, Relationship, ResourceNode, Risk


class ExplanationProvider(Protocol):
    """Anything that can turn an attack path into prose."""

    def explain_path(
        self, nodes: Sequence[ResourceNode], edges: Sequence[GraphEdge]
    ) -> str:  # pragma: no cover - interface
        ...


class RuleBasedExplainer:
    """Deterministic, template-driven explanations."""

    def explain_path(self, nodes: Sequence[ResourceNode], edges: Sequence[GraphEdge]) -> str:
        if not nodes:
            return ""

        entry = self._entry_sentence(nodes, edges)
        pivots = self._pivot_sentences(nodes, edges)
        impact = self._impact_sentence(nodes)
        return " ".join(part for part in [entry, *pivots, impact] if part)

    def _entry_sentence(
        self, nodes: Sequence[ResourceNode], edges: Sequence[GraphEdge]
    ) -> str:
        compute = next((n for n in nodes if n.type == NodeType.EC2), None)
        ingress = next((e for e in edges if e.relationship == Relationship.INGRESS_ALLOWS), None)
        if compute is None or ingress is None:
            return ""
        return (
            f"{compute.name} is reachable from the public internet because its "
            f"security group permits inbound traffic from the whole internet "
            f"({ingress.reason.split('allows ')[-1]})."
        )

    def _pivot_sentences(
        self, nodes: Sequence[ResourceNode], edges: Sequence[GraphEdge]
    ) -> List[str]:
        sentences: List[str] = []
        role = next((n for n in nodes if n.type == NodeType.IAM_ROLE), None)
        bucket = next((n for n in nodes if n.type == NodeType.S3_BUCKET), None)
        compute = next((n for n in nodes if n.type == NodeType.EC2), None)

        if role is not None and compute is not None:
            sentences.append(
                f"An attacker who compromises {compute.name} can read the instance "
                f"metadata service and obtain credentials for {role.name}."
            )
        if role is not None and bucket is not None:
            access = next((e for e in edges if e.relationship == Relationship.CAN_ACCESS), None)
            detail = f" ({access.reason.lower()})" if access else ""
            sentences.append(
                f"Those credentials grant access to {bucket.name}{detail}."
            )
        return sentences

    def _impact_sentence(self, nodes: Sequence[ResourceNode]) -> str:
        if not any(n.type == NodeType.SENSITIVE_DATA for n in nodes):
            return "No resource on this path is marked as holding sensitive data."
        bucket = next((n for n in nodes if n.type == NodeType.S3_BUCKET), None)
        target = bucket.name if bucket else "the target bucket"
        return (
            f"{target} is tagged as sensitive, so this is a complete path from the "
            "internet to sensitive cloud data."
        )


_provider: ExplanationProvider = RuleBasedExplainer()


def set_provider(provider: ExplanationProvider) -> None:
    """Swap in a different explanation backend (e.g. an LLM agent)."""
    global _provider
    _provider = provider


def get_provider() -> ExplanationProvider:
    return _provider


def explain_path(nodes: Sequence[ResourceNode], edges: Sequence[GraphEdge]) -> str:
    return _provider.explain_path(nodes, edges)


def summarize_regression(
    new_paths: Sequence["object"],
    before_sensitive: int,
    after_sensitive: int,
) -> str:
    """One-paragraph summary of what a change did to the blast radius."""
    if after_sensitive > before_sensitive:
        return (
            "This change increased the blast radius: infrastructure that was previously "
            "unreachable from the internet can now be reached, and the path terminates at "
            "data marked sensitive. Review the highlighted path before deploying."
        )
    if after_sensitive < before_sensitive:
        return (
            "This change reduced the blast radius: sensitive data that was previously "
            "reachable from the internet is no longer reachable through the modelled paths."
        )
    if new_paths:
        return (
            "This change introduced new internet-facing exposure, but no path reaches a "
            "resource marked sensitive."
        )
    return "This change did not alter the modelled internet-to-sensitive-data reachability."


def path_severity(edges: Sequence[GraphEdge], reaches_sensitive: bool) -> Risk:
    """Severity of a path: the worst edge, escalated if it ends in sensitive data."""
    worst = Risk.max(*[e.risk for e in edges]) if edges else Risk.NONE
    if reaches_sensitive:
        return Risk.CRITICAL
    return worst
