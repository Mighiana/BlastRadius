import hashlib
import json
import sys
import tempfile
from pathlib import Path

import blastradius
from blastradius.server.config import Settings
from blastradius.server.fixtures import FIXTURES
from blastradius.server.jobs import execute
from blastradius.server.schemas import AnalysisInput


def build_demos(settings: Settings) -> dict[tuple[str, str], dict]:
    demos: dict[tuple[str, str], dict] = {}
    for scenario_id, scenario in FIXTURES.items():
        baseline, risky = scenario["before_files"], scenario["after_files"]
        for stage in ("safe", "risky", "remediated"):
            before = risky if stage == "remediated" else baseline
            after = risky if stage == "risky" else baseline
            if stage == "remediated" and scenario_id != "broad_iam":
                patch = demos[(scenario_id, "risky")]["remediation"]["patched_files"]
                if not patch:
                    raise RuntimeError("Supported demo patch is missing")
                after = risky | patch
            payload = AnalysisInput(
                project_id="demo",
                before_files=before,
                after_files=after,
                base_label="risky" if stage == "remediated" else "baseline",
                candidate_label=stage,
            )
            result = execute(payload, settings)
            if "error" in result:
                raise RuntimeError("Bundled demo failed to analyze")
            result["result"]["demo"] = {
                "scenario_id": scenario_id,
                "stage": stage,
                "remediation_kind": "reviewed_fixture"
                if scenario_id == "broad_iam"
                else "supported_patch",
                "note": "The IAM fix restores the reviewed least-privilege fixture; it is not an automatic IAM patch.",
            }
            demos[(scenario_id, stage)] = result["result"]
    return demos


def demo_fingerprint() -> str:
    """Digest of the analyzer source and fixtures a demo cache was computed from."""
    digest = hashlib.sha256()
    package = Path(blastradius.__file__).parent
    for path in sorted(package.rglob("*.py")):
        digest.update(path.relative_to(package).as_posix().encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def write_demo_cache(path: Path, settings: Settings) -> None:
    demos = build_demos(settings)
    path.write_text(
        json.dumps(
            {
                "fingerprint": demo_fingerprint(),
                "demos": [[scenario, stage, result] for (scenario, stage), result in demos.items()],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def load_demo_cache(path: Path | None) -> dict[tuple[str, str], dict] | None:
    """Demos precomputed at image build time, or ``None`` when absent or stale."""
    if path is None or not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if document["fingerprint"] != demo_fingerprint():
            return None
        demos = {(scenario, stage): result for scenario, stage, result in document["demos"]}
    except (OSError, ValueError, KeyError, TypeError):
        return None
    expected = {(scenario, stage) for scenario in FIXTURES for stage in ("safe", "risky", "remediated")}
    return demos if set(demos) == expected else None


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as directory:
        write_demo_cache(Path(sys.argv[1]), Settings(data_dir=Path(directory)))
