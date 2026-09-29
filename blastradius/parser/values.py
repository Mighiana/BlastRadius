"""Small, non-evaluating helpers for normalized Terraform values."""

import json
import re
from functools import lru_cache

from blastradius.parser.expression import (
    ExpressionError,
    PolicyString,
    evaluate_expression,
    jsonencode_argument,
    traversal_addresses,
)
from blastradius.parser.limits import check_structure, check_text_depth, InputLimitError

_REFERENCE_RE = re.compile(
    r"(?<![\w.])(aws_[a-z0-9_]+)\.([A-Za-z_][A-Za-z0-9_-]*)(?![\w\[-])"
)
_JSON_INTERPOLATION = re.compile(r"(?<!\$)\$\{\s*(aws_[^}]*?)\s*\}")
_POLICY_CACHE_SIZE = 256


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
        if isinstance(node, PolicyString):
            found.extend(a for a in node.addresses if a not in found)
        elif isinstance(node, str):
            for match in _REFERENCE_RE.finditer(node):
                address = f"{match[1]}.{match[2]}"
                if address not in found:
                    found.append(address)
        elif isinstance(node, list):
            pending.extend(reversed(node))
        elif isinstance(node, dict):
            pending.extend(reversed(list(node.values())))
    return found


def policy_references(value: object) -> list[str]:
    """Resource addresses genuinely referenced by normalized policy values.

    Only ``PolicyString`` provenance counts; plain strings are literal text even
    when they look like Terraform addresses.
    """
    found: list[str] = []
    pending = [value]
    while pending:
        node = pending.pop()
        if isinstance(node, PolicyString):
            found.extend(a for a in node.addresses if a not in found)
        elif isinstance(node, list):
            pending.extend(reversed(node))
        elif isinstance(node, dict):
            pending.extend(reversed(list(node.values())))
    return found


def _with_provenance(node: object) -> object:
    """Mark JSON policy strings with the resources their ``${aws_*}`` templates name."""
    if isinstance(node, str):
        addresses: tuple[str, ...] = ()
        for match in _JSON_INTERPOLATION.finditer(node):
            addresses += traversal_addresses(match[1])
        return PolicyString(node, tuple(dict.fromkeys(addresses)))
    if isinstance(node, list):
        return [_with_provenance(item) for item in node]
    if isinstance(node, dict):
        return {key: _with_provenance(value) for key, value in node.items()}
    return node


def evaluate_policy_document(raw: object) -> tuple[dict | None, str | None]:
    """Normalize an IAM policy source into a canonical JSON-shaped document.

    Returns ``(document, unresolved_reason)``:

    - ``(dict, None)`` — fully normalized (heredoc/literal JSON, a dict value,
      or a supported ``jsonencode({...})`` literal).
    - ``(None, reason)`` — a ``jsonencode`` expression we could not completely
      evaluate (unsupported function, unresolved reference, malformed syntax).
      The reason is a short, bounded description safe for diagnostics.
    - ``(None, None)`` — not a policy document at all.
    """
    if isinstance(raw, dict):
        marked_raw = _with_provenance(raw)
        return (marked_raw if isinstance(marked_raw, dict) else None), None
    if not isinstance(raw, str):
        return None, None
    document, reason = _evaluate_policy_text(str(raw))
    copied = _copy_tree(document)
    return (copied if isinstance(copied, dict) else None), reason


def _copy_tree(node: object) -> object:
    """Fresh containers around shared immutable leaves, so cached documents stay pristine."""
    if isinstance(node, dict):
        return {key: _copy_tree(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_copy_tree(item) for item in node]
    return node


@lru_cache(maxsize=_POLICY_CACHE_SIZE)
def _evaluate_policy_text(raw: str) -> tuple[dict | None, str | None]:
    try:
        check_text_depth(raw)
        document = json.loads(raw, object_pairs_hook=unique_object)
        check_structure(document)
        if not isinstance(document, dict):
            return None, None
        marked = _with_provenance(document)
        return (marked if isinstance(marked, dict) else None), None
    except (json.JSONDecodeError, InputLimitError, RecursionError, DuplicateKeyError):
        pass
    argument = jsonencode_argument(raw)
    if argument is None:
        return None, None
    try:
        value, problems = evaluate_expression(argument)
        check_structure(value)
    except (ExpressionError, InputLimitError, RecursionError) as error:
        return None, f"expression could not be evaluated ({error})"
    if problems:
        return None, problems[0].reason
    if not isinstance(value, dict):
        return None, "jsonencode() did not produce an object"
    return value, None


def parse_policy_document(raw: object) -> dict:
    document, _unresolved = evaluate_policy_document(raw)
    return document or {}


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
