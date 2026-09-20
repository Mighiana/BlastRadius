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
