from __future__ import annotations

import hashlib
from dataclasses import asdict
from urllib.parse import quote

from blastradius import __version__
from blastradius.parser.models import Relationship
from blastradius.parser.coverage import safe_source
from blastradius.security.decision import Decision, decide

RULES = [
    {"id": "BR001", "name": "NewCriticalAttackPath",
     "shortDescription": {"text": "New internet-to-sensitive-data attack path"},
     "defaultConfiguration": {"level": "error"},
     "properties": {"security-severity": "9.0"}},
    {"id": "BR002", "name": "NewInternetExposure",
     "shortDescription": {"text": "New internet-facing attack path"},
     "defaultConfiguration": {"level": "warning"},
     "properties": {"security-severity": "6.0"}},
    {"id": "BR003", "name": "PolicyGateViolation",
     "shortDescription": {"text": "Repository security policy blocks this change"},
     "defaultConfiguration": {"level": "error"}},
    {"id": "BR004", "name": "IncompleteAnalysis",
     "shortDescription": {"text": "Static analysis coverage diagnostic"},
     "defaultConfiguration": {"level": "warning"}},
]


def recommendation(edges):
    if any(e.relationship == Relationship.PUBLIC_ACCESS for e in edges):
        return "Remove public bucket access and review bucket ACLs and policy."
    if any(e.relationship == Relationship.CAN_ACCESS for e in edges):
        return "Restrict IAM permissions to the intended bucket ARNs and required actions."
    return "Restrict public administrative ingress to a trusted CIDR and re-analyze."


def location(resource, graph):
    result = {"logicalLocations": [{"fullyQualifiedName": resource, "kind": "resource"}]}
    file = graph.graph.get("source_files", {}).get(resource)
    if file:
        uri = quote(safe_source(file), safe="/")
        result["physicalLocation"] = {"artifactLocation": {"uri": uri}}
    return result


def build_sarif(diff, decision=None):
    decision = decision or decide(diff)
    results = []
    new_edges = {(e.source, e.target) for e in diff.new_edges}
    for path in diff.new_attack_paths:
        changed = [e for e in path.edges if (e.source, e.target) in new_edges]
        responsible = changed or path.edges
        resource = next((e.terraform_resource for e in responsible if e.terraform_resource), "")
        rule_id = "BR001" if path.reaches_sensitive else "BR002"
        advice = recommendation(responsible)
        labels = diff.display_path(path)
        result = {
            "ruleId": rule_id,
            "ruleIndex": 0 if path.reaches_sensitive else 1,
            "level": "error" if path.reaches_sensitive else "warning",
            "message": {"text": "New attack path: " + " -> ".join(labels) + ". " + advice},
            "partialFingerprints": {"attackPath/v1": hashlib.sha256(path.key.encode()).hexdigest()},
            "properties": {"attackPath": path.nodes, "severity": path.severity.value,
                           "terraformResource": resource, "recommendation": advice,
                           "edgeEvidence": [asdict(edge) for edge in path.edges]},
            "codeFlows": [{"threadFlows": [{"locations": [
                {"location": {
                    **location(edge.terraform_resource or edge.target, diff.after.graph),
                    "message": {"text": f"{edge.source} -> {edge.target}: {edge.reason}"},
                }} for edge in path.edges
            ]}]}],
        }
        if resource:
            result["locations"] = [location(resource, diff.after.graph)]
        results.append(result)
    if decision.decision is Decision.BLOCK:
        results.append({
            "ruleId": "BR003", "ruleIndex": 2, "level": "error",
            "message": {"text": decision.headline + " " + "; ".join(decision.policy_notes)},
            "properties": {"attackPath": [], "severity": "HIGH",
                           "recommendation": "Resolve the listed gate violations and re-analyze."},
        })
    for phase, analysis in (("before", diff.before), ("after", diff.after)):
        for diagnostic in analysis.diagnostics:
            result = {
                "ruleId": "BR004", "ruleIndex": 3,
                "level": "warning" if diagnostic.blocks_analysis else "note",
                "message": {"text": f"{phase}: {diagnostic.code}: {diagnostic.message}"},
                "properties": {"phase": phase, **asdict(diagnostic)},
            }
            if diagnostic.resource:
                result["locations"] = [location(diagnostic.resource, analysis.graph)]
            elif diagnostic.source_file:
                result["locations"] = [{"physicalLocation": {"artifactLocation": {
                    "uri": quote(safe_source(diagnostic.source_file), safe="/")}}}]
            results.append(result)
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {"name": "BlastRadius", "version": __version__, "rules": RULES}},
            "results": results,
            "invocations": [{"executionSuccessful": True}],
            "properties": {"decision": decision.decision.value,
                           "analysisComplete": diff.complete,
                           "pathsTruncated": diff.before.paths_truncated or diff.after.paths_truncated,
                           "unsupportedResourceTypes": diff.after.graph.graph.get("unsupported", [])},
        }],
    }
