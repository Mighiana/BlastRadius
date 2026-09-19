from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from check_docs import anchors, check_file
from check_integration import check

ROOT = Path(__file__).resolve().parents[1]


def test_docs_detect_missing_file_and_anchor(tmp_path: Path) -> None:
    source = tmp_path / "README.md"
    source.write_text("[Missing](missing.md)\n[Wrong](#absent)\n", encoding="utf-8")
    assert len(check_file(source, tmp_path)) == 2


def test_docs_accept_relative_links_and_explicit_legacy_anchors(tmp_path: Path) -> None:
    source = tmp_path / "README.md"
    source.write_text(
        '# Title\n<a id="legacy"></a>\n[Old](#legacy)\n[Self](README.md#title)\n',
        encoding="utf-8",
    )
    assert check_file(source, tmp_path) == []


def test_docs_ignore_examples_and_external_links(tmp_path: Path) -> None:
    source = tmp_path / "README.md"
    source.write_text(
        '```markdown\n[Example](missing.md)\n```\n[Docs](https://example.com)\n',
        encoding="utf-8",
    )
    assert check_file(source, tmp_path) == []


def test_docs_handle_duplicate_headings() -> None:
    assert anchors("# Example\n# Example\n") == {"example", "example-1"}


def test_docs_report_paths_outside_repo(tmp_path: Path) -> None:
    source = tmp_path / "README.md"
    source.write_text("[Outside](../private.md)\n", encoding="utf-8")
    assert "escapes repository" in check_file(source, tmp_path)[0]


def test_integration_rejects_incomplete_checkout(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    assert len(check(tmp_path)) == 4


def test_integration_accepts_complete_contract(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project.optional-dependencies]\nserver=["fastapi"]\n', encoding="utf-8"
    )
    (tmp_path / "blastradius/server").mkdir(parents=True)
    (tmp_path / "blastradius/server/app.py").touch()
    (tmp_path / "web").mkdir()
    (tmp_path / "web/package.json").write_text(
        '{"scripts":{"lint":"lint","typecheck":"typecheck","build":"build"}}', encoding="utf-8"
    )
    (tmp_path / "web/package-lock.json").write_text("{}", encoding="utf-8")
    assert check(tmp_path) == []


@pytest.mark.parametrize("package", ["[]", '{"scripts":[]}', '{"scripts":{"lint":false}}'])
def test_integration_rejects_invalid_script_metadata(tmp_path: Path, package: str) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project.optional-dependencies]\nserver=["fastapi"]\n', encoding="utf-8"
    )
    (tmp_path / "blastradius/server").mkdir(parents=True)
    (tmp_path / "blastradius/server/app.py").touch()
    (tmp_path / "web").mkdir()
    (tmp_path / "web/package.json").write_text(package, encoding="utf-8")
    (tmp_path / "web/package-lock.json").write_text("{}", encoding="utf-8")
    assert check(tmp_path)


def test_migration_requires_real_config() -> None:
    env = dict(os.environ, BLASTRADIUS_ALEMBIC_CONFIG="")
    result = subprocess.run(
        ["sh", str(ROOT / "scripts/container-entrypoint.sh"), "migrate"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "existing Alembic config" in result.stderr


def test_startup_rejects_unrecognized_command() -> None:
    result = subprocess.run(
        ["sh", str(ROOT / "scripts/container-entrypoint.sh"), "unknown"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2


@pytest.mark.parametrize(
    "name",
    [
        ".github/workflows/blastradius.yml",
        ".github/workflows/blastradius-hosted-test.yml",
        "docs/github-action.yml",
    ],
)
def test_workflow_actions_are_immutable_and_credentials_not_persisted(name: str) -> None:
    workflow = yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            if "uses" in step:
                assert re.fullmatch(r"[\w/-]+@[0-9a-f]{40}", step["uses"])
                if step["uses"].startswith("actions/checkout@"):
                    assert step["with"]["persist-credentials"] is False


def test_onboarding_workflow_preserves_candidate_data_only_boundary() -> None:
    text = (ROOT / "docs/github-action.yml").read_text(encoding="utf-8")
    assert "pull_request_target" not in text
    assert "ref: ${{ github.event.pull_request.base.sha }}" in text
    assert 'fetch --no-tags origin "refs/pull/$PR_NUMBER/head"' in text
    assert "-I -m blastradius.cli" in text
    assert "-I -m blastradius.github_pr" in text
    assert "a72c04890640102b315506ab85e5f1ccbe91bb9f" in text
    assert "working-directory: ${{ runner.temp }}" in text
    assert "git checkout" not in text
    assert "if: always()" in text
    assert '*) echo "::error::BlastRadius analysis did not complete successfully."; exit 2 ;;' in text
