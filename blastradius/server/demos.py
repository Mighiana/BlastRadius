import hashlib
import importlib.metadata
import json
import logging
import shutil
import sys
import tempfile
from pathlib import Path

import blastradius
from importlib.metadata import PackageNotFoundError
from blastradius.server.config import Settings
from blastradius.server.fixtures import FIXTURES
from blastradius.server.jobs import execute
from blastradius.server.schemas import AnalysisInput

LOGGER = logging.getLogger(__name__)
DEMO_STAGES = ("safe", "risky", "remediated")
DEMO_COUNT = len(FIXTURES) * len(DEMO_STAGES)


def build_demos(settings: Settings) -> dict[tuple[str, str], dict]:
    demos: dict[tuple[str, str], dict] = {}
    work_dir = settings.data_dir.resolve() / "demos"
    work_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    for path in work_dir.glob("job-*"):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
    for scenario_id, scenario in FIXTURES.items():
        baseline, risky = scenario["before_files"], scenario["after_files"]
        for stage in DEMO_STAGES:
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
            result = execute(payload, settings, work_dir=work_dir)
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
    digest.update(sys.version.encode() + b"\0")
    for name in ("python-hcl2", "lark", "networkx"):
        try:
            version = importlib.metadata.version(name)
        except PackageNotFoundError:
            version = "missing"
        digest.update(name.encode() + b"\0" + version.encode() + b"\0")
    return digest.hexdigest()


def write_demo_cache(path: Path, settings: Settings) -> None:
    demos = build_demos(settings)
    path.write_text(
        json.dumps(
            {
                "fingerprint": demo_fingerprint(),
                "settings": demo_settings(settings),
                "demos": [[scenario, stage, result] for (scenario, stage), result in demos.items()],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def demo_settings(settings: Settings) -> dict[str, int]:
    return {
        "job_timeout_seconds": settings.job_timeout_seconds,
        "max_body_bytes": settings.max_body_bytes,
        "max_resources": settings.max_resources,
    }


def load_demo_cache(
    path: Path | None, settings: Settings
) -> dict[tuple[str, str], dict] | None:
    """Demos precomputed at image build time, or ``None`` when absent or stale."""
    if path is None:
        LOGGER.info(json.dumps({"event": "demo.cache_miss", "reason": "unconfigured"}))
        return None
    if not path.is_file():
        LOGGER.warning(json.dumps({"event": "demo.cache_miss", "reason": "missing"}))
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if document["settings"] != demo_settings(settings):
            LOGGER.warning(json.dumps({"event": "demo.cache_miss", "reason": "settings"}))
            return None
        if document["fingerprint"] != demo_fingerprint():
            LOGGER.warning(json.dumps({"event": "demo.cache_miss", "reason": "stale"}))
            return None
        demos = {(scenario, stage): result for scenario, stage, result in document["demos"]}
        if any(
            not isinstance(result, dict)
            or not {"decision", "score", "verdict"} <= result.keys()
            for result in demos.values()
        ):
            LOGGER.warning(json.dumps({"event": "demo.cache_miss", "reason": "corrupt"}))
            return None
    except (OSError, ValueError, KeyError, TypeError):
        LOGGER.warning(json.dumps({"event": "demo.cache_miss", "reason": "corrupt"}))
        return None
    expected = {(scenario, stage) for scenario in FIXTURES for stage in DEMO_STAGES}
    if set(demos) != expected:
        LOGGER.warning(json.dumps({"event": "demo.cache_miss", "reason": "incomplete"}))
        return None
    LOGGER.info(json.dumps({"event": "demo.cache_loaded", "count": len(demos)}))
    return demos


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as directory:
        settings = Settings(data_dir=Path(directory))
        write_demo_cache(Path(sys.argv[1]), settings)
