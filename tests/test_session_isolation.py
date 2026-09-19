"""Filesystem boundaries and independent legacy Streamlit sessions."""

from __future__ import annotations

import html
import json
import os
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

import app
from blastradius import session_storage, simulation
from blastradius.session_storage import (
    MAX_FILE_BYTES,
    MAX_INPUT_BYTES,
    MAX_JOBS_PER_SESSION,
    MAX_TERRAFORM_FILES,
    SESSION_TTL_SECONDS,
    SessionWorkspace,
    StorageError,
    checked_path,
    cleanup_expired,
    trusted_local_enabled,
    validate_terraform_directory,
)

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
SAFE = ROOT / "examples" / "safe"


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("BLASTRADIUS_DEMO_STORAGE_ROOT", str(tmp_path / "sessions"))
    monkeypatch.delenv("BLASTRADIUS_TRUSTED_LOCAL", raising=False)


def start_app() -> AppTest:
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not at.exception
    return at


def rendered(at: AppTest) -> str:
    return " ".join(block.value for block in at.markdown)


def terraform(
    directory: Path, text: str = 'resource "aws_s3_bucket" "test" {}'
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "main.tf").write_text(text, encoding="utf-8")
    return directory


def test_two_sessions_keep_simulation_and_remediation_independent():
    first, second = start_app(), start_app()
    first.button(key="restore_safe").click().run()
    second.button(key="restore_safe").click().run()
    first.button(key="simulate_risky").click().run()
    second.button(key="simulate_risky").click().run()
    first_risky = Path(first.session_state.after_dir)
    second_risky = Path(second.session_state.after_dir)
    assert first_risky != second_risky
    assert first_risky.parent != second_risky.parent
    first_content = (first_risky / "main.tf").read_bytes()
    second_content = (second_risky / "main.tf").read_bytes()
    assert first_content == second_content
    assert "BLOCK CHANGE" in rendered(first)
    assert "BLOCK CHANGE" in rendered(second)

    first.button(key="apply_fix").click().run()
    first_fixed = Path(first.session_state.after_dir)
    assert Path(first.session_state.before_dir) == first_risky
    assert first_fixed != first_risky
    assert (first_risky / "main.tf").read_bytes() == first_content
    assert (second_risky / "main.tf").read_bytes() == second_content
    assert "SAFE TO MERGE" in rendered(first)
    second.run()
    assert "BLOCK CHANGE" in rendered(second)
    assert not first.exception and not second.exception

    second.button(key="scenario_public_bucket").click().run()
    second.button(key="apply_fix_primary").click().run()
    assert "SAFE TO MERGE" in rendered(second)
    first.toggle(key="demo_mode").set_value(True).run()
    first.toggle(key="demo_mode").set_value(False).run()
    assert Path(first.session_state.before_dir) == first_risky
    assert Path(first.session_state.after_dir) == first_fixed
    assert "SAFE TO MERGE" in rendered(first)
    assert not first.exception and not second.exception


