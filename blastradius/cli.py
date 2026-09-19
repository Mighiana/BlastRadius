"""BlastRadius CI mode.

    python -m blastradius.cli --before examples/safe --after examples/vulnerable

Exit codes:
    0  no critical security regression (SAFE TO MERGE / REVIEW REQUIRED)
    1  critical security regression    (BLOCK CHANGE)
    2  usage or input error

This is what a CI pipeline would call on a pull request.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Sequence, TextIO

from blastradius import gitsource
from blastradius.policy import PolicyError, discover_policy, load_policy_file
from blastradius.graph import analyze, build_graph, compare
from blastradius.graph.diff_engine import GraphDiff
from blastradius.parser import parse_directory
from blastradius.parser.inputs import parse_input
from lark.exceptions import UnexpectedInput
from blastradius.parser.plan_parser import PlanParseError, parse_plan_pair
from blastradius.report import build_report
from blastradius.security.decision import DeploymentDecision, decide

EXIT_USAGE = 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m blastradius.cli",
        description=(
            "Compare two Terraform configurations and fail the build when the change "
            "opens a new path from the internet to sensitive data."
        ),
    )
    parser.add_argument("--policy", help="Explicit trusted blastradius.yml policy file")
    parser.add_argument("--before", help="Terraform directory before the change")
    parser.add_argument("--after", help="Terraform directory after the change")
    parser.add_argument("--repo", help="Git repository to analyze instead of two directories")
    parser.add_argument("--base", help="Base ref/branch (with --repo), e.g. main")
    parser.add_argument("--head", help="Candidate ref/branch (with --repo), e.g. my-feature")
    parser.add_argument(
        "--terraform-dir",
        help="Repo-relative directory holding the .tf files (with --repo)",
    )
    parser.add_argument(
        "--plan",
        help="Terraform plan JSON (`terraform show -json plan.out`); supplies both sides",
    )
    parser.add_argument(
        "--format",
        choices=("summary", "pr", "json", "sarif"),
        default="summary",
        help="Output format (default: summary)",
    )
    parser.add_argument(
        "--fail-on-review",
        action="store_true",
        help="Also exit non-zero for REVIEW REQUIRED, not only BLOCK CHANGE",
    )
    return parser


def _summary_lines(diff: GraphDiff, decision: DeploymentDecision) -> List[str]:
    lines = [
        "BlastRadius change-impact analysis",
        "=" * 40,
        f"Decision : {decision.decision.value}",
        f"Verdict  : {diff.verdict.value}",
        f"Score    : {diff.before.score} -> {diff.after.score} ({diff.score_delta:+d})",
        f"Risk     : {diff.before.risk_level.value} -> {diff.after.risk_level.value}",
        "",
        decision.headline,
        "",
        "Reasons:",
    ]
    for reason in decision.reasons:
        marker = "!" if reason.delta and reason.severity.rank >= 3 else "-"
        lines.append(f"  {marker} {reason.label}: {reason.detail}")

    if diff.new_critical_paths:
        lines.append("")
        lines.append("New critical attack path(s):")
        for path in diff.new_critical_paths:
            lines.append("  " + " -> ".join(diff.display_path(path)))
            for edge in path.edges:
                lines.append(f"      {edge.source} -> {edge.target}: {edge.reason}")

    if diff.removed_critical_paths:
        lines.append("")
        lines.append("Eliminated attack path(s):")
        for path in diff.removed_critical_paths:
            lines.append("  " + " -> ".join(diff.display_path(path, "before")))

    lines.extend(f"Policy: {note}" for note in decision.policy_notes)
    return lines


def _json_payload(diff: GraphDiff, decision: DeploymentDecision) -> dict:
    return {
        "decision": decision.decision.value,
        "passed": decision.passed,
        "policy_notes": decision.policy_notes,
        "verdict": diff.verdict.value,
        "score": {
            "before": diff.before.score,
            "after": diff.after.score,
            "delta": diff.score_delta,
        },
        "risk_level": {
            "before": diff.before.risk_level.value,
            "after": diff.after.risk_level.value,
        },
        "new_critical_paths": [diff.display_path(p) for p in diff.new_critical_paths],
        "removed_critical_paths": [
            diff.display_path(p, "before") for p in diff.removed_critical_paths
        ],
        "newly_exposed": diff.newly_exposed,
        "newly_reachable_sensitive": diff.newly_reachable_sensitive,
        "reasons": [
            {"label": r.label, "detail": r.detail, "delta": r.delta, "severity": r.severity.value}
            for r in decision.reasons
        ],
    }


def run(argv: Optional[Sequence[str]] = None, stream: Optional[TextIO] = None) -> int:
    """Run the CLI and return the process exit code."""
    out = stream or sys.stdout
    # The PR report contains status emoji; a Windows console defaults to cp1252
    # and would raise UnicodeEncodeError mid-pipeline.
    if stream is None and hasattr(out, "reconfigure"):
        try:
            out.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # pragma: no cover - exotic streams
            pass

    args = _build_parser().parse_args(argv)
    args.diagnostics = []
    args.resolved_policy = None
    if args.policy:
        try:
            args.resolved_policy = load_policy_file(args.policy)
        except PolicyError as error:
            print(f"error: {error}", file=out)
            return EXIT_USAGE

    git_mode = bool(args.repo or args.base or args.head)
    if git_mode and not (args.repo and args.base and args.head):
        print("error: --repo, --base and --head must be used together", file=out)
        return EXIT_USAGE
    if git_mode and (args.before or args.after):
        print("error: --repo cannot be combined with --before/--after", file=out)
        return EXIT_USAGE
    if args.plan and (git_mode or args.before or args.after):
        print("error: --plan cannot be combined with --before/--after or --repo", file=out)
        return EXIT_USAGE
    if not git_mode and not args.plan and not (args.before and args.after):
        print("error: provide --before/--after, --repo/--base/--head, or --plan", file=out)
        return EXIT_USAGE

    if args.plan:
        try:
            before_config, after_config = parse_plan_pair(args.plan)
        except PlanParseError as error:
            print(f"error: {error}", file=out)
            return EXIT_USAGE
        if after_config.unsupported:
            args.diagnostics.append(
                "outside current model coverage, ignored: " + ", ".join(after_config.unsupported)
            )
        before = analyze(build_graph(before_config), f"{args.plan} (prior state)")
        after = analyze(build_graph(after_config), f"{args.plan} (planned)")
        return _report(args, compare(before, after), None, None, out)

    with tempfile.TemporaryDirectory(prefix="blastradius-") as workdir:
        if git_mode:
            try:
                comparison = gitsource.prepare_comparison(
                    args.repo, args.base, args.head, workdir, args.terraform_dir
                )
                args.resolved_policy = args.resolved_policy or gitsource.base_policy(comparison)
            except (gitsource.GitAnalysisError, PolicyError) as error:
                print(f"error: {error}", file=out)
                return EXIT_USAGE
            before_dir, after_dir = comparison.before_dir, comparison.after_dir
            args.diagnostics.append(comparison.summary)
        else:
            before_dir, after_dir = Path(args.before), Path(args.after)

        try:
            before_config = parse_input(before_dir)
            after_config = parse_input(after_dir)
            if git_mode:
                for config in (before_config, after_config):
                    for resource in config.resources:
                        resource.source_file = (Path(comparison.terraform_dir) / Path(resource.source_file).name).as_posix()
            before = analyze(build_graph(before_config), str(before_dir))
            after = analyze(build_graph(after_config), str(after_dir))
        except (OSError, UnexpectedInput, PlanParseError) as error:
            print(f"error: {error}", file=out)
            return EXIT_USAGE

        return _report(args, compare(before, after), before_dir, after_dir, out)


def _report(
    args,
    diff: GraphDiff,
    before_dir: Optional[Path],
    after_dir: Optional[Path],
    out: TextIO,
) -> int:
    try:
        policy = args.resolved_policy or discover_policy(
            before_dir or Path(args.plan).parent, Path.cwd()
        )
    except PolicyError as error:
        print(f"error: {error}", file=out)
        return EXIT_USAGE
    decision = decide(diff, policy)
    if args.format not in ("json", "sarif"):
        for message in args.diagnostics:
            print(f"# {message}", file=out)

    if args.format == "pr":
        print(build_report(diff, decision, before_dir, after_dir), file=out)
    elif args.format == "json":
        import json

        payload = _json_payload(diff, decision)
        payload["diagnostics"] = args.diagnostics
        payload["unsupported_resource_types"] = diff.after.graph.graph.get("unsupported", [])
        print(json.dumps(payload, indent=2), file=out)
    elif args.format == "sarif":
        import json
        from blastradius.sarif import build_sarif

        print(json.dumps(build_sarif(diff, decision), indent=2), file=out)
    else:
        print("\n".join(_summary_lines(diff, decision)), file=out)

    if args.fail_on_review:
        return 0 if decision.decision.value == "SAFE TO MERGE" else 1
    return decision.exit_code


def main() -> None:  # pragma: no cover - thin wrapper
    sys.exit(run())


if __name__ == "__main__":  # pragma: no cover
    main()
