"""Local Git pull-request analysis (Phase 2)."""

import io
import subprocess

import pytest

from blastradius import gitsource
from blastradius.cli import run
from blastradius.graph import analyze, build_graph, compare
from blastradius.parser import parse_directory
from blastradius.security.decision import Decision, decide

from tests.conftest import SAFE_DIR, VULNERABLE_DIR


def _git(repo, *args):
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *args],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path):
    """A repository with `main` (safe) and `feature` (one-line risky change)."""
    root = tmp_path / "repo"
    (root / "infra").mkdir(parents=True)
    _git(root.parent, "init", "-q", "-b", "main", str(root))

    (root / "infra" / "main.tf").write_text(
        (SAFE_DIR / "main.tf").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (root / "README.md").write_text("not terraform\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "baseline")

    _git(root, "checkout", "-q", "-b", "feature")
    (root / "infra" / "main.tf").write_text(
        (VULNERABLE_DIR / "main.tf").read_text(encoding="utf-8"), encoding="utf-8"
    )
    _git(root, "commit", "-qam", "widen ssh")
    _git(root, "checkout", "-q", "main")
    return root


def _analyze(directory):
    return analyze(build_graph(parse_directory(directory)), str(directory))


# --- Happy path ------------------------------------------------------------
def test_prepare_comparison_materializes_both_refs(repo, tmp_path):
    comparison = gitsource.prepare_comparison(repo, "main", "feature", tmp_path / "work")
    assert comparison.terraform_dir == "infra"
    assert comparison.base_files == ["main.tf"] and comparison.head_files == ["main.tf"]
    assert comparison.base_sha != comparison.head_sha
    assert (comparison.before_dir / "main.tf").exists()
    assert (comparison.after_dir / "main.tf").exists()
    # Non-Terraform files are not materialized.
    assert not (comparison.before_dir / "README.md").exists()


def test_git_analysis_reproduces_the_directory_mode_result(repo, tmp_path):
    comparison = gitsource.prepare_comparison(repo, "main", "feature", tmp_path / "work")
    git_diff = compare(_analyze(comparison.before_dir), _analyze(comparison.after_dir))
    dir_diff = compare(_analyze(SAFE_DIR), _analyze(VULNERABLE_DIR))

    assert decide(git_diff).decision is Decision.BLOCK
    assert len(git_diff.new_critical_paths) == len(dir_diff.new_critical_paths) == 1
    assert git_diff.after.score == dir_diff.after.score
    assert [p.key for p in git_diff.new_critical_paths] == [
        p.key for p in dir_diff.new_critical_paths
    ]


def test_working_tree_is_not_modified(repo, tmp_path):
    before_status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=str(repo), capture_output=True, text=True
    ).stdout
    before_branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(repo), capture_output=True, text=True
    ).stdout

    gitsource.prepare_comparison(repo, "main", "feature", tmp_path / "work")

    after_status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=str(repo), capture_output=True, text=True
    ).stdout
    after_branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(repo), capture_output=True, text=True
    ).stdout
    assert before_status == after_status
    assert before_branch == after_branch == "main\n"


def test_commit_sha_is_accepted_as_a_ref(repo, tmp_path):
    sha = gitsource.resolve_ref(repo, "feature")
    comparison = gitsource.prepare_comparison(repo, "main", sha, tmp_path / "work")
    assert comparison.head_sha == sha


# --- Error handling --------------------------------------------------------
def test_not_a_git_repository(tmp_path):
    (tmp_path / "plain").mkdir()
    with pytest.raises(gitsource.NotAGitRepository):
        gitsource.prepare_comparison(tmp_path / "plain", "main", "feature", tmp_path / "work")


def test_missing_directory_is_reported_as_not_a_repository(tmp_path):
    with pytest.raises(gitsource.NotAGitRepository):
        gitsource.prepare_comparison(tmp_path / "nope", "main", "feature", tmp_path / "work")


def test_unknown_ref(repo, tmp_path):
    with pytest.raises(gitsource.RefNotFound) as error:
        gitsource.prepare_comparison(repo, "main", "does-not-exist", tmp_path / "work")
    assert "does-not-exist" in str(error.value)


