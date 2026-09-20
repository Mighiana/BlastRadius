"""Merge/deployment gate decision.

BlastRadius is meant to sit in front of a pull request, so the analysis has to
end in an unambiguous answer: can this change be merged?

The rules are deliberately simple, ordered, and fully explainable - every
decision is accompanied by the four counts that produced it.

    BLOCK CHANGE    a new critical path (internet -> sensitive data) appeared,
                    or a sensitive resource became internet-reachable
    REVIEW REQUIRED no new critical path, but the change increased exposure
                    (new internet-reachable resources, new non-critical paths,
                    or a lower security score)
    SAFE TO MERGE   the change added no new exposure (it may have removed some)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, List, Optional

from blastradius.parser.models import Risk, NodeType, TerraformResource
from blastradius.policy import Policy
from blastradius.security.rules import public_ingress_findings

if TYPE_CHECKING:  # pragma: no cover
    from blastradius.graph.diff_engine import GraphDiff


class Decision(str, Enum):
    BLOCK = "BLOCK CHANGE"
    REVIEW = "REVIEW REQUIRED"
    SAFE = "SAFE TO MERGE"

    @property
    def icon(self) -> str:
        return {"BLOCK CHANGE": "\U0001f6ab", "REVIEW REQUIRED": "\u26a0", "SAFE TO MERGE": "\u2705"}[
            self.value
        ]

    @property
    def color(self) -> str:
        return {
            "BLOCK CHANGE": "#ef4444",
            "REVIEW REQUIRED": "#f59e0b",
            "SAFE TO MERGE": "#10b981",
        }[self.value]

    @property
    def passed(self) -> bool:
        """True when the change does not introduce a critical regression."""
        return self is not Decision.BLOCK

    @property
    def exit_code(self) -> int:
        """Process exit code for CI use: 1 only for a blocking regression."""
        return 1 if self is Decision.BLOCK else 0


@dataclass
class DecisionReason:
    """One explainable input to the decision."""

    label: str
    detail: str
    severity: Risk = Risk.NONE
    delta: int = 0

    @property
    def is_negative(self) -> bool:
        return self.delta > 0 and self.severity.rank >= Risk.MEDIUM.rank


@dataclass
class DeploymentDecision:
    decision: Decision
    headline: str
    reasons: List[DecisionReason] = field(default_factory=list)
    # Policy-specific notes (threshold breaches, gates that were disabled).
    # Kept separate from `reasons` so the four core counts are always the same.
    policy_notes: List[str] = field(default_factory=list)
    policy: Optional["Policy"] = None

    @property
    def icon(self) -> str:
        return self.decision.icon

    @property
    def color(self) -> str:
        return self.decision.color

    @property
    def passed(self) -> bool:
        return self.decision.passed

    @property
    def exit_code(self) -> int:
        return self.decision.exit_code

    @property
    def blocking_reasons(self) -> List[DecisionReason]:
        return [r for r in self.reasons if r.delta > 0 and r.severity is Risk.CRITICAL]


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


def _score_reason(delta: int) -> DecisionReason:
    if delta < 0:
        return DecisionReason(
            label="Security score delta",
            detail=f"Score dropped by {abs(delta)} points",
            severity=Risk.MEDIUM,
            delta=abs(delta),
        )
    if delta > 0:
        return DecisionReason(
            label="Security score delta",
            detail=f"Score improved by {delta} points",
            severity=Risk.NONE,
        )
    return DecisionReason(label="Security score delta", detail="Score unchanged", severity=Risk.NONE)


def decide(diff: "GraphDiff", policy: Optional[Policy] = None) -> DeploymentDecision:
    """Turn a graph diff into a merge decision plus its justification."""
    new_critical = len(diff.new_critical_paths)
    new_sensitive = len(diff.newly_reachable_sensitive)
    new_exposed = len(diff.newly_exposed)
    new_paths = len(diff.new_attack_paths)

    reasons = [
        DecisionReason(
            label="New critical attack paths",
            detail=(
                f"{_plural(new_critical, 'new path')} from the internet to data marked sensitive"
                if new_critical
                else "No new internet-to-sensitive-data path"
            ),
            severity=Risk.CRITICAL if new_critical else Risk.NONE,
            delta=new_critical,
        ),
        DecisionReason(
            label="Newly reachable sensitive resources",
            detail=(
                ", ".join(diff.newly_reachable_sensitive)
                if new_sensitive
                else "No sensitive resource became reachable"
            ),
            severity=Risk.CRITICAL if new_sensitive else Risk.NONE,
            delta=new_sensitive,
        ),
        DecisionReason(
            label="Newly internet-reachable resources",
            detail=(
                ", ".join(diff.newly_exposed)
                if new_exposed
                else "No resource became internet-reachable"
            ),
            severity=Risk.HIGH if new_exposed else Risk.NONE,
            delta=new_exposed,
        ),
        _score_reason(diff.score_delta),
    ]

    policy = policy or Policy()
    notes = list(policy.warnings)
    violations = []
    if new_critical and policy.block_new_critical_paths:
        violations.append("New critical attack paths are prohibited")
    if new_sensitive and policy.block_new_sensitive_exposure:
        violations.append("New sensitive resource exposure is prohibited")
    def ingress_facts(result):
        facts = set()
        for _, data in result.graph.nodes(data=True):
            node = data["node"]
            if node.type != NodeType.SECURITY_GROUP:
                continue
            resource = TerraformResource("aws_security_group", node.id, node.attributes)
            for finding in public_ingress_findings(resource):
                facts.add((node.id, finding.cidr, finding.from_port, finding.to_port,
                           finding.protocol, finding.is_admin_port))
        return facts

    new_ingress = ingress_facts(diff.after) - ingress_facts(diff.before)
    if policy.block_public_admin_ports and any(fact[-1] for fact in new_ingress):
        violations.append("New public administrative ingress (SSH/RDP/all ports) is prohibited")
    if not policy.allow_public_https and any(
        fact[2:5] in ((443, 443, "tcp"), (443, 443, "6")) for fact in new_ingress
    ):
        violations.append("New public HTTPS ingress is prohibited by policy")
    if policy.minimum_security_score is not None and diff.after.score < policy.minimum_security_score:
        violations.append(
            f"Security score {diff.after.score} is below minimum {policy.minimum_security_score}"
        )
    if new_critical and not policy.block_new_critical_paths:
        notes.append("Critical-path blocking disabled by explicit policy; findings remain visible")
    if new_sensitive and not policy.block_new_sensitive_exposure:
        notes.append("Sensitive-exposure blocking disabled by explicit policy; findings remain visible")
    notes.extend(violations)
    if not diff.complete:
        notes.append("Analysis incomplete: resolve coverage diagnostics before treating this change as safe.")

    if violations:
        decision = Decision.BLOCK
        headline = (
            "This change opens a new path from the public internet to data marked sensitive."
            if new_critical or new_sensitive else "; ".join(violations) + "."
        )
    elif not diff.complete:
        decision = Decision.REVIEW
        headline = "Security-critical inputs or paths are incomplete; manual review is required."
    elif new_paths or new_sensitive or new_exposed or diff.score_delta < 0:
        decision = Decision.REVIEW
        headline = "This change introduces security findings requiring review; see the exposure and policy details."
    else:
        decision = Decision.SAFE
        headline = "This change introduces no new internet-reachable resources or attack paths."
        if diff.removed_critical_paths:
            headline = (
                f"{_plural(len(diff.removed_critical_paths), 'critical attack path')} removed and "
                "no new exposure introduced."
            )

    return DeploymentDecision(
        decision=decision, headline=headline, reasons=reasons, policy=policy, policy_notes=notes
    )
