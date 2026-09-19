"""GitHub-style pull-request security report.

Renders a diff + decision as the comment BlastRadius would post on a pull
request. Pure text generation, so it is identical in the dashboard, in the CLI
and in any future CI integration.
"""

from __future__ import annotations

import difflib
import html
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

from blastradius.security.decision import Decision, DeploymentDecision, decide
from blastradius.parser.limits import MAX_FILES, MAX_INPUT_BYTES, read_bounded, InputLimitError
from blastradius.github_pr import MARKER

if TYPE_CHECKING:  # pragma: no cover
    from blastradius.graph.diff_engine import GraphDiff

TITLE = "BlastRadius Security Check"


def responsible_change(before_dir: Optional[Path], after_dir: Optional[Path]) -> str:
    """Summarise the Terraform edit responsible, as `old -> new` where possible.

    Falls back to a file list when the change is not a simple one-line edit.
    """
    if not before_dir or not after_dir:
        return ""
    try:
        before = _terraform_text(Path(before_dir)).splitlines()
        after = _terraform_text(Path(after_dir)).splitlines()
    except (OSError, ValueError):  # pragma: no cover - unreadable directory
        return ""

    removed = [line.strip() for line in difflib.unified_diff(before, after, n=0) if line.startswith("-") and not line.startswith("---")]
    added = [line.strip() for line in difflib.unified_diff(before, after, n=0) if line.startswith("+") and not line.startswith("+++")]
    removed = [line[1:].strip() for line in removed]
    added = [line[1:].strip() for line in added]

    if len(removed) == 1 and len(added) == 1:
        return f"{removed[0]} -> {added[0]}"
    if removed or added:
        return f"{len(removed)} line(s) removed, {len(added)} line(s) added"
    return "no textual change"


def _terraform_text(directory: Path) -> str:
    files = sorted(directory.glob("*.tf"))
    if len(files) > MAX_FILES:
        raise InputLimitError("Too many files for textual comparison")
    documents = []
    size = 0
    for path in files:
        text = read_bounded(path)
        size += len(text.encode("utf-8"))
        if size > MAX_INPUT_BYTES:
            raise InputLimitError("Textual comparison exceeds byte budget")
        documents.append(text)
    return "\n".join(documents)


def coverage_lines(diff: "GraphDiff") -> list[str]:
    lines = ["", "Analysis coverage: " + ("complete within documented model" if diff.complete else "INCOMPLETE")]
    for phase, result in (("before", diff.before), ("after", diff.after)):
        for item in result.diagnostics[:100]:
            location = ": ".join(part for part in (item.source_file, item.resource, item.attribute) if part)
            lines.append(f"- {_safe_markdown(phase)} [{item.code}] {_safe_markdown(location)}: {_safe_markdown(item.message)}")
        if len(result.diagnostics) > 100:
            lines.append(f"- {len(result.diagnostics) - 100} additional diagnostics; see JSON/SARIF.")
    return lines


def _metric_lines(diff: "GraphDiff") -> List[str]:
    lines: List[str] = []
    counts = (
        (len(diff.new_critical_paths), "critical attack path"),
        (len(diff.newly_exposed), "internet-reachable resource"),
        (len(diff.newly_reachable_sensitive), "sensitive resource reachable"),
    )
    for count, noun in counts:
        if count:
            plural = "" if count == 1 else "s"
            suffix = "" if noun.endswith("reachable") else plural
            lines.append(f"+{count} {noun}{suffix}")

    removed = len(diff.removed_critical_paths)
    if removed:
        lines.append(f"-{removed} critical attack path" + ("" if removed == 1 else "s"))
    return lines


def _recommendation(diff: "GraphDiff", decision: DeploymentDecision) -> str:
    if decision.decision is Decision.SAFE:
        return "No action required."
    if not diff.complete:
        return "Resolve coverage diagnostics and re-analyze; missing paths do not establish safety."

    changed = {(e.source, e.target) for e in diff.new_edges}
    for path in diff.new_critical_paths or diff.new_attack_paths:
        for edge in path.edges:
            if (edge.source, edge.target) not in changed:
                continue
            if edge.relationship.value == "PUBLIC_ACCESS":
                return "Remove public bucket access before merging."
            if "0.0.0.0/0" in edge.evidence or "0.0.0.0/0" in edge.reason:
                return "Restrict the public ingress CIDR before merging."
            if "s3:*" in edge.evidence or "all resources" in edge.reason:
                return "Scope the IAM policy to specific bucket ARNs before merging."
    if decision.decision is Decision.BLOCK:
        return "Resolve the blocking paths or repository policy violations before merging."
    return "Review the new internet-facing exposure before merging."