def test_repository_without_terraform(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    _git(tmp_path, "init", "-q", "-b", "main", str(root))
    (root / "app.py").write_text("print('hi')\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "no terraform")

    with pytest.raises(gitsource.NoTerraformFiles):
        gitsource.prepare_comparison(root, "main", "main", tmp_path / "work")


def test_terraform_files_removed_in_candidate(repo, tmp_path):
    _git(repo, "checkout", "-q", "-b", "delete-infra")
    _git(repo, "rm", "-q", "infra/main.tf")
    _git(repo, "commit", "-qm", "remove terraform")
    _git(repo, "checkout", "-q", "main")

    with pytest.raises(gitsource.NoTerraformFiles) as error:
        gitsource.prepare_comparison(repo, "main", "delete-infra", tmp_path / "work")
    assert "removed" in str(error.value)


def test_terraform_files_added_in_candidate(repo, tmp_path):
    _git(repo, "checkout", "-q", "-b", "add-file")
    (repo / "infra" / "buckets.tf").write_text(
        'resource "aws_s3_bucket" "extra" {\n  bucket = "extra"\n}\n', encoding="utf-8"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "add bucket file")
    _git(repo, "checkout", "-q", "main")

    comparison = gitsource.prepare_comparison(repo, "main", "add-file", tmp_path / "work")
    assert comparison.added_files == ["buckets.tf"]
    assert comparison.removed_files == []
    assert "added: buckets.tf" in comparison.summary
    # The new file is part of the analysed configuration.
    assert _analyze(comparison.after_dir).graph.has_node("aws_s3_bucket.extra")


def test_ambiguous_terraform_directories(repo, tmp_path):
    _git(repo, "checkout", "-q", "-b", "two-dirs")
    (repo / "network").mkdir()
    (repo / "network" / "vpc.tf").write_text(
        'resource "aws_s3_bucket" "net" {\n  bucket = "net"\n}\n', encoding="utf-8"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "second terraform dir")
    _git(repo, "checkout", "-q", "main")

    with pytest.raises(gitsource.AmbiguousTerraformDir) as error:
        gitsource.prepare_comparison(repo, "main", "two-dirs", tmp_path / "work")
    assert "--terraform-dir" in str(error.value)

    # Explicitly choosing one resolves it.
    comparison = gitsource.prepare_comparison(
        repo, "main", "two-dirs", tmp_path / "work2", terraform_dir="infra"
    )
    assert comparison.terraform_dir == "infra"


def test_terraform_directories_listing(repo):
    assert gitsource.terraform_directories(repo, "main") == ["infra"]
    assert gitsource.list_terraform_files(repo, "main") == ["infra/main.tf"]


def test_is_git_repository(repo, tmp_path):
    assert gitsource.is_git_repository(repo)
    assert not gitsource.is_git_repository(tmp_path)


# --- CLI integration -------------------------------------------------------
def test_cli_git_mode_blocks(repo):
    stream = io.StringIO()
    code = run(["--repo", str(repo), "--base", "main", "--head", "feature"], stream=stream)
    output = stream.getvalue()
    assert code == 1
    assert "BLOCK CHANGE" in output
    assert "main -> feature" in output


def test_cli_git_mode_passes_in_reverse(repo):
    stream = io.StringIO()
    code = run(["--repo", str(repo), "--base", "feature", "--head", "main"], stream=stream)
    assert code == 0
    assert "SAFE TO MERGE" in stream.getvalue()


def test_cli_git_mode_requires_all_three_flags(repo):
    stream = io.StringIO()
    code = run(["--repo", str(repo), "--base", "main"], stream=stream)
    assert code == 2
    assert "must be used together" in stream.getvalue()


def test_cli_requires_some_input():
    stream = io.StringIO()
    code = run([], stream=stream)
    assert code == 2
    assert "--before/--after" in stream.getvalue()


def test_cli_git_mode_invalid_ref_exits_usage(repo):
    stream = io.StringIO()
    code = run(["--repo", str(repo), "--base", "main", "--head", "nope"], stream=stream)
    assert code == 2
    assert "Ref not found" in stream.getvalue()


def test_cli_git_mode_pr_format(repo):
    stream = io.StringIO()
    run(
        ["--repo", str(repo), "--base", "main", "--head", "feature", "--format", "pr"],
        stream=stream,
    )
    assert "BlastRadius Security Check" in stream.getvalue()
    assert "FAILED" in stream.getvalue()
