from __future__ import annotations

import difflib
import json
from dataclasses import asdict
from pathlib import Path

from blastradius.graph import analyze, build_graph, compare
from blastradius.graph.attack_paths import AnalysisResult
from blastradius.parser import parse_directory
from blastradius.parser.models import AttackPath, GraphEdge
from blastradius.parser.plan_parser import parse_plan_pair
from blastradius.report import build_report, responsible_change
from blastradius.sarif import build_sarif
from blastradius.security.decision import decide
from blastradius.security.remediation import generate_safer_config, recommend
from blastradius.server.schemas import AnalysisInput

LIMITATION = "Simplified static AWS model; a path is not proof of exploitability and no path is not proof of safety."


class ResourceLimitError(ValueError):
    pass


def edge_payload(edge: GraphEdge) -> dict:
    return {
        "source": edge.source,
        "target": edge.target,
        "relationship": edge.relationship.value,
        "reason": edge.reason,
        "evidence": edge.evidence,
        "severity": edge.risk.value,
        "terraform_resource": edge.terraform_resource,
        "metadata": edge.metadata,
        "confidence": edge.confidence,
        "category": edge.category,
        "source_file": edge.source_file,
        "remediation": edge.remediation,
    }


def path_payload(path: AttackPath, result: AnalysisResult) -> dict:
    return {
        "id": path.key,
        "nodes": path.nodes,
        "labels": result.display_path(path),
        "edges": [edge_payload(edge) for edge in path.edges],
        "severity": path.severity.value,
        "explanation": path.explanation,
        "reaches_sensitive": path.reaches_sensitive,
    }


def snapshot(result: AnalysisResult) -> dict:
    nodes = [result.node(node_id) for node_id in sorted(result.graph.nodes)]
    return {
        "label": result.label,
        "complete": result.complete,
        "paths_truncated": result.paths_truncated,
        "path_work": result.path_work,
        "score": result.score,
        "risk_level": result.risk_level.value,
        "score_breakdown": result.score_breakdown,
        "exposed_resources": result.exposed_resources,
        "reachable_sensitive": result.reachable_sensitive,
        "attack_paths": [path_payload(path, result) for path in result.attack_paths],
        "graph": {
            "nodes": [
                {
                    "id": n.id,
                    "name": n.name,
                    "type": n.type.value,
                    "sensitive": n.sensitive,
                    "risk": n.risk.value,
                }
                for n in nodes
            ],
            "edges": [
                edge_payload(result.graph.edges[a, b]["edge"])
                for a, b in sorted(result.graph.edges)
            ],
        },
    }


def analyze_input(payload: AnalysisInput, workdir: Path, max_resources: int) -> dict:
    before_dir = after_dir = None
    if payload.plan is not None:
        plan_file = workdir / "plan.json"
        plan_file.write_text(json.dumps(payload.plan), encoding="utf-8")
        before_config, after_config = parse_plan_pair(plan_file)
    else:
        before_dir, after_dir = workdir / "before", workdir / "after"
        for directory, files in (
            (before_dir, payload.before_files),
            (after_dir, payload.after_files),
        ):
            directory.mkdir()
            for name, content in sorted((files or {}).items()):
                (directory / name).write_text(content, encoding="utf-8")
        before_config, after_config = (
            parse_directory(before_dir),
            parse_directory(after_dir),
        )
    for config in (before_config, after_config):
        if len(config.resources) > max_resources:
            raise ResourceLimitError("resource_limit_exceeded")
        addresses = [r.address for r in config.resources]
        if len(addresses) != len(set(addresses)):
            raise ValueError("duplicate_resource_address")
        for resource in config.resources:
            if resource.source_file:
                resource.source_file = Path(resource.source_file).name
    before = analyze(build_graph(before_config), payload.base_label)
    after = analyze(build_graph(after_config), payload.candidate_label)
    diff = compare(before, after)
    decision = decide(diff)
    remediation = generate_safer_config(after_dir) if after_dir else None
    advice = recommend(after_config, after.graph)
    unsupported = sorted(set(before_config.unsupported + after_config.unsupported))
    diagnostics = [
        {"code": "unsupported", "severity": "warning", "message": item}
        for item in unsupported
    ]
    diagnostics.extend(
        {"phase": phase, **asdict(diagnostic)}
        for phase, result in (("before", before), ("after", after))
        for diagnostic in result.diagnostics
    )
    diagnostics.append(
        {"code": "model_limitations", "severity": "info", "message": LIMITATION}
    )
    changes = []
    for name in sorted(
        set(payload.before_files or {}) | set(payload.after_files or {})
    ):
        old, new = (
            (payload.before_files or {}).get(name, ""),
            (payload.after_files or {}).get(name, ""),
        )
        if old != new:
            changes.append(
                {
                    "file": name,
                    "diff": "".join(
                        difflib.unified_diff(
                            old.splitlines(keepends=True),
                            new.splitlines(keepends=True),
                            fromfile=f"a/{name}",
                            tofile=f"b/{name}",
                        )
                    ),
                }
            )
    return {
        "schema_version": 1,
        "analysis_complete": diff.complete,
        "decision": decision.decision.value,
        "passed": decision.passed,
        "headline": decision.headline,
        "verdict": diff.verdict.value,
        "score": {
            "before": before.score,
            "after": after.score,
            "delta": diff.score_delta,
        },
        "before": snapshot(before),
        "after": snapshot(after),
        "new_attack_paths": [path_payload(p, after) for p in diff.new_attack_paths],
        "removed_attack_paths": [
            path_payload(p, before) for p in diff.removed_attack_paths
        ],
        "new_critical_paths": [path_payload(p, after) for p in diff.new_critical_paths],
        "removed_critical_paths": [
            path_payload(p, before) for p in diff.removed_critical_paths
        ],
        "newly_exposed": diff.newly_exposed,
        "newly_reachable_sensitive": diff.newly_reachable_sensitive,
        "new_nodes": diff.new_nodes,
        "removed_nodes": diff.removed_nodes,
        "new_edges": [edge_payload(e) for e in diff.new_edges],
        "removed_edges": [edge_payload(e) for e in diff.removed_edges],
        "findings": [
            {
                "label": r.label,
                "detail": r.detail,
                "delta": r.delta,
                "severity": r.severity.value,
            }
            for r in decision.reasons
        ],
        "responsible_change": responsible_change(before_dir, after_dir),
        "responsible_changes": changes,
        "diagnostics": diagnostics,
        "limitations": [LIMITATION],
        "remediation": {
            "recommendations": [
                {
                    "title": r.title,
                    "detail": r.detail,
                    "current": r.current,
                    "recommended": r.recommended,
                    "severity": r.severity.value,
                    "resource": r.resource,
                }
                for r in advice
            ],
            "patched_files": remediation.patched_files if remediation else {},
            "diff": remediation.diff if remediation else "",
            "can_autofix": remediation.can_autofix if remediation else False,
        },
        "reports": {
            "markdown": build_report(diff, decision, before_dir, after_dir),
            "sarif": build_sarif(diff, decision),
        },
    }
