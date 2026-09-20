"""Generate synthetic customer evidence using the installed analyzer."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import blastradius
from blastradius.security.hcl_edit import widen_admin_ingress
from blastradius.security.remediation import generate_safer_config, write_plan

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "examples/customer"
REVIEW_MODULE = '\nmodule "outside_model" {\n  source = "./not-executed"\n}\n'


@dataclass(frozen=True)
class Case:
    name: str
    before: str
    after: str | None
    expected_exit: int
    strict: bool = True


CASES = (
    Case("baseline", "before", "before", 0),
    Case("risky", "before", "after", 1),
    Case("remediated", "after", "remediated", 0),
    Case("review-default", "before", "review", 0, strict=False),
    Case("review-strict", "before", "review", 1),
    Case("error", "before", None, 2),
)


def engine_digest() -> str:
    package = Path(blastradius.__file__).parent
    files = [package / name for name in (
        "__init__.py", "cli.py", "actions_output.py", "report.py", "sarif.py",
        "policy.py", "gitsource.py", "github_context.py", "github_pr.py",
    )]
    for directory in ("parser", "graph", "security"):
        files.extend((package / directory).rglob("*.py"))
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.relative_to(package).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def generate(output: Path) -> None:
    before = (SAMPLES / "before/main.tf").read_text(encoding="utf-8")
    candidate, count = widen_admin_ingress(before)
    if count != 1:
        raise ValueError("Customer sample must contain exactly one restricted admin ingress.")
    write_text(output / "before/main.tf", before)
    write_text(output / "after/main.tf", candidate)
    write_text(output / "policy.yml", (SAMPLES / "policy.yml").read_text(encoding="utf-8"))
    write_text(output / "review/main.tf", before + REVIEW_MODULE)

    plan = generate_safer_config(output / "after")
    if not plan.can_autofix:
        raise ValueError("The installed engine did not generate the expected remediation.")
    write_plan(plan, output / "remediated", output / "after")
    if (output / "remediated/main.tf").read_text(encoding="utf-8") != before:
        raise ValueError("Remediation did not restore the baseline; inspect the engine output.")
    write_text(output / "remediation.patch", plan.diff)

    runs = []
    for case in CASES:
        arguments = ["--before", case.before, "--policy", "policy.yml"]
        if case.after is not None:
            arguments.extend(["--after", case.after])
        if case.strict:
            arguments.append("--fail-on-review")
        arguments.extend(["--report-dir", f"output/{case.name}"])
        result = subprocess.run(
            [sys.executable, "-I", "-m", "blastradius.cli", *arguments],
            cwd=output,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=60,
        )
        if result.returncode != case.expected_exit or result.stderr:
            raise RuntimeError(
                f"{case.name}: expected exit {case.expected_exit}, got {result.returncode}.\n"
                f"{result.stdout}\n{result.stderr}"
            )
        write_text(output / f"output/{case.name}/console.txt", result.stdout)
        runs.append({"case": case.name, "cli_args": arguments, "exit_code": result.returncode})
    manifest = {
        "analyzer_version": blastradius.__version__,
        "engine_source_sha256": engine_digest(),
        "invocation": "python -I -m blastradius.cli",
        "working_directory": "examples/customer",
        "runs": runs,
    }
    write_text(output / "manifest.json", json.dumps(manifest, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=SAMPLES)
    args = parser.parse_args()
    generate(args.output.resolve())
    print("Generated customer samples; verified exits: 0, 1, 0, 0, 1, 2.")


if __name__ == "__main__":
    main()
