"""Customer evidence must remain actual, reproducible installed-CLI output."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "examples/customer"


@pytest.fixture(scope="module")
def generated(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("customer-samples")
    result = subprocess.run(
        [sys.executable, "-I", str(ROOT / "scripts/generate_customer_samples.py"),
         "--output", str(output)],
        cwd=output,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return output


def test_customer_bundle_is_byte_reproducible_without_local_paths(generated: Path) -> None:
    committed = {p.relative_to(SAMPLES) for p in SAMPLES.rglob("*") if p.is_file()}
    reproduced = {p.relative_to(generated) for p in generated.rglob("*") if p.is_file()}
    assert reproduced == committed
    for name in sorted(committed):
        content = (generated / name).read_bytes()
        assert content == (SAMPLES / name).read_bytes(), str(name)
        for private_path in (str(ROOT), str(generated), str(Path.home())):
            assert private_path.encode() not in content, str(name)


def test_customer_change_and_engine_repair_are_one_line(generated: Path) -> None:
    before = (generated / "before/main.tf").read_text()
    after = (generated / "after/main.tf").read_text()
    fixed = (generated / "remediated/main.tf").read_text()
    assert fixed == before
    assert len(before.splitlines()) == len(after.splitlines())
    changes = [(old.strip(), new.strip())
               for old, new in zip(before.splitlines(), after.splitlines()) if old != new]
    assert changes == [('cidr_blocks = ["10.0.0.0/24"]', 'cidr_blocks = ["0.0.0.0/0"]')]
    assert 'protocol    = "-1"\n    cidr_blocks = ["0.0.0.0/0"]' in fixed
    patch = (generated / "remediation.patch").read_text()
    assert '-    cidr_blocks = ["0.0.0.0/0"]' in patch
    assert '+    cidr_blocks = ["10.0.0.0/24"]' in patch


def test_customer_block_has_the_full_modeled_evidence_chain(generated: Path) -> None:
    result = json.loads((generated / "output/risky/result.json").read_text())
    assert result["decision"] == "BLOCK CHANGE"
    assert result["analysis_complete"] is True
    assert result["critical_paths_added"] == 1
    assert result["newly_reachable_sensitive"] == ["aws_s3_bucket.customer_data"]
    sarif = json.loads((generated / "output/risky/results.sarif").read_text())
    critical = [r for r in sarif["runs"][0]["results"] if r["ruleId"] == "BR001"]
    assert len(critical) == 1
    path = ["INTERNET", "aws_security_group.web", "aws_instance.web_server",
            "aws_iam_role.app", "aws_s3_bucket.customer_data", "sensitive_data.customer_data"]
    assert critical[0]["properties"]["attackPath"] == path
    edges = critical[0]["properties"]["edgeEvidence"]
    assert [(edge["source"], edge["target"]) for edge in edges] == list(zip(path, path[1:]))
    assert all(edge["evidence"] and edge["source_file"] == "main.tf" for edge in edges)
    assert [edge["confidence"] for edge in edges] == [
        "modeled", "modeled", "conditional", "conservative", "modeled",
    ]
    assert result["edge_evidence"] == [edges[0]]
    assert critical[0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "main.tf"
    report = (generated / "output/risky/report.md").read_text()
    assert "10.0.0.0/24" in report and "0.0.0.0/0" in report


@pytest.mark.parametrize(("case", "decision", "exit_code", "complete"), [
    ("baseline", "SAFE TO MERGE", 0, True),
    ("risky", "BLOCK CHANGE", 1, True),
    ("remediated", "SAFE TO MERGE", 0, True),
    ("review-default", "REVIEW REQUIRED", 0, False),
    ("review-strict", "REVIEW REQUIRED", 1, False),
])
def test_customer_result_and_process_exits(
    generated: Path, case: str, decision: str, exit_code: int, complete: bool,
) -> None:
    result = json.loads((generated / f"output/{case}/result.json").read_text())
    manifest = json.loads((generated / "manifest.json").read_text())
    run = next(run for run in manifest["runs"] if run["case"] == case)
    assert result["decision"] == decision
    assert result["analysis_complete"] is complete
    assert result["exit_code"] == run["exit_code"] == exit_code
    if case.startswith("review"):
        assert result["coverage_diagnostics"]
        assert result["verdict"] == "INCOMPLETE ANALYSIS"
    if case in ("baseline", "remediated"):
        assert result["new_critical_paths"] == []
        assert result["score"]["after"] == 100
    if case == "remediated":
        assert len(result["removed_critical_paths"]) == 1


def test_customer_usage_error_never_becomes_a_passing_result(generated: Path) -> None:
    result = json.loads((generated / "output/error/result.json").read_text())
    sarif = json.loads((generated / "output/error/results.sarif").read_text())
    assert result["decision"] == "ERROR"
    assert result["exit_code"] == 2
    assert result["passed"] is False
    assert result["critical_paths_added"] == ""
    assert sarif["runs"][0]["invocations"] == [{"executionSuccessful": False}]
