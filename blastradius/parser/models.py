"""Normalized data model shared by every BlastRadius stage.

Terraform is messy and provider-specific. Everything downstream of the parser
works on these small, boring dataclasses instead, which keeps the graph builder
and the security rules readable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class NodeType(str, Enum):
    """The node kinds in the simplified BlastRadius attack graph."""

    INTERNET = "INTERNET"
    SECURITY_GROUP = "SECURITY_GROUP"
    EC2 = "EC2"
    IAM_ROLE = "IAM_ROLE"
    S3_BUCKET = "S3_BUCKET"
    SENSITIVE_DATA = "SENSITIVE_DATA"


class Relationship(str, Enum):
    """Why an edge exists between two nodes."""

    INGRESS_ALLOWS = "INGRESS_ALLOWS"
    PUBLIC_ACCESS = "PUBLIC_ACCESS"
    PROTECTS = "PROTECTS"
    ASSUMES_ROLE = "ASSUMES_ROLE"
    CAN_ACCESS = "CAN_ACCESS"
    CONTAINS = "CONTAINS"


class Risk(str, Enum):
    """Coarse severity buckets used for colouring and sorting."""

    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @property
    def rank(self) -> int:
        return _RISK_ORDER.index(self)

    @classmethod
    def max(cls, *risks: "Risk") -> "Risk":
        return max(risks, key=lambda r: r.rank) if risks else cls.NONE


_RISK_ORDER = [Risk.NONE, Risk.LOW, Risk.MEDIUM, Risk.HIGH, Risk.CRITICAL]


INTERNET_ID = "INTERNET"


@dataclass(frozen=True)
class Diagnostic:
    """A coverage gap, without input values or machine-local filesystem paths."""

    code: str
    message: str
    severity: str = "warning"
    resource: str = ""
    attribute: str = ""
    source_file: str = ""
    blocks_analysis: bool = True


@dataclass
class TerraformResource:
    """A single `resource "<type>" "<name>"` block, with values normalized."""

    type: str
    name: str
    attributes: Dict[str, Any] = field(default_factory=dict)
    source_file: Optional[str] = None

    @property
    def address(self) -> str:
        """The Terraform address, e.g. `aws_instance.web_server`."""
        return f"{self.type}.{self.name}"

    def get(self, key: str, default: Any = None) -> Any:
        return self.attributes.get(key, default)

    def tags(self) -> Dict[str, Any]:
        tags = self.attributes.get("tags") or {}
        return tags if isinstance(tags, dict) else {}


@dataclass
class ParsedConfig:
    """All resources parsed from one Terraform source (directory or plan JSON)."""

    resources: List[TerraformResource] = field(default_factory=list)
    source_dir: Optional[str] = None
    # Resource types present in the input but outside the modelled coverage.
    # Reported rather than silently dropped, so users know the scope limit.
    unsupported: List[str] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not any(d.blocks_analysis for d in self.diagnostics)

    def of_type(self, *types: str) -> List[TerraformResource]:
        return [r for r in self.resources if r.type in types]

    def by_address(self, address: str) -> Optional[TerraformResource]:
        return next((r for r in self.resources if r.address == address), None)


@dataclass
class ResourceNode:
    """A node in the attack graph."""

    id: str
    type: NodeType
    name: str
    attributes: Dict[str, Any] = field(default_factory=dict)
    sensitive: bool = False
    risk: Risk = Risk.NONE

    @property
    def label(self) -> str:
        return self.name


@dataclass
class GraphEdge:
    """A directed edge in the attack graph, with a human-readable reason.

    `terraform_resource` and `evidence` make an edge auditable: which resource
    block created this relationship, and the specific configuration that proves
    it. Both are optional so edges remain cheap to construct.
    """

    source: str
    target: str
    relationship: Relationship
    reason: str
    risk: Risk = Risk.LOW
    terraform_resource: str = ""
    evidence: str = ""
    # Structured facts about the edge (ports, cidr, ...) for policy decisions
    # that must not rely on parsing the human-readable reason.
    metadata: Dict[str, Any] = field(default_factory=dict)
    confidence: str = "modeled"
    category: str = "reachability"
    source_file: str = ""
    remediation: str = ""


@dataclass
class AttackPath:
    """A concrete Internet-to-resource route through the graph."""

    nodes: List[str]
    edges: List[GraphEdge]
    severity: Risk = Risk.HIGH
    explanation: str = ""
    reaches_sensitive: bool = False

    @property
    def key(self) -> str:
        """Stable identity used for before/after path diffing."""
        return " -> ".join(self.nodes)

    def __len__(self) -> int:
        return len(self.nodes)
