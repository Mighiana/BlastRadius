"""Check local Markdown links and anchors without sending content to a service."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def without_code(text: str) -> str:
    return re.sub(r"^```.*?^```\s*$", "", text, flags=re.MULTILINE | re.DOTALL)


def anchors(text: str) -> set[str]:
    result = set(re.findall(r'<a\s+id="([^"]+)"\s*>', text))
    counts: dict[str, int] = {}
    for heading in re.findall(r"^#{1,6}\s+(.+)$", without_code(text), re.MULTILINE):
        slug = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        result.add(f"{slug}-{count}" if count else slug)
    return result


def check_file(path: Path, root: Path) -> list[str]:
    errors = []
    text = path.read_text(encoding="utf-8")
    for link in LINK.findall(without_code(text)):
        url = urlsplit(link)
        if url.scheme or url.netloc:
            continue
        target = (path.parent / unquote(url.path)).resolve() if url.path else path.resolve()
        if not target.is_relative_to(root.resolve()):
            errors.append(f"{path.relative_to(root)}: link escapes repository: {link}")
        elif not target.exists():
            errors.append(f"{path.relative_to(root)}: missing target: {link}")
        elif url.fragment and target.suffix == ".md":
            if unquote(url.fragment) not in anchors(target.read_text(encoding="utf-8")):
                errors.append(f"{path.relative_to(root)}: missing anchor: {link}")
    return errors


def main() -> int:
    paths = [ROOT / name for name in ("README.md", "CONTRIBUTING.md", "SECURITY.md")]
    paths.extend(sorted((ROOT / "docs").rglob("*.md")))
    errors = [error for path in paths for error in check_file(path, ROOT)]
    for error in errors:
        print(error, file=sys.stderr)
    print(f"Checked local links in {len(paths)} Markdown files.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
