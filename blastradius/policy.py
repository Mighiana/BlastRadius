"""Optional repository policy (`blastradius.yml`).

The policy tunes the *gate*, never the analysis. The attack graph, the rules and
the score are computed identically with or without a policy file - a policy can
only decide how strictly the resulting facts are enforced. That separation is
deliberate: a repository cannot configure away the evidence, only the verdict.

With no file present, critical regressions block and noncritical exposure requires
review, preserving the original gate. Explicit policies additionally enable
standalone administrative-ingress blocking by default.

    version: 1

    gate:
      block_new_critical_paths: true
      block_new_sensitive_exposure: true
      block_public_admin_ports: true

    allowed:
      public_https: true        # 0.0.0.0/0 on 443 alone is not a blocker

    thresholds:
      minimum_security_score: 70
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

POLICY_FILENAMES = ("blastradius.yml", "blastradius.yaml")

DEFAULTS: Dict[str, Any] = {
    "gate": {
        "block_new_critical_paths": True,
        "block_new_sensitive_exposure": True,
        "block_public_admin_ports": True,
    },
    "allowed": {
        # A public HTTPS listener is a normal design choice, so on its own it
        # does not block. It still appears in the graph and still contributes
        # to any path that reaches sensitive data.
        "public_https": True,
    },
    "thresholds": {
        "minimum_security_score": None,
    },
}


class PolicyError(ValueError):
    """The policy file exists but cannot be used."""


@dataclass
class Policy:
    """Resolved gate configuration."""

    block_new_critical_paths: bool = True
    block_new_sensitive_exposure: bool = True
    block_public_admin_ports: bool = False
    allow_public_https: bool = True
    minimum_security_score: Optional[int] = None
    source: Optional[str] = None
    warnings: List[str] = field(default_factory=list)

    @property
    def is_default(self) -> bool:
        return self.source is None

    def describe(self) -> str:
        if self.is_default:
            return "default policy (critical regressions block; noncritical exposure requires review)"
        enabled = [
            name
            for name, on in (
                ("new critical paths", self.block_new_critical_paths),
                ("new sensitive exposure", self.block_new_sensitive_exposure),
                ("public admin ports", self.block_public_admin_ports),
            )
            if on
        ]
        detail = ", ".join(enabled) or "no blocking gates"
        if self.minimum_security_score is not None:
            detail += f", min score {self.minimum_security_score}"
        return f"{self.source}: {detail}"


DEFAULT_POLICY = Policy()


def _coerce_bool(value: Any, key: str, warnings: List[str], fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    raise PolicyError(f"{key}: expected true/false, got {value!r}")


def load_policy_data(data: Any, source: Optional[str] = None) -> Policy:
    """Build a `Policy` from an already-parsed mapping."""
    if data is None:
        return Policy(source=source)
    if not isinstance(data, dict):
        raise PolicyError(f"Policy must be a mapping, got {type(data).__name__}")

    warnings: List[str] = []
    unknown = set(data) - {"version", "gate", "allowed", "thresholds"}
    if unknown:
        raise PolicyError(f"Unknown policy keys: {sorted(unknown)}")

    version = data.get("version", 1)
    if type(version) is not int or version != 1:
        raise PolicyError(f"Unsupported policy version: {version!r}")

    gate = data.get("gate") or {}
    allowed = data.get("allowed") or {}
    thresholds = data.get("thresholds") or {}
    for name, section in (("gate", gate), ("allowed", allowed), ("thresholds", thresholds)):
        if not isinstance(section, dict):
            raise PolicyError(f"'{name}' must be a mapping, got {type(section).__name__}")
        unknown = set(section) - set(DEFAULTS[name])
        if unknown:
            raise PolicyError(f"Unknown {name} keys: {sorted(unknown)}")

    minimum = thresholds.get("minimum_security_score", DEFAULTS["thresholds"]["minimum_security_score"])
    if minimum is not None and (type(minimum) is not int or not 0 <= minimum <= 100):
        raise PolicyError("minimum_security_score must be an integer from 0 to 100")

    defaults = DEFAULTS["gate"]
    return Policy(
        block_new_critical_paths=_coerce_bool(
            gate.get("block_new_critical_paths", defaults["block_new_critical_paths"]),
            "block_new_critical_paths",
            warnings,
            defaults["block_new_critical_paths"],
        ),
        block_new_sensitive_exposure=_coerce_bool(
            gate.get("block_new_sensitive_exposure", defaults["block_new_sensitive_exposure"]),
            "block_new_sensitive_exposure",
            warnings,
            defaults["block_new_sensitive_exposure"],
        ),
        block_public_admin_ports=_coerce_bool(
            gate.get("block_public_admin_ports", defaults["block_public_admin_ports"]),
            "block_public_admin_ports",
            warnings,
            defaults["block_public_admin_ports"],
        ),
        allow_public_https=_coerce_bool(
            allowed.get("public_https", DEFAULTS["allowed"]["public_https"]),
            "public_https",
            warnings,
            DEFAULTS["allowed"]["public_https"],
        ),
        minimum_security_score=minimum,
        source=source,
        warnings=warnings,
    )


def load_policy_file(path: str | Path) -> Policy:
    """Load a policy from an explicit path."""
    file_path = Path(path)
    if not file_path.is_file():
        raise PolicyError(f"Policy file not found: {file_path}")
    try:
        import yaml
    except ImportError as error:  # pragma: no cover - PyYAML is in requirements
        raise PolicyError(
            "PyYAML is required to read a policy file (pip install -r requirements.txt)"
        ) from error
    try:
        data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    except Exception as error:  # yaml.YAMLError and friends
        raise PolicyError(f"Policy file is not valid YAML: {file_path} ({error})") from error
    return load_policy_data(data, source=str(file_path))


def discover_policy(*search_dirs: str | Path) -> Policy:
    """Find `blastradius.yml` in the given directories, else return the defaults.

    Missing policies use the compatibility defaults. Invalid policies raise
    PolicyError so a typo cannot silently disable a configured security gate.
    """
    for directory in search_dirs:
        if not directory:
            continue
        for filename in POLICY_FILENAMES:
            candidate = Path(directory) / filename
            if candidate.is_file():
                return load_policy_file(candidate)
    return Policy()
