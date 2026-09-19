"""Terraform (HCL) parsing and normalization.

python-hcl2 gives us a faithful but awkward representation: string literals keep
their surrounding quotes, heredocs keep their `<<MARKER` wrapper, and
interpolations arrive as `${aws_s3_bucket.data.arn}`. This module flattens all
of that into plain Python values so the rest of BlastRadius never has to think
about HCL again.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Union

import hcl2

from blastradius.parser.models import ParsedConfig, TerraformResource

# Resource types the MVP understands. Anything else is ignored rather than
# guessed at, so the graph never contains resources we cannot reason about.
SUPPORTED_TYPES = (
    "aws_security_group",
    "aws_instance",
    "aws_iam_role",
    "aws_iam_instance_profile",
    "aws_iam_role_policy",
    "aws_iam_policy",
    "aws_iam_role_policy_attachment",
    "aws_s3_bucket",
    "aws_s3_bucket_policy",
    "aws_s3_bucket_acl",
)

_HEREDOC_RE = re.compile(r"^<<[-~]?(?P<marker>\w+)\r?\n(?P<body>.*?)\r?\n?(?P=marker)\s*$", re.DOTALL)
_INTERPOLATION_RE = re.compile(r"^\$\{(?P<expr>[^{}]+)\}$")
_REFERENCE_RE = re.compile(r"\b(aws_[a-z0-9_]+)\.([A-Za-z_][A-Za-z0-9_-]*)")

PathLike = Union[str, Path]


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


def _normalize_scalar(value: str) -> str:
    """Strip HCL packaging (quotes, heredoc markers, lone interpolations)."""
    value = _unquote(value)
    heredoc = _HEREDOC_RE.match(value)
    if heredoc:
        return heredoc.group("body")
    interpolation = _INTERPOLATION_RE.match(value)
    if interpolation:
        return interpolation.group("expr").strip()
    return value


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return _normalize_scalar(value)
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {
            _unquote(key): _normalize(item)
            for key, item in value.items()
            if key not in ("__is_block__", "__comments__", "__start_line__", "__end_line__")
        }
    return value


def references(value: Any) -> List[str]:
    """Return every `aws_type.name` Terraform address mentioned inside `value`.

    Works on strings, lists and nested dicts, which is what lets us follow
    `iam_instance_profile = aws_iam_instance_profile.app.name` and IAM policy
    resource ARNs without implementing a Terraform expression evaluator.
    """
    found: List[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str):
            for rtype, rname in _REFERENCE_RE.findall(node):
                address = f"{rtype}.{rname}"
                if address not in found:
                    found.append(address)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for item in node.values():
                walk(item)

    walk(value)
    return found


def parse_policy_document(raw: Any) -> Dict[str, Any]:
    """Parse an IAM policy that was written as a heredoc JSON document.

    Returns an empty dict when the policy is not parseable JSON (for example a
    `jsonencode(...)` expression), so callers degrade gracefully instead of
    crashing mid-demo.
    """
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def policy_statements(policy: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normalize `Statement` to always be a list of dicts."""
    statements = policy.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]
    return [s for s in statements if isinstance(s, dict)]


def as_list(value: Any) -> List[Any]:
    """Coerce an HCL/JSON value that may be a scalar or a list into a list."""
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def parse_file(path: PathLike) -> ParsedConfig:
    """Parse a single `.tf` file."""
    return _parse_files([Path(path)], source_dir=str(Path(path).parent))


def parse_directory(path: PathLike) -> ParsedConfig:
    """Parse every `.tf` file in a directory (non-recursive, like Terraform)."""
    directory = Path(path)
    if not directory.is_dir():
        raise NotADirectoryError(f"Not a Terraform directory: {directory}")
    files = sorted(directory.glob("*.tf"))
    if not files:
        raise FileNotFoundError(f"No .tf files found in {directory}")
    return _parse_files(files, source_dir=str(directory))


def _parse_files(files: Iterable[Path], source_dir: str) -> ParsedConfig:
    resources: List[TerraformResource] = []
    unsupported = set()
    for file_path in files:
        with file_path.open("r", encoding="utf-8") as handle:
            document = hcl2.load(handle)
        for block in document.get("resource", []):
            for raw_type, bodies in block.items():
                resource_type = _unquote(raw_type)
                if resource_type not in SUPPORTED_TYPES:
                    unsupported.add(resource_type)
                    continue
                for raw_name, body in bodies.items():
                    resources.append(
                        TerraformResource(
                            type=resource_type,
                            name=_unquote(raw_name),
                            attributes=_normalize(body),
                            source_file=str(file_path),
                        )
                    )
    # Deterministic ordering keeps graphs and screenshots stable across runs.
    resources.sort(key=lambda r: (SUPPORTED_TYPES.index(r.type), r.name))
    return ParsedConfig(resources=resources, source_dir=source_dir, unsupported=sorted(unsupported))
