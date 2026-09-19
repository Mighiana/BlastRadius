"""Fail early when a checkout lacks the agreed application build contract."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
import zipfile
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


def check_wheel(root: Path, wheel: Path) -> list[str]:
    errors = []
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        for source in sorted((root / "blastradius").rglob("*.py")):
            name = source.relative_to(root).as_posix()
            if name not in names:
                errors.append(f"Wheel is missing {name}.")
            elif archive.read(name) != source.read_bytes():
                errors.append(f"Wheel has stale content for {name}.")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--wheel", nargs="?", const="",
        help="Verify package contents; defaults to the single dist/*.whl file.",
    )
    args = parser.parse_args()
    try:
        errors = check(ROOT)
        if args.wheel is not None:
            wheels = [Path(args.wheel)] if args.wheel else sorted((ROOT / "dist").glob("*.whl"))
            if len(wheels) != 1:
                errors.append("Provide one wheel path, or leave exactly one wheel in dist/.")
            else:
                errors.extend(check_wheel(ROOT, wheels[0]))
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"Invalid application build metadata: {exc}", file=sys.stderr)
        return 2
    for error in errors:
        print(error, file=sys.stderr)
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
