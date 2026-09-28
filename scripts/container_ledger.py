"""Preserve every Trivy finding and compare package inventories without suppressions."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import cast


def object_value(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return cast(dict[str, object], value)


def objects(value: object) -> list[dict[str, object]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Expected a JSON array")
    return [object_value(item) for item in value]


def text(value: object) -> str:
    return str(value) if value is not None else ""


def read(path: Path) -> dict[str, object]:
    return object_value(json.loads(path.read_text(encoding="utf-8")))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(scan: dict[str, object]) -> list[dict[str, object]]:
    return [
        package
        for result in objects(scan.get("Results"))
        for package in objects(result.get("Packages"))
    ]


RELEVANCE = {
    "util-linux": "Mount/nsenter/login utilities and shared libraries share source advisories. "
    "No mount or namespace capability is granted; the vulnerable utility need not exist in "
    "each flagged library package. Actual exploit reachability remains unproven.",
    "ncurses": "Terminal libraries and data share advisories with infocmp. The reported HIGH "
    "overflow is in infocmp before 6.5-20251213; library presence alone is not that code path.",
    "glibc": "Runtime C library, locale data and tools share source findings. The runtime "
    "loads libc, but individual DNS/debug/regex/locale vulnerability paths are unproven.",
    "libxml2": "PostgreSQL links libxml2 and exposes SQL XML functions. BlastRadius does not "
    "intentionally query XML; SQL access or future code can expose it. Python SAX bindings, "
    "xmlcatalog and core XML callbacks are distinct; linkage does not prove every path.",
    "gnupg2": "Image-construction key verification tooling remains in the old runtime. "
    "GnuPG binaries, localization and meta-packages share source advisories including "
    "tpm2daemon; those package matches do not establish that daemon is installed/running.",
    "systemd": "Shared runtime libraries are flagged with service advisories. Presence of "
    "libsystemd/libudev does not mean journald, networkd or resolved is running.",
    "perl": "Perl interpreter, libraries and modules are installed; PostgreSQL packaging "
    "helpers may use them. Request-path execution of each vulnerable routine is unproven.",
    "pam": "Authentication libraries/modules; the pam_userdb advisory needs a calling "
    "service and relevant configuration. Neither app nor tested database uses PAM login.",
    "shadow": "Local account/login tooling; services run as fixed unprivileged users. "
    "No proof of reachability or nonexploitability for individual account-management paths.",
    "apt": "Package management is used during image construction, not normal request "
    "handling. It was still present in the scanned runtime, so is not build-stage-only.",
    "acl": "Local filesystem ACL library; privileged attacker-controlled path operations "
    "are prerequisites described by the advisory. Dropped capabilities constrain privilege.",
    "attr": "Extended-attribute library shares advisories with getfattr/setfattr utilities. "
    "Library installation does not establish those command paths are present.",
    "bzip2": "Compression library shares advisories with bzip2recover. Library use and "
    "a vulnerable recovery utility are distinct; exploit relevance is uncertain.",
    "sqlite3": "SQLite library is loadable; Session Extension/changeset advisories require "
    "those APIs. Production uses PostgreSQL, but this does not prove nonexploitability.",
    "openssl": "TLS libraries may process external certificates/connections; examine each "
    "advisory against the installed implementation and calling code.",
    "openldap": "LDAP runtime dependency is installed; tested database uses password auth, "
    "not LDAP. Alternative deployments can change reachability.",
    "krb5": "Kerberos libraries are installed; the tested authentication mode is password, "
    "not GSSAPI. Other deployments can activate additional paths.",
    "libxslt": "PostgreSQL extension/runtime dependency; malicious XSLT requires a caller. "
    "No exploitability assertion follows from the tested application queries.",
    "xz-utils": "Compression tools/library support restore/import paths. Malicious archives "
    "and local privilege assumptions differ per advisory; trusted backups are required.",
    "zlib": "Runtime compression library. Package source advisories can concern optional "
    "minizip utilities or core decompression; package presence is not a reachability proof.",
}


def relevance(source: str, package: str) -> str:
    if source in RELEVANCE:
        return RELEVANCE[source]
    return (
        f"{package} is installed in the runtime image. The full advisory below describes "
        "the vulnerable component and preconditions; no call-path proof was established. "
        "Non-root/read-only constraints reduce privilege, not the vulnerability severity."
    )


def counts(rows: list[dict[str, object]]) -> dict[str, int]:
    return dict(sorted(Counter(text(row["severity"]) for row in rows).items()))


def rows_for(
    scan: dict[str, object], stage: str, phase: str, after: dict[str, object]
) -> list[dict[str, object]]:
    after_packages = inventory(after)
    if not after_packages:
        raise ValueError("Comparison scan must include Packages; run Trivy with --list-all-pkgs")
    after_sources = {
        text(p.get("SrcName") or p.get("Name")) for p in after_packages
    }
    after_findings = {
        (text(v.get("VulnerabilityID")), text(v.get("PkgName")))
        for r in objects(after.get("Results"))
        for v in objects(r.get("Vulnerabilities"))
    }
    rows: list[dict[str, object]] = []
    for result_index, result in enumerate(objects(scan.get("Results"))):
        packages = {
            text(p.get("ID") or p.get("Name")): p for p in objects(result.get("Packages"))
        }
        for index, finding in enumerate(objects(result.get("Vulnerabilities"))):
            package = text(finding.get("PkgName"))
            metadata = packages.get(text(finding.get("PkgID") or package), {})
            source = text(metadata.get("SrcName") or package)
            identifier = text(finding.get("VulnerabilityID"))
            replacement = [
                {"package": p.get("Name"), "version": p.get("Version")}
                for p in after_packages
                if text(p.get("SrcName") or p.get("Name")) == source
            ]
            if (identifier, package) in after_findings:
                disposition = "still-reported"
                remediation = "Await vendor fix or reviewed compatible base; retain promotion block."
                residual = "Finding retained at original scanner severity; reachability uncertain."
            elif source not in after_sources:
                disposition = "source-package-absent"
                remediation = "Source package absent from final inventory after base change or purge."
                residual = "Removal is not a patch; replacement implementations have independent risk."
            else:
                disposition = "not-reported-source-retained"
                remediation = "Compare vendor fixes and upstream affected range; scan silence is not proof."
                residual = "Cross-distribution detection/coverage difference or version change; unresolved without vendor evidence."
            rows.append({
                "row_id": f"{phase}:{stage}:{result_index}:{index}",
                "phase": phase,
                "stage": stage,
                "scope": "installed-runtime",
                "target": result.get("Target"),
                "cve": identifier,
                "package": package,
                "source_package": source,
                "source_version": metadata.get("SrcVersion"),
                "installed_version": finding.get("InstalledVersion"),
                "fixed_version": finding.get("FixedVersion"),
                "scanner_status": finding.get("Status"),
                "severity": finding.get("Severity", "UNKNOWN"),
                "package_id": finding.get("PkgID"),
                "package_url": object_value(finding.get("PkgIdentifier", {})).get("PURL"),
                "installed_files": metadata.get("InstalledFiles", []),
                "relevance": relevance(source, package),
                "reachability": "uncertain; no exploit test performed",
                "remediation": remediation,
                "disposition": disposition,
                "replacement_packages_same_source": replacement,
                "residual_risk": residual,
                "source_cve_group": f"{phase}:{stage}:{source}:{identifier}",
                "advisory": finding,
            })
        for index, finding in enumerate(objects(result.get("Secrets"))):
            rows.append({
                "row_id": f"{phase}:{stage}:{result_index}:secret:{index}",
                "phase": phase, "stage": stage, "scope": "installed-runtime",
                "cve": finding.get("RuleID"), "package": result.get("Target"),
                "severity": finding.get("Severity", "UNKNOWN"),
                "remediation": "Remove secret, rebuild, and rotate any exposed credential.",
                "residual_risk": "Secret finding blocks release.",
                "advisory": finding,
            })
    groups = Counter(text(row.get("source_cve_group")) for row in rows)
    for row in rows:
        row["source_cve_package_rows"] = groups[text(row.get("source_cve_group"))]
    return rows


def markdown(rows: list[dict[str, object]]) -> str:
    def cell(value: object) -> str:
        return text(value).replace("|", "\\|").replace("\n", " ")

    lines = [
        "# Container vulnerability ledger",
        "",
        "One row per scanner package finding, including duplicate source advisories. "
        "Blank fixed version means none provided by this scan. All rows concern installed "
        "runtime packages, even when only normally used during image construction. "
        "The JSON includes full advisories, installed files, versions and comparison evidence.",
        "",
        "| Phase/stage | CVE | Binary package (source) | Installed → fixed | Severity | Relevance | Remediation | Residual risk |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(cell(value) for value in (
            f"{row['phase']}/{row['stage']}", row["cve"],
            f"{row['package']} ({row.get('source_package', '')})",
            f"{row.get('installed_version', '')} → {row.get('fixed_version') or 'not supplied'}",
            row["severity"], row.get("relevance"), row["remediation"], row["residual_risk"],
        )) + " |")
    return "\n".join(lines) + "\n"


def apply_assessments(
    rows: list[dict[str, object]], assessments: list[dict[str, object]]
) -> None:
    for row in rows:
        for assessment in assessments:
            if (row.get("stage") != assessment["stage"]
                    or row.get("source_package") != assessment["source_package"]
                    or row.get("cve") not in text(assessment["cves"]).split()):
                continue
            replacements = objects(row.get("replacement_packages_same_source"))
            if not replacements or {
                text(p.get("version")) for p in replacements
            } != {text(assessment["replacement_version"])}:
                continue
            row["replacement_assessment"] = assessment
            row["remediation"] = assessment["remediation"]
            row["residual_risk"] = assessment["residual_risk"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("before-app", "before-database", "after-app", "after-database",
                 "before-scanner", "after-scanner"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument("--assessments", type=Path)
    args = parser.parse_args()
    scans = {
        "before:runtime": args.before_app, "before:database": args.before_database,
        "after:runtime": args.after_app, "after:database": args.after_database,
    }
    after = {"runtime": read(args.after_app), "database": read(args.after_database)}
    rows: list[dict[str, object]] = []
    evidence: dict[str, object] = {}
    totals: dict[str, object] = {}
    for key, path in scans.items():
        phase, stage = key.split(":")
        scan = read(path)
        scan_rows = rows_for(scan, stage, phase, after[stage])
        rows.extend(scan_rows)
        totals[key] = counts(scan_rows)
        evidence[key] = {
            "filename": path.name, "sha256": digest(path),
            "artifact_name": scan.get("ArtifactName"), "metadata": scan.get("Metadata"),
            "inventory": inventory(scan),
        }
    if args.assessments:
        apply_assessments(rows, objects(read(args.assessments)["assessments"]))
        evidence["assessment_sha256"] = digest(args.assessments)
    ledger = {
        "schema_version": 1, "findings": rows, "counts": totals, "evidence": evidence,
        "carried_forward_findings": [
            {
                "baseline_row_id": row["row_id"], "stage": row["stage"], "cve": row["cve"],
                "source_package": row.get("source_package"), "severity": row["severity"],
                "replacement_packages": row.get("replacement_packages_same_source"),
                "assessment": row["replacement_assessment"],
            }
            for row in rows
            if object_value(row.get("replacement_assessment", {})).get("status") == "unresolved"
        ],
        "scanners": {
            "before": read(args.before_scanner), "after": read(args.after_scanner),
            "before_sha256": digest(args.before_scanner),
            "after_sha256": digest(args.after_scanner),
        },
        "limitations": [
            "No findings are suppressed or severity-adjusted by this ledger.",
            "Source-CVE grouping describes duplication; package rows are never deduplicated.",
            "Scan silence across distributions does not establish a fix or nonexploitability.",
            "These scans do not cover discarded frontend/python-build stages or the host kernel.",
            "Scanner JSON is version/database provenance, not an additional image vulnerability scan.",
        ],
    }
    args.output.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
    args.markdown.write_text(markdown(rows), encoding="utf-8")
    print(json.dumps(totals, sort_keys=True))


if __name__ == "__main__":
    main()
