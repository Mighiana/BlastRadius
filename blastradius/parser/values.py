"""Small, non-evaluating helpers for normalized Terraform values."""

import json
import re

from blastradius.parser.limits import check_structure, check_text_depth, InputLimitError

_REFERENCE_RE = re.compile(
    r"(?<![\w.])(aws_[a-z0-9_]+)\.([A-Za-z_][A-Za-z0-9_-]*)(?![\w\[-])"
)


class DuplicateKeyError(ValueError):
    """JSON has ambiguous duplicate object members."""


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError("JSON object contains duplicate keys")
        result[key] = value
    return result


def references(value: object) -> list[str]:
    found: list[str] = []
    pending = [value]
    while pending:
        node = pending.pop()
        if isinstance(node, str):
            for match in _REFERENCE_RE.finditer(node):
                address = f"{match[1]}.{match[2]}"
                if address not in found:
                    found.append(address)
        elif isinstance(node, list):
            pending.extend(reversed(node))
        elif isinstance(node, dict):
            pending.extend(reversed(list(node.values())))
    return found


def parse_policy_document(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    try:
        check_text_depth(raw)
        document = json.loads(raw, object_pairs_hook=unique_object)
        check_structure(document)
        return document if isinstance(document, dict) else {}
    except (json.JSONDecodeError, InputLimitError, RecursionError, DuplicateKeyError):
        return {}


def policy_statements(policy: dict) -> list[dict]:
    statements = policy.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]
    if not isinstance(statements, list):
        return []
    return [statement for statement in statements if isinstance(statement, dict)]


def as_list(value: object) -> list:
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]
