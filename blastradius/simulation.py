"""What-if simulation of infrastructure changes.

Lets the dashboard mutate a Terraform configuration in memory, write it to a
scratch directory, and run it through the *real* parser/graph/analysis pipeline.
Nothing is faked: a simulated change is analysed exactly like a change a
developer committed.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from blastradius.security.hcl_edit import broaden_s3_policy, widen_admin_ingress

PathLike = str | Path

Mutator = Callable[[str], Tuple[str, int]]


@dataclass(frozen=True)
class Simulation:
    """A named, structure-aware mutation of a Terraform configuration."""

    id: str
    title: str
    description: str
    mutate: Mutator

    def apply(self, source: str) -> Tuple[str, int]:
        return self.mutate(source)

    def applies_to(self, source: str) -> bool:
        """True when this mutation would actually change the configuration."""
        _, count = self.mutate(source)
        return count > 0


# Registry of the mutations the UI can offer. Each mirrors a realistic, small
# pull-request edit.
SIMULATIONS: Dict[str, Simulation] = {
    "public_ssh": Simulation(
        id="public_ssh",
        title="Open SSH to the internet",
        description=(
            'Widen the SSH ingress CIDR from 10.0.0.0/24 to 0.0.0.0/0 - the classic '
            '"unblock a remote engineer" change.'
        ),
        mutate=widen_admin_ingress,
    ),
    "broad_iam": Simulation(
        id="broad_iam",
        title="Broaden the IAM policy to s3:*",
        description="Replace the scoped S3 read policy with s3:* on the bucket.",
        mutate=broaden_s3_policy,
    ),
}


@dataclass
class SimulationResult:
    directory: Path
    simulation: Simulation
    replacements: int = 0
    diff: str = ""
    files: Dict[str, str] = field(default_factory=dict)

    @property
    def applied(self) -> bool:
        return self.replacements > 0


def simulate(
    source_dir: PathLike,
    target_dir: PathLike,
    simulation: Simulation,
) -> SimulationResult:
    """Apply `simulation` to every `.tf` file in `source_dir`, writing to `target_dir`.

    Unchanged files are copied verbatim so the target is a complete,
    analysable Terraform directory.
    """
    source = Path(source_dir)
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)

    result = SimulationResult(directory=target, simulation=simulation)
    diff_chunks: List[str] = []

    for tf_file in sorted(source.glob("*.tf")):
        original = tf_file.read_text(encoding="utf-8")
        mutated, count = simulation.apply(original)
        result.replacements += count
        result.files[tf_file.name] = mutated
        (target / tf_file.name).write_text(mutated, encoding="utf-8")
        if count:
            diff_chunks.extend(
                difflib.unified_diff(
                    original.splitlines(keepends=True),
                    mutated.splitlines(keepends=True),
                    fromfile=f"a/{tf_file.name}",
                    tofile=f"b/{tf_file.name}",
                )
            )

    result.diff = "".join(diff_chunks)
    return result


def available_simulations(source_dir: PathLike) -> List[Simulation]:
    """Which registered simulations can actually be applied to this directory."""
    combined = "\n".join(
        p.read_text(encoding="utf-8") for p in sorted(Path(source_dir).glob("*.tf"))
    )
    return [sim for sim in SIMULATIONS.values() if sim.applies_to(combined)]


def get(simulation_id: str) -> Optional[Simulation]:
    return SIMULATIONS.get(simulation_id)
