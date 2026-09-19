"""Terraform (HCL) parsing and normalization.

python-hcl2 gives us a faithful but awkward representation: string literals keep
their surrounding quotes, heredocs keep their `<<MARKER` wrapper, and
interpolations arrive as `${aws_s3_bucket.data.arn}`. This module flattens all
of that into plain Python values so the rest of BlastRadius never has to think
about HCL again.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, List, Union

import hcl2

from blastradius.parser.models import Diagnostic, ParsedConfig, TerraformResource
from blastradius.parser.coverage import config_diagnostics
from blastradius.parser.limits import (
    MAX_FILES, MAX_INPUT_BYTES, MAX_RESOURCES, InputLimitError,
    check_structure, check_text_depth, read_bounded,
)
from blastradius.parser.values import (
    as_list as as_list, parse_policy_document as parse_policy_document,
    policy_statements as policy_statements, references as references,
)

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
    "aws_s3_bucket_public_access_block",
)

_HEREDOC_RE = re.compile(r"^<<[-~]?(?P<marker>\w+)\r?\n(?P<body>.*?)\r?\n?(?P=marker)\s*$", re.DOTALL)
_INTERPOLATION_RE = re.compile(r"^\$\{(?P<expr>[^{}]+)\}$")

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
    config = _parse_files(files, source_dir=str(directory))
    if next(directory.glob("*.tf.json"), None) is not None:
        config.diagnostics.append(Diagnostic("UNSUPPORTED_HCL_JSON",
            "Terraform .tf.json files are not modeled; supply a full Terraform plan JSON."))
    return config


def _parse_files(files: Iterable[Path], source_dir: str) -> ParsedConfig:
    resources: List[TerraformResource] = []
    unsupported = set()
    diagnostics = []
    total_bytes = 0
    resource_count = 0
    for file_count, file_path in enumerate(files, 1):
        if file_count > MAX_FILES:
            raise InputLimitError(f"Input exceeds {MAX_FILES} Terraform files")
        text = read_bounded(file_path)
        total_bytes += len(text.encode("utf-8"))
        if total_bytes > MAX_INPUT_BYTES:
            raise InputLimitError(f"Terraform root exceeds {MAX_INPUT_BYTES} bytes")
        check_text_depth(text)
        try:
            document = hcl2.loads(text)
        except RecursionError as error:
            raise InputLimitError("HCL parser nesting budget exceeded") from error
        check_structure(document)
        if document.get("module"):
            diagnostics.append(Diagnostic("UNEXPANDED_MODULE", "HCL modules are not downloaded or expanded.",
                                          source_file=file_path.name))
        for block in document.get("resource", []):
            for raw_type, bodies in block.items():
                resource_count += len(bodies)
                if resource_count > MAX_RESOURCES:
                    raise InputLimitError(f"Input exceeds {MAX_RESOURCES} resources")
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
                            source_file=file_path.name,
                        )
                    )
    # Deterministic ordering keeps graphs and screenshots stable across runs.
    resources.sort(key=lambda r: (SUPPORTED_TYPES.index(r.type), r.name))
    config = ParsedConfig(resources=resources, source_dir=source_dir,
                          unsupported=sorted(unsupported), diagnostics=diagnostics)
    config.diagnostics = config_diagnostics(config)
    return config
