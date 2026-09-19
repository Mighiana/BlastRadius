"""Private, bounded workspaces for the legacy Streamlit demo."""

from __future__ import annotations

import os
import re
import shutil
import stat
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SESSION_TTL_SECONDS = 24 * 60 * 60
MAX_SESSIONS = 128
MAX_JOBS_PER_SESSION = 8
MAX_TERRAFORM_FILES = 32
MAX_FILE_BYTES = 512 * 1024
MAX_INPUT_BYTES = 2 * 1024 * 1024
_SESSION_NAME = re.compile(r"session-[a-z0-9_]{8}")
_JOB_NAME = re.compile(r"(simulation|remediation|git)-[a-z0-9_]{8}")
_LOCK = threading.RLock()


class StorageError(ValueError):
    """A workspace or input failed the demo's filesystem boundary."""


def trusted_local_enabled() -> bool:
    return os.environ.get("BLASTRADIUS_TRUSTED_LOCAL", "") == "1"


def checked_path(path: str | Path) -> Path:
    """Reject traversal and symlinks before resolving an existing local path."""
    raw = str(path)
    candidate = Path(path)
    if not raw or "\x00" in raw or "\\" in raw or ".." in candidate.parts:
        raise StorageError("Traversal and ambiguous paths are not allowed.")
    absolute = candidate.absolute()
    for component in (*reversed(absolute.parents), absolute):
        if component.is_symlink():
            raise StorageError("Symbolic links are not allowed.")
    return absolute.resolve(strict=True)


def storage_root() -> Path:
    return Path(
        os.environ.get(
            "BLASTRADIUS_DEMO_STORAGE_ROOT",
            str(Path.home() / ".cache" / "blastradius" / "legacy-sessions"),
        )
    )


def _private_directory(path: Path) -> Path:
    if ".." in path.parts or "\\" in str(path):
        raise StorageError("Invalid workspace root.")
    for component in (*reversed(path.absolute().parents), path.absolute()):
        if component.is_symlink():
            raise StorageError("Workspace paths cannot contain symbolic links.")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    resolved = checked_path(path)
    mode = resolved.stat().st_mode
    if not stat.S_ISDIR(mode) or (os.name != "nt" and mode & 0o077):
        raise StorageError("Workspace directories must be private (mode 0700).")
    return resolved


def cleanup_expired(root: Path, *, now: float | None = None) -> int:
    """Remove only recognized session directories idle for at least one day."""
    with _LOCK:
        root = _private_directory(root)
        cutoff = (time.time() if now is None else now) - SESSION_TTL_SECONDS
        removed = 0
        for entry in root.iterdir():
            if not _SESSION_NAME.fullmatch(entry.name) or entry.is_symlink():
                continue
            try:
                if entry.is_dir() and entry.stat().st_mtime <= cutoff:
                    shutil.rmtree(entry)
                    removed += 1
            except FileNotFoundError:
                continue
        return removed


def validate_terraform_directory(directory: Path) -> Path:
    directory = checked_path(directory)
    if not directory.is_dir():
        raise StorageError("Choose a Terraform directory.")
    files = sorted(directory.glob("*.tf"))
    if not files:
        raise StorageError("No Terraform files found in the selected directory.")
    if len(files) > MAX_TERRAFORM_FILES:
        raise StorageError(
            f"The legacy demo supports at most {MAX_TERRAFORM_FILES} Terraform files."
        )
    total = 0
    for entry in files + [
        directory / "blastradius.yml",
        directory / "blastradius.yaml",
    ]:
        if not entry.exists() and not entry.is_symlink():
            continue
        checked_path(entry)
        info = entry.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise StorageError("Inputs must be regular files without links.")
        if info.st_size > MAX_FILE_BYTES:
            raise StorageError("An input file exceeds the legacy demo's 512 KiB limit.")
        total += info.st_size
    if total > MAX_INPUT_BYTES:
        raise StorageError("Inputs exceed the legacy demo's 2 MiB limit.")
    return directory


@dataclass(frozen=True)
class SessionWorkspace:
    root: Path
    directory: Path

    @classmethod
    def create(cls, root: Path | None = None) -> SessionWorkspace:
        with _LOCK:
            root = _private_directory(root if root is not None else storage_root())
            cleanup_expired(root)
            sessions = [
                p
                for p in root.iterdir()
                if _SESSION_NAME.fullmatch(p.name) and p.is_dir() and not p.is_symlink()
            ]
            if len(sessions) >= MAX_SESSIONS:
                raise StorageError(
                    "The demo is at session capacity. Please try again later."
                )
            directory = Path(tempfile.mkdtemp(prefix="session-", dir=root))
            return cls(root=root, directory=directory)

    def touch(self) -> None:
        with _LOCK:
            directory = checked_path(self.directory)
            if directory.parent != self.root or not _SESSION_NAME.fullmatch(
                directory.name
            ):
                raise StorageError("Invalid session workspace.")
            os.utime(directory, None, follow_symlinks=False)

    def owns(self, path: Path) -> bool:
        relative = (
            path.relative_to(self.directory)
            if path.is_relative_to(self.directory)
            else None
        )
        return bool(
            relative and relative.parts and _JOB_NAME.fullmatch(relative.parts[0])
        )

    def validate_input(
        self, path: Path, bundled: Iterable[Path], *, trusted: bool = False
    ) -> Path:
        directory = checked_path(path)
        owned = self.owns(directory)
        if directory.is_relative_to(self.root) and not owned:
            raise StorageError("Another session's files cannot be accessed.")
        if not owned and directory not in bundled and not trusted:
            raise StorageError(
                "Hosted demo inputs are limited to bundled scenarios and this session."
            )
        return validate_terraform_directory(directory)

    def prune(self, keep: Iterable[Path] = (), *, reserve: int = 0) -> None:
        with _LOCK:
            self.touch()
            protected = tuple(keep)
            jobs = sorted(
                (
                    p
                    for p in self.directory.iterdir()
                    if _JOB_NAME.fullmatch(p.name) and p.is_dir() and not p.is_symlink()
                ),
                key=lambda p: p.stat().st_mtime_ns,
                reverse=True,
            )
            survivors = {p for p in jobs if any(k.is_relative_to(p) for k in protected)}
            if len(survivors) > MAX_JOBS_PER_SESSION - reserve:
                raise StorageError("Too many active demo snapshots.")
            for job in jobs:
                if job in survivors:
                    continue
                if len(survivors) < MAX_JOBS_PER_SESSION - reserve:
                    survivors.add(job)
                else:
                    shutil.rmtree(job)

    def new_job(self, purpose: str, keep: Iterable[Path] = ()) -> Path:
        if purpose not in ("simulation", "remediation", "git"):
            raise StorageError("Unknown workspace purpose.")
        with _LOCK:
            self.prune(keep, reserve=1)
            return Path(tempfile.mkdtemp(prefix=f"{purpose}-", dir=self.directory))

    def discard_job(self, directory: Path) -> None:
        with _LOCK:
            directory = checked_path(directory)
            if directory.parent != self.directory or not self.owns(directory):
                raise StorageError("Only this session's jobs can be removed.")
            shutil.rmtree(directory)

    def close(self) -> None:
        with _LOCK:
            self.touch()
            shutil.rmtree(self.directory)
