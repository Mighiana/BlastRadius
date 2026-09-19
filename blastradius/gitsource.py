"""Read Terraform from two Git refs without touching the working tree.

Only read-only plumbing commands are used (`rev-parse`, `ls-tree`, `show`), and
file contents are written to caller-provided temporary directories. Nothing is
checked out, stashed, or modified, so this is safe to run on a repository the
developer is actively working in.
"""

from __future__ import annotations

import posixpath
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

GIT_TIMEOUT_SECONDS = 30


class GitAnalysisError(Exception):
    """Base class for user-facing Git problems."""


class NotAGitRepository(GitAnalysisError):
    pass


class RefNotFound(GitAnalysisError):
    pass


class NoTerraformFiles(GitAnalysisError):
    pass


class AmbiguousTerraformDir(GitAnalysisError):
    pass


def _run(repo: Path, args: Sequence[str], binary: bool = False) -> str | bytes:
    """Run a read-only git command inside `repo`."""
    try:
        completed = subprocess.run(
            ["git", "--no-pager", *args],
            cwd=str(repo),
            capture_output=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as error:  # pragma: no cover - git missing
        raise GitAnalysisError("git executable not found on PATH") from error
    except subprocess.TimeoutExpired as error:  # pragma: no cover - pathological repo
        raise GitAnalysisError(f"git command timed out: {' '.join(args)}") from error

    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", "replace").strip()
        raise GitAnalysisError(message or f"git {' '.join(args)} failed")
    return completed.stdout if binary else completed.stdout.decode("utf-8", "replace")


def is_git_repository(repo: Path | str) -> bool:
    try:
        output = _run(Path(repo), ["rev-parse", "--is-inside-work-tree"])
    except (GitAnalysisError, OSError):
        return False
    return str(output).strip() == "true"


def require_repository(repo: Path | str) -> Path:
    path = Path(repo)
    if not path.is_dir():
        raise NotAGitRepository(f"Not a directory: {path}")
    if not is_git_repository(path):
        raise NotAGitRepository(f"Not a Git repository: {path}")
    return path


def resolve_ref(repo: Path, ref: str) -> str:
    """Return the commit SHA for `ref`, or raise `RefNotFound`."""
    try:
        return str(_run(repo, ["rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}"])).strip()
    except GitAnalysisError as error:
        raise RefNotFound(f"Ref not found in repository: {ref}") from error


def list_terraform_files(repo: Path, ref: str) -> List[str]:
    """All `.tf` paths present at `ref`, as repo-relative POSIX paths."""
    sha = resolve_ref(repo, ref)
    output = str(_run(repo, ["ls-tree", "-rz", "--name-only", sha]))
    return sorted(path for path in output.split("\0") if path.endswith(".tf"))


def terraform_directories(repo: Path, ref: str) -> List[str]:
    """Directories that directly contain `.tf` files at `ref` ('.' for the root)."""
    directories = {posixpath.dirname(path) or "." for path in list_terraform_files(repo, ref)}
    return sorted(directories)


def _select_directory(
    repo: Path, base_ref: str, head_ref: str, terraform_dir: Optional[str]
) -> str:
    if terraform_dir:
        return terraform_dir.replace("\\", "/").strip("/") or "."

    candidates = sorted(
        set(terraform_directories(repo, base_ref)) | set(terraform_directories(repo, head_ref))
    )
    if not candidates:
        raise NoTerraformFiles("No .tf files found in either ref")
    if len(candidates) > 1:
        raise AmbiguousTerraformDir(
            "Multiple Terraform directories found: "
            + ", ".join(candidates)
            + ". Choose one with --terraform-dir."
        )
    return candidates[0]


def materialize(repo: Path, ref: str, directory: str, target: Path) -> List[str]:
    """Write the `.tf` files of `directory` at `ref` into `target`.

    Returns the file names written. Terraform itself is non-recursive, so only
    files directly inside `directory` are extracted.
    """
    target.mkdir(parents=True, exist_ok=True)
    written: List[str] = []
    for path in list_terraform_files(repo, ref):
        parent = posixpath.dirname(path) or "."
        if parent != directory:
            continue
        content = _run(repo, ["show", f"{ref}:{path}"], binary=True)
        name = posixpath.basename(path)
        if "\\" in name or ":" in name or name in (".", ".."):
            raise GitAnalysisError(f"Unsafe snapshot filename: {path!r}")
        (target / name).write_bytes(content)  # type: ignore[arg-type]
        written.append(name)
    return sorted(written)


@dataclass
class GitComparison:
    """Two materialized Terraform snapshots plus what changed between them."""

    repo: Path
    base_ref: str
    head_ref: str
    base_sha: str
    head_sha: str
    terraform_dir: str
    before_dir: Path
    after_dir: Path
    base_files: List[str] = field(default_factory=list)
    head_files: List[str] = field(default_factory=list)

    @property
    def added_files(self) -> List[str]:
        return sorted(set(self.head_files) - set(self.base_files))

    @property
    def removed_files(self) -> List[str]:
        return sorted(set(self.base_files) - set(self.head_files))

    @property
    def common_files(self) -> List[str]:
        return sorted(set(self.base_files) & set(self.head_files))

    @property
    def summary(self) -> str:
        parts = [f"{self.base_ref} -> {self.head_ref}", f"dir: {self.terraform_dir}"]
        if self.added_files:
            parts.append(f"added: {', '.join(self.added_files)}")
        if self.removed_files:
            parts.append(f"removed: {', '.join(self.removed_files)}")
        return " | ".join(parts)


def base_policy(comparison: GitComparison):
    return policy_at_ref(comparison.repo, comparison.base_sha)


def policy_at_ref(repo, base_sha):
    import yaml
    from blastradius.policy import POLICY_FILENAMES, Policy, PolicyError, load_policy_data

    paths = str(_run(repo, [
        "ls-tree", "-rz", "--name-only", base_sha
    ])).split("\0")
    for filename in POLICY_FILENAMES:
        if filename not in paths:
            continue
        text = _run(repo, ["show", f"{base_sha}:{filename}"])
        try:
            return load_policy_data(yaml.safe_load(text), f"{base_sha}:{filename}")
        except yaml.YAMLError as error:
            raise PolicyError(f"Invalid policy at base ref: {error}") from error
    return Policy()


def prepare_comparison(
    repo: Path | str,
    base_ref: str,
    head_ref: str,
    workdir: Path | str,
    terraform_dir: Optional[str] = None,
) -> GitComparison:
    """Materialize both refs into `workdir` and describe the change.

    Raises a `GitAnalysisError` subclass with an actionable message for every
    expected failure: not a repo, unknown ref, no Terraform, or an ambiguous
    Terraform directory.
    """
    repository = require_repository(repo)
    base_sha = resolve_ref(repository, base_ref)
    head_sha = resolve_ref(repository, head_ref)

    directory = _select_directory(
        repository, base_sha, head_sha, terraform_dir or policy_at_ref(repository, base_sha).terraform_dir
    )

    root = Path(workdir)
    before_dir = root / "before"
    after_dir = root / "after"
    base_files = materialize(repository, base_sha, directory, before_dir)
    head_files = materialize(repository, head_sha, directory, after_dir)

    if not base_files and not head_files:
        raise NoTerraformFiles(
            f"No .tf files in '{directory}' at either {base_ref} or {head_ref}"
        )
    if not base_files:
        raise NoTerraformFiles(
            f"No .tf files in '{directory}' at base ref {base_ref} - "
            "BlastRadius needs a baseline to compare against"
        )
    if not head_files:
        raise NoTerraformFiles(
            f"All .tf files in '{directory}' were removed in {head_ref} - nothing to analyze"
        )

    return GitComparison(
        repo=repository,
        base_ref=base_ref,
        head_ref=head_ref,
        base_sha=base_sha,
        head_sha=head_sha,
        terraform_dir=directory,
        before_dir=before_dir,
        after_dir=after_dir,
        base_files=base_files,
        head_files=head_files,
    )