def test_analysis_reloads_content_even_if_timestamp_is_unchanged():
    at = start_app()
    at.button(key="restore_safe").click().run()
    at.button(key="simulate_risky").click().run()
    generated = Path(at.session_state.after_dir) / "main.tf"
    original_stat = generated.stat()
    generated.write_bytes((SAFE / "main.tf").read_bytes())
    os.utime(generated, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    at.run()
    assert not at.exception
    assert "SAFE TO MERGE" in rendered(at)


def test_hosted_mode_hides_paths_and_enforces_boundary_before_parsing(tmp_path):
    at = start_app()
    assert not at.text_input
    assert not any(button.key == "analyze_git" for button in at.button)
    outside = terraform(tmp_path / "private")
    at.session_state.before_dir = str(outside)
    with patch(
        "blastradius.parser.parse_directory",
        side_effect=AssertionError("must not read"),
    ):
        at.run()
    assert not at.exception
    assert at.error
    assert str(outside) not in at.error[0].value
    at.button(key="scenario_public_ssh").click().run()
    assert not at.exception
    assert "BLOCK CHANGE" in rendered(at)


def test_other_session_path_is_rejected_even_when_forged_in_state():
    first, second = start_app(), start_app()
    first.button(key="simulate_risky").click().run()
    second.session_state.after_dir = first.session_state.after_dir
    with patch(
        "blastradius.parser.parse_directory",
        side_effect=AssertionError("must not read"),
    ):
        second.run()
    assert not second.exception
    assert second.error


@pytest.mark.parametrize("setting", ["", "0", "true", "yes", "1"])
def test_only_explicit_local_opt_in_enables_paths(monkeypatch, setting):
    monkeypatch.setenv("BLASTRADIUS_TRUSTED_LOCAL", setting)
    assert trusted_local_enabled() is (setting == "1")


def test_trusted_local_ui_and_server_gate(monkeypatch, tmp_path):
    with (
        patch("app.gitsource.prepare_comparison") as prepare,
        patch("app.st.error") as error,
    ):
        app._run_git_comparison(str(ROOT), "main", "main", "examples/safe")
    prepare.assert_not_called()
    error.assert_called_once()

    monkeypatch.setenv("BLASTRADIUS_TRUSTED_LOCAL", "1")
    local = terraform(tmp_path / "custom", (SAFE / "main.tf").read_text())
    at = start_app()
    at.text_input(key="before_dir").set_value(str(local))
    at.text_input(key="after_dir").set_value(str(local))
    at.button(key="reanalyze").click().run()
    assert not at.exception
    assert "SAFE TO MERGE" in rendered(at)
    at.toggle(key="demo_mode").set_value(True).run()
    assert not at.text_input
    at.toggle(key="demo_mode").set_value(False).run()
    assert Path(at.session_state.after_dir) == local


def test_trusted_git_snapshots_belong_to_session(monkeypatch):
    monkeypatch.setenv("BLASTRADIUS_TRUSTED_LOCAL", "1")
    at = start_app()
    at.text_input(key="git_repo").set_value(str(ROOT))
    at.text_input(key="git_base").set_value("HEAD")
    at.text_input(key="git_head").set_value("HEAD")
    at.text_input(key="git_dir").set_value("examples/safe")
    at.button(key="analyze_git").click().run()
    assert not at.exception and not at.error
    before, after = Path(at.session_state.before_dir), Path(at.session_state.after_dir)
    assert before.parent == after.parent
    assert before.parent.parent == at.session_state.workspace.directory
    assert "SAFE TO MERGE" in rendered(at)


def test_path_allowlist_is_exact_and_never_allows_other_sessions(tmp_path):
    first, second = SessionWorkspace.create(), SessionWorkspace.create()
    own = terraform(first.new_job("simulation"))
    other = terraform(second.new_job("simulation"))
    assert first.validate_input(SAFE, [SAFE]) == SAFE
    assert first.validate_input(own, []) == own
    for trusted in (False, True):
        with pytest.raises(StorageError, match="Another session"):
            first.validate_input(other, [], trusted=trusted)
    sibling = terraform(tmp_path / "safe-extra")
    with pytest.raises(StorageError, match="Hosted demo"):
        first.validate_input(sibling, [SAFE])
    assert first.validate_input(sibling, [], trusted=True) == sibling


def test_generated_jobs_do_not_accumulate_stale_terraform():
    workspace = SessionWorkspace.create()
    first = workspace.new_job("simulation")
    simulation.simulate(SAFE, first, simulation.SIMULATIONS["public_ssh"])
    (first / "stale.tf").write_text('resource "aws_s3_bucket" "stale" {}')
    second = workspace.new_job("simulation", [first])
    simulation.simulate(SAFE, second, simulation.SIMULATIONS["public_ssh"])
    assert not (second / "stale.tf").exists()
    assert (first / "stale.tf").exists()


@pytest.mark.parametrize(
    "kind", ["directory", "ancestor", "file", "policy", "dangling"]
)
def test_symlink_inputs_are_rejected(tmp_path, kind):
    workspace = SessionWorkspace.create()
    real = terraform(tmp_path / "real")
    directory = real
    if kind == "directory":
        directory = tmp_path / "linked"
        directory.symlink_to(real, target_is_directory=True)
    elif kind == "ancestor":
        directory = terraform(real / "child")
        (tmp_path / "linked").symlink_to(real, target_is_directory=True)
        directory = tmp_path / "linked" / "child"
    else:
        name = "blastradius.yml" if kind == "policy" else "linked.tf"
        target = tmp_path / "missing" if kind == "dangling" else real / "main.tf"
        (real / name).symlink_to(target)
    with pytest.raises(StorageError, match="Symbolic links"):
        workspace.validate_input(directory, [], trusted=True)


@pytest.mark.parametrize(
    "relative", ["../outside", "safe/../outside", "safe\\..\\outside"]
)
def test_traversal_is_rejected(tmp_path, relative):
    with pytest.raises(StorageError, match="Traversal"):
        checked_path(tmp_path / relative)


def test_symlink_storage_root_and_public_root_are_rejected(tmp_path):
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(StorageError, match="symbolic links"):
        SessionWorkspace.create(alias)
    if os.name != "nt":
        real.chmod(0o755)
        with pytest.raises(StorageError, match="private"):
            SessionWorkspace.create(real)


def test_input_limits_and_nonregular_files(tmp_path):
    directory = terraform(tmp_path / "inputs")
    (directory / "main.tf").write_bytes(b" " * (MAX_FILE_BYTES + 1))
    with pytest.raises(StorageError, match="512 KiB"):
        validate_terraform_directory(directory)
    (directory / "main.tf").write_text("")
    for index in range(MAX_TERRAFORM_FILES):
        (directory / f"{index}.tf").write_text("")
    with pytest.raises(StorageError, match="at most"):
        validate_terraform_directory(directory)

    oversized = tmp_path / "oversized"
    oversized.mkdir()
    for index in range(MAX_INPUT_BYTES // MAX_FILE_BYTES + 1):
        (oversized / f"{index}.tf").write_bytes(b" " * MAX_FILE_BYTES)
    with pytest.raises(StorageError, match="2 MiB"):
        validate_terraform_directory(oversized)

    nonregular = terraform(tmp_path / "nonregular")
    (nonregular / "directory.tf").mkdir()
    with pytest.raises(StorageError, match="regular files"):
        validate_terraform_directory(nonregular)


def test_hard_links_are_rejected(tmp_path):
    directory = terraform(tmp_path / "inputs")
    os.link(directory / "main.tf", tmp_path / "alias.tf")
    with pytest.raises(StorageError, match="without links"):
        validate_terraform_directory(directory)


def test_retention_is_bounded_without_deleting_before_or_after():
    workspace = SessionWorkspace.create()
    before = workspace.new_job("simulation")
    after = workspace.new_job("remediation", [before])
    for _ in range(MAX_JOBS_PER_SESSION * 3):
        workspace.new_job("simulation", [before, after])
    assert before.is_dir() and after.is_dir()
    assert len(list(workspace.directory.iterdir())) == MAX_JOBS_PER_SESSION
    workspace.close()
    assert not workspace.directory.exists()


def test_cleanup_removes_expired_sessions_without_following_links(tmp_path):
    old, fresh = SessionWorkspace.create(), SessionWorkspace.create()
    external = terraform(tmp_path / "external")
    (old.new_job("simulation") / "symlink").symlink_to(
        external, target_is_directory=True
    )
    untouched = old.root / "not-a-session"
    untouched.mkdir()
    alias = old.root / "session-12345678"
    alias.symlink_to(external, target_is_directory=True)
    now = fresh.directory.stat().st_mtime
    os.utime(old.directory, (now - SESSION_TTL_SECONDS - 1,) * 2)
    os.utime(untouched, (now - SESSION_TTL_SECONDS - 1,) * 2)
    assert cleanup_expired(old.root, now=now) == 1
    assert not old.directory.exists()
    assert fresh.directory.is_dir() and external.is_dir() and untouched.is_dir()
    assert alias.is_symlink()


def test_session_capacity_fails_closed_without_eviction():
    with patch("blastradius.session_storage.MAX_SESSIONS", 2):
        first, second = SessionWorkspace.create(), SessionWorkspace.create()
        with pytest.raises(StorageError, match="capacity"):
            SessionWorkspace.create()
    assert first.directory.exists() and second.directory.exists()


def test_session_capacity_is_reported_without_an_app_exception():
    with patch("blastradius.session_storage.MAX_SESSIONS", 0):
        at = start_app()
    assert at.error
    assert "session capacity" in at.error[0].value


def test_expired_session_restarts_cleanly():
    at = start_app()
    at.button(key="simulate_risky").click().run()
    old = at.session_state.workspace
    old.close()
    at.run()
    assert not at.exception
    assert at.session_state.workspace.directory != old.directory
    assert Path(at.session_state.before_dir) == SAFE
    assert any("expired" in message.value for message in at.info)


def test_html_labels_and_evidence_are_escaped_without_mutating_analysis(
    vulnerable_result,
):
    payload = '<img src=x onerror="alert(1)">'
    path = vulnerable_result.critical_paths[0]
    node = vulnerable_result.node(path.nodes[1])
    node.name = payload
    edge = path.edges[0]
    edge.reason = payload
    edge.evidence = payload
    edge.terraform_resource = payload
    assert payload not in app.path_chip([payload])
    hops = app.render_hops(vulnerable_result, path)
    assert payload not in hops
    assert html.escape(payload) in hops

    document = app.safe_graph_html(vulnerable_result.graph, path.nodes, [], 470)
    node_match = re.search(r"nodes = new vis.DataSet\((\[.*?\])\);", document)
    edge_match = re.search(r"edges = new vis.DataSet\((\[.*?\])\);", document)
    assert node_match and edge_match
    nodes = json.loads(node_match.group(1))
    edges = json.loads(edge_match.group(1))
    assert all(payload not in item["title"] for item in nodes + edges)
    assert any(html.escape(payload) in item["title"] for item in nodes)
    assert any(html.escape(payload) in item["title"] for item in edges)
    assert node.name == payload and edge.reason == payload
    assert (
        "ResizeObserver" in document and "network.fit({animation: false})" in document
    )
    assert '"enabled": false' in document


def test_markdown_payloads_cannot_become_images_or_links():
    payload = "[link](https://example.com) ![image](https://example.com/a)"
    escaped = app.markdown_text(payload)
    assert "[link](" not in escaped
    assert "![image](" not in escaped


def test_invalid_purpose_and_cross_session_deletion_are_rejected():
    first, second = SessionWorkspace.create(), SessionWorkspace.create()
    other = second.new_job("simulation")
    with pytest.raises(StorageError, match="Unknown"):
        first.new_job("../escape")
    with pytest.raises(StorageError, match="Only this session"):
        first.discard_job(other)
    assert other.exists()


def test_private_storage_has_restrictive_permissions():
    workspace = SessionWorkspace.create()
    job = workspace.new_job("simulation")
    if os.name != "nt":
        assert all(
            path.stat().st_mode & 0o077 == 0
            for path in (workspace.root, workspace.directory, job)
        )
    assert workspace.root == session_storage.storage_root()
