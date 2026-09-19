"""Bundled demo scenarios.

Each scenario is a pair of real Terraform directories analysed by the same
engine - nothing about the output is hardcoded. They exist to show that
BlastRadius reasons about reachability rather than pattern-matching one
prepared file.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    root_cause: str
    change: str
    before: Path
    after: Path

    @property
    def label(self) -> str:
        return f"{self.title} ({self.root_cause})"


SCENARIOS: List[Scenario] = [
    Scenario(
        id="public_ssh",
        title="Public SSH exposure",
        root_cause="network",
        change='SSH ingress CIDR 10.0.0.0/24 -> 0.0.0.0/0',
        before=EXAMPLES / "safe",
        after=EXAMPLES / "vulnerable",
    ),
    Scenario(
        id="broad_iam",
        title="Overly broad IAM permission",
        root_cause="identity",
        change='IAM policy s3:PutObject on one bucket -> s3:* on "*"',
        before=EXAMPLES / "scenarios" / "broad_iam" / "before",
        after=EXAMPLES / "scenarios" / "broad_iam" / "after",
    ),
    Scenario(
        id="public_bucket",
        title="Public sensitive S3 bucket",
        root_cause="storage",
        change='Bucket ACL private -> public-read',
        before=EXAMPLES / "scenarios" / "public_bucket" / "before",
        after=EXAMPLES / "scenarios" / "public_bucket" / "after",
    ),
]


def get(scenario_id: str) -> Optional[Scenario]:
    return next((s for s in SCENARIOS if s.id == scenario_id), None)


def by_dirs(before: Path, after: Path) -> Optional[Scenario]:
    """Identify which bundled scenario a directory pair corresponds to, if any."""
    for scenario in SCENARIOS:
        try:
            if scenario.before.samefile(before) and scenario.after.samefile(after):
                return scenario
        except OSError:
            continue
    return None