def build_report(
    diff: "GraphDiff",
    decision: Optional[DeploymentDecision] = None,
    before_dir: Optional[Path] = None,
    after_dir: Optional[Path] = None,
) -> str:
    """Render the full PR comment as markdown-ish plain text."""
    decision = decision or decide(diff)
    status = {
        Decision.SAFE: "PASSED",
        Decision.REVIEW: "REVIEW REQUIRED",
        Decision.BLOCK: "FAILED",
    }[decision.decision]
    mark = "\u26a0" if decision.decision is Decision.REVIEW else "\u2705" if decision.passed else "\u274c"

    lines = [TITLE, "", f"{mark} {status}", ""]

    if decision.decision is Decision.BLOCK:
        lines.append("This infrastructure change introduces a security regression."
                     if diff.is_regression else "Repository security policy blocks this change.")
    elif decision.decision is Decision.REVIEW:
        lines.append(decision.headline)
    elif diff.removed_critical_paths:
        lines.append("This infrastructure change removes an existing attack path.")
    else:
        lines.append("No new critical attack paths detected.")
    lines.append("")

    lines.append(f"Decision: {decision.decision.value}")
    lines.extend(f"Policy: {note}" for note in decision.policy_notes)
    lines.append(
        f"Security score: {diff.before.score} -> {diff.after.score} "
        f"({diff.score_delta:+d})"
    )
    lines.append("")

    metrics = _metric_lines(diff)
    if metrics:
        lines.extend(metrics)
        lines.append("")

    paths = diff.new_critical_paths or diff.new_attack_paths
    if paths:
        lines.append("Attack path:")
        for path in paths:
            lines.append("  " + " -> ".join(diff.display_path(path)))
        lines.append("")
    elif diff.removed_critical_paths:
        lines.append("Eliminated attack path:")
        for path in diff.removed_critical_paths:
            lines.append("  " + " -> ".join(diff.display_path(path, "before")))
        lines.append("")

    change = responsible_change(before_dir, after_dir)
    if change:
        lines.append("Responsible Terraform change:")
        lines.append(f"  {change}")
        lines.append("")

    lines.append("Recommendation:")
    lines.append(f"  {_recommendation(diff, decision)}")
    lines.extend(coverage_lines(diff))
    lines.append("")
    lines.append(
        "-- BlastRadius static attack-path analysis. Simplified AWS model; "
        "no infrastructure was deployed or accessed."
    )
    return "\n".join(lines)


def _safe_markdown(value):
    text = html.escape(str(value), quote=False).replace('@', '@\u200b')
    for character in ('\\', '`', '*', '_', '[', ']', '|', '#'):
        text = text.replace(character, '\\' + character)
    return text.replace('\r', ' ').replace('\n', ' ')


def build_pr_comment(diff, decision=None, before_dir=None, after_dir=None):
    decision = decision or decide(diff)
    paths = diff.new_critical_paths or diff.new_attack_paths
    coverage = sorted(set(diff.before.graph.graph.get('unsupported', [])) |
                      set(diff.after.graph.graph.get('unsupported', [])))
    lines = [MARKER, '## BlastRadius Security Check', '',
             f'**Decision: {decision.icon} {decision.decision.value}**', '',
             f'**Security score:** {diff.before.score} → {diff.after.score}',
             f'**New critical attack paths:** {len(diff.new_critical_paths)}',
             f'**Newly reachable sensitive resources:** {len(diff.newly_reachable_sensitive)}',
             f'**Newly internet-reachable resources:** {len(diff.newly_exposed)}', '']
    if paths:
        lines.append('**Attack path:**')
        for path in paths[:3]:
            lines.append('- ' + ' → '.join(_safe_markdown(n) for n in diff.display_path(path)))
        if len(paths) > 3:
            lines.append(f'- {len(paths) - 3} additional paths; see artifacts.')
    else:
        lines.append('No new modeled critical attack paths detected.')
    change = responsible_change(before_dir, after_dir)
    if change:
        lines.extend(['', '**Responsible infrastructure change:**', _safe_markdown(change)[:2000]])
    if decision.policy_notes:
        lines.extend(['', '**Policy:**'] + ['- ' + _safe_markdown(note) for note in decision.policy_notes[:8]])
    lines.extend(['', '**Recommendation:**', _recommendation(diff, decision)])
    if coverage:
        lines.extend(['', '**Outside current model coverage:** ' + ', '.join(_safe_markdown(c) for c in coverage)[:2000]])
    lines.extend(coverage_lines(diff))
    lines.extend(['', '_Simplified static AWS model, not proof of infrastructure safety. '
                  'Unsupported relationships and unknown values can hide paths. No AWS access or deployment._'])
    return '\n'.join(lines)
