"""Fail early when a checkout lacks the agreed application build contract."""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(root: Path) -> list[str]:
    errors = []
    metadata = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    extras = metadata.get("project", {}).get("optional-dependencies", {})
    if "server" not in extras:
        errors.append("pyproject.toml must provide the server extra.")
    if not (root / "blastradius/server/app.py").is_file():
        errors.append("Missing blastradius.server.app:app implementation.")
    manifest = root / "web/package.json"
    if not manifest.is_file():
        errors.append("Missing web/package.json; integrate the frontend first.")
    else:
        package = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(package, dict):
            return [*errors, "web/package.json must be an object."]
        scripts = package.get("scripts")
        if not isinstance(scripts, dict):
            return [*errors, "web/package.json must provide a scripts object."]
        for name in ("lint", "typecheck", "build"):
            command = scripts.get(name)
            if not isinstance(command, str) or not command.strip():
                errors.append(f"web/package.json must provide npm run {name}.")
    if not (root / "web/package-lock.json").is_file():
        errors.append("Missing web/package-lock.json for reproducible npm ci.")
    return errors


def main() -> int:
    try:
        errors = check(ROOT)
    except (OSError, ValueError) as exc:
        print(f"Invalid application build metadata: {exc}", file=sys.stderr)
        return 2
    for error in errors:
        print(error, file=sys.stderr)
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
