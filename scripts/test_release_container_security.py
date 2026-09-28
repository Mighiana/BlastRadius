from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def ledger_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "container_ledger", ROOT / "scripts/container_ledger.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def scan(packages: list[str], findings: bool = True) -> dict[str, object]:
    return {"Results": [{
        "Target": "fixture", "Packages": [
            {"ID": name, "Name": name, "SrcName": "source", "Version": "1"}
            for name in packages
        ],
        "Vulnerabilities": [
            {"VulnerabilityID": "CVE-fixture", "PkgName": name, "PkgID": name,
             "InstalledVersion": "1", "Severity": "UNKNOWN"}
            for name in packages
        ] if findings else None,
    }]}


def test_ledger_preserves_duplicate_source_findings_and_unknown_severity() -> None:
    rows = ledger_module().rows_for(scan(["library", "utility"]), "runtime", "before",
                                   scan(["library", "utility"]))
    assert len(rows) == 2
    assert {r["package"] for r in rows} == {"library", "utility"}
    assert {r["source_cve_package_rows"] for r in rows} == {2}
    assert {r["severity"] for r in rows} == {"UNKNOWN"}
    assert all(r["fixed_version"] is None for r in rows)


def test_ledger_does_not_treat_scan_silence_as_a_vendor_fix() -> None:
    rows = ledger_module().rows_for(scan(["library"]), "runtime", "before",
                                   scan(["library"], findings=False))
    assert rows[0]["disposition"] == "not-reported-source-retained"
    assert "unresolved" in rows[0]["residual_risk"]


def test_ledger_distinguishes_removal_from_version_fix() -> None:
    after = {"Results": [{"Packages": [{"ID": "replacement", "Name": "replacement"}]}]}
    rows = ledger_module().rows_for(scan(["library"]), "runtime", "before", after)
    assert rows[0]["disposition"] == "source-package-absent"
    assert "not a patch" in rows[0]["residual_risk"]


def test_ledger_requires_inventory_to_claim_package_removal() -> None:
    with pytest.raises(ValueError, match="must include Packages"):
        ledger_module().rows_for(scan(["library"]), "runtime", "before",
                                 {"Results": [{"Vulnerabilities": []}]})


def test_ledger_retains_secrets_and_nullable_vulnerability_lists() -> None:
    after = scan(["library"], findings=False)
    before = {"Results": [{"Target": "file", "Vulnerabilities": None,
                          "Secrets": [{"RuleID": "fixture-token", "Severity": "HIGH"}]}]}
    rows = ledger_module().rows_for(before, "runtime", "before", after)
    assert len(rows) == 1
    assert rows[0]["cve"] == "fixture-token"
    assert rows[0]["residual_risk"] == "Secret finding blocks release."


def test_vendor_assessments_require_the_exact_replacement_version() -> None:
    module = ledger_module()
    rows = module.rows_for(scan(["library"]), "runtime", "before",
                           scan(["library"], findings=False))
    assessment = {
        "stage": "runtime", "source_package": "source", "cves": "CVE-fixture",
        "replacement_version": "2", "remediation": "verified fix",
        "residual_risk": "scoped evidence",
    }
    module.apply_assessments(rows, [assessment])
    assert "replacement_assessment" not in rows[0]
    assessment["replacement_version"] = "1"
    module.apply_assessments(rows, [assessment])
    assert rows[0]["remediation"] == "verified fix"


def test_language_packages_without_ids_do_not_drop_findings() -> None:
    report = {"Results": [{
        "Packages": [{"Name": "dependency", "Version": "1"}],
        "Vulnerabilities": [{"PkgName": "dependency", "VulnerabilityID": "CVE-fixture"}],
    }]}
    rows = ledger_module().rows_for(report, "runtime", "after", report)
    assert len(rows) == 1
    assert rows[0]["severity"] == "UNKNOWN"
