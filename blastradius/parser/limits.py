"""Deterministic input budgets shared by offline adapters."""

from pathlib import Path
import re

MAX_INPUT_BYTES = 4 * 1024 * 1024
MAX_FILES = 128
MAX_RESOURCES = 1000
MAX_DEPTH = 64
MAX_VALUES = 100_000

_TOKENS = re.compile(
    r'(?P<heredoc><<[-~]?(?P<marker>\w+)\r?\n.*?^\s*(?P=marker)\s*$)'
    r'|"(?:\\.|[^"\\])*"|//[^\n]*|\#[^\n]*|/\*.*?\*/|(?P<bracket>[{}\[\]()])',
    re.MULTILINE | re.DOTALL,
)


class InputLimitError(ValueError):
    """The input exceeds the documented static analysis budget."""


def read_bounded(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path.name}")
    if path.is_symlink() or not path.is_file():
        raise InputLimitError(f"Input must be a regular, non-symlink file: {path.name}")
    with path.open("rb") as handle:
        raw = handle.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise InputLimitError(f"Input exceeds {MAX_INPUT_BYTES} bytes: {path.name}")
    return raw.decode("utf-8")


def check_text_depth(text: str) -> None:
    depth = 0
    for token in _TOKENS.finditer(text):
        bracket = token.group("bracket")
        if bracket in ("{", "[", "("):
            depth += 1
            if depth > MAX_DEPTH:
                raise InputLimitError(f"Input nesting exceeds {MAX_DEPTH}")
        elif bracket in ("}", "]", ")"):
            depth -= 1


def check_structure(value: object) -> None:
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if count > MAX_VALUES or depth > MAX_DEPTH:
            raise InputLimitError("Input structure exceeds value or nesting budget")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend((child, depth + 1) for child in item)
