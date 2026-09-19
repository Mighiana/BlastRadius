"""Terraform plan JSON parser.

Source-mode analysis answers "what relationships exist in these Terraform
files?". Plan-mode analysis answers "what change is Terraform actually
proposing?" - and one plan file contains *both* sides of that question, so a
single `terraform show -json plan.out` yields a full before/after comparison.

    terraform plan -out plan.out
    terraform show -json plan.out > plan.json

The output of this module is the same `ParsedConfig` the HCL parser produces,
so the graph builder, rules, scoring and diff engine are reused unchanged.

The hard part is that plan JSON stores *resolved values* (`sg-0a1b2c`), not
Terraform addresses. Relationships are recovered in two passes:

  1. `configuration.root_module.resources[].expressions[].references` - exact,
     and available even when a value is still unknown (new resources).
  2. value matching against an index of ids/names/ARNs - covers plans where the
     configuration block is absent (some `-json` producers omit it).

Recovered relationships are written back into the attributes in the same
`aws_type.name.attr` form the HCL parser emits, so nothing downstream has to
know which parser was used.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from blastradius.parser.models import ParsedConfig, TerraformResource
from blastradius.parser.terraform_parser import SUPPORTED_TYPES

PathLike = str | Path

# Attributes that hold a reference to another resource, and the attribute of
# the target that the HCL parser would have produced (`aws_x.y.<suffix>`).
_REFERENCE_ATTRS: Dict[Tuple[str, str], Tuple[Tuple[str, ...], str]] = {
    ("aws_instance", "vpc_security_group_ids"): (("aws_security_group",), "id"),
    ("aws_instance", "security_groups"): (("aws_security_group",), "name"),
    ("aws_instance", "iam_instance_profile"): (("aws_iam_instance_profile",), "name"),
    ("aws_iam_instance_profile", "role"): (("aws_iam_role",), "name"),
    ("aws_iam_role_policy", "role"): (("aws_iam_role",), "id"),
    ("aws_iam_role_policy_attachment", "role"): (("aws_iam_role",), "id"),
    ("aws_iam_role_policy_attachment", "policy_arn"): (("aws_iam_policy",), "arn"),
    ("aws_s3_bucket_acl", "bucket"): (("aws_s3_bucket",), "id"),
    ("aws_s3_bucket_policy", "bucket"): (("aws_s3_bucket",), "id"),
}

# Identifying attribute values used to match a resolved value back to a resource.
_IDENTITY_ATTRS = ("id", "arn", "name", "bucket")


class PlanParseError(ValueError):
    """The supplied file is not usable Terraform plan JSON."""


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def load_plan(path: PathLike) -> Dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise PlanParseError(f"Plan file not found: {path}") from error
    except json.JSONDecodeError as error:
        raise PlanParseError(f"Plan file is not valid JSON: {path} ({error})") from error
    if not isinstance(data, dict):
        raise PlanParseError(f"Plan file is not a JSON object: {path}")
    if "planned_values" not in data and "resource_changes" not in data:
        raise PlanParseError(
            f"{path} does not look like `terraform show -json` output "
            "(no planned_values or resource_changes)"
        )
    return data


def _iter_module_resources(module: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    """Walk a values module tree, including nested child modules."""
    for resource in module.get("resources", []) or []:
        yield resource
    for child in module.get("child_modules", []) or []:
        yield from _iter_module_resources(child)


def _values_resources(data: Dict[str, Any], phase: str) -> List[Dict[str, Any]]:
    """Resources for the requested phase, as `{address,type,name,values}` dicts."""
    if phase == "after":
        root = (data.get("planned_values") or {}).get("root_module") or {}
        resources = list(_iter_module_resources(root))
        if resources:
            return resources
        return _from_resource_changes(data, "after")

    prior = ((data.get("prior_state") or {}).get("values") or {}).get("root_module") or {}
    resources = list(_iter_module_resources(prior))
    if resources:
        return resources
    return _from_resource_changes(data, "before")


def _from_resource_changes(data: Dict[str, Any], side: str) -> List[Dict[str, Any]]:
    """Reconstruct one side of the change from `resource_changes`."""
    resources = []
    for change in data.get("resource_changes", []) or []:
        values = (change.get("change") or {}).get(side)
        if values is None:
            continue
        resources.append(
            {
                "address": change.get("address", ""),
                "type": change.get("type", ""),
                "name": change.get("name", ""),
                "mode": change.get("mode", "managed"),
                "values": values,
            }
        )
    return resources


# ---------------------------------------------------------------------------
# Relationship recovery
# ---------------------------------------------------------------------------
def _configuration_references(data: Dict[str, Any]) -> Dict[str, Dict[str, List[str]]]:
    """`{resource_address: {attribute: [referenced addresses]}}` from `configuration`."""
    result: Dict[str, Dict[str, List[str]]] = {}

    def walk(module: Dict[str, Any]) -> None:
        for resource in module.get("resources", []) or []:
            address = resource.get("address") or ""
            expressions = resource.get("expressions") or {}
            attributes: Dict[str, List[str]] = {}
            for attribute, expression in expressions.items():
                references = _expression_references(expression)
                if references:
                    attributes[attribute] = references
            if attributes:
                result[address] = attributes
        for call in (module.get("module_calls") or {}).values():
            nested = call.get("module")
            if nested:
                walk(nested)

    walk((data.get("configuration") or {}).get("root_module") or {})
    return result


def _expression_references(expression: Any) -> List[str]:
    """Pull `references` out of an expression, including list-nested ones."""
    references: List[str] = []
    if isinstance(expression, dict):
        for reference in expression.get("references", []) or []:
            if reference not in references:
                references.append(reference)
        for nested in expression.values():
            if isinstance(nested, (list, dict)):
                for item in _expression_references(nested):
                    if item not in references:
                        references.append(item)
    elif isinstance(expression, list):
        for item in expression:
            for reference in _expression_references(item):
                if reference not in references:
                    references.append(reference)
    return references


def _resource_address(reference: str) -> Optional[str]:
    """`aws_security_group.web.id` -> `aws_security_group.web`."""
    parts = reference.split(".")
    if len(parts) >= 2 and parts[0].startswith("aws_"):
        return f"{parts[0]}.{parts[1]}"
    return None


def _build_identity_index(
    resources: List[TerraformResource],
) -> Dict[str, Dict[str, str]]:
    """`{type: {identifying value: address}}` for value-based matching."""
    index: Dict[str, Dict[str, str]] = {}
    for resource in resources:
        bucket = index.setdefault(resource.type, {})
        for attribute in _IDENTITY_ATTRS:
            value = resource.get(attribute)
            if isinstance(value, str) and value:
                bucket.setdefault(value, resource.address)
    return index


def _link_attribute(
    resource: TerraformResource,
    attribute: str,
    target_types: Tuple[str, ...],
    suffix: str,
    index: Dict[str, Dict[str, str]],
    config_references: Dict[str, Dict[str, List[str]]],
) -> None:
    """Rewrite one attribute from resolved values to Terraform addresses."""
    # Pass 1: exact references from the configuration block.
    # `references` lists both `aws_x.y.id` and `aws_x.y`, so de-duplicate.
    referenced = (config_references.get(resource.address) or {}).get(attribute) or []
    addresses: List[str] = []
    for reference in referenced:
        address = _resource_address(reference)
        if address and address.split(".")[0] in target_types and address not in addresses:
            addresses.append(address)

    # Pass 2: match resolved values against known ids/names/ARNs.
    if not addresses:
        raw = resource.get(attribute)
        candidates = raw if isinstance(raw, list) else [raw]
        for value in candidates:
            if not isinstance(value, str):
                continue
            for target_type in target_types:
                address = (index.get(target_type) or {}).get(value)
                if address and address not in addresses:
                    addresses.append(address)

    if not addresses:
        return

    linked = [f"{address}.{suffix}" for address in addresses]
    original = resource.attributes.get(attribute)
    resource.attributes[attribute] = linked if isinstance(original, list) or attribute in ("vpc_security_group_ids", "security_groups") else linked[0]


def _link_policy_documents(
    resource: TerraformResource, buckets: List[TerraformResource]
) -> None:
    """Replace concrete bucket ARNs inside a policy with Terraform addresses."""
    policy = resource.get("policy")
    if not isinstance(policy, str) or not policy:
        return
    for bucket in sorted(buckets, key=lambda b: len(str(b.get("arn") or "")), reverse=True):
        arn = bucket.get("arn")
        if isinstance(arn, str) and arn:
            policy = policy.replace(f'"{arn}"', f'"${{{bucket.address}.arn}}"')
            policy = policy.replace(f'"{arn}/', f'"${{{bucket.address}.arn}}/')
    resource.attributes["policy"] = policy


def _relink(
    resources: List[TerraformResource], config_references: Dict[str, Dict[str, List[str]]]
) -> None:
    index = _build_identity_index(resources)
    buckets = [r for r in resources if r.type == "aws_s3_bucket"]
    for resource in resources:
        for (resource_type, attribute), (targets, suffix) in _REFERENCE_ATTRS.items():
            if resource.type == resource_type:
                _link_attribute(resource, attribute, targets, suffix, index, config_references)
        if resource.type in ("aws_iam_role_policy", "aws_iam_policy", "aws_s3_bucket_policy"):
            _link_policy_documents(resource, buckets)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def parse_plan(data: Dict[str, Any], phase: str = "after", source: str = "plan") -> ParsedConfig:
    """Normalize one side of a plan into the standard `ParsedConfig`."""
    if phase not in ("before", "after"):
        raise ValueError(f"phase must be 'before' or 'after', not {phase!r}")

    resources: List[TerraformResource] = []
    unsupported: List[str] = []

    for entry in _values_resources(data, phase):
        if entry.get("mode", "managed") != "managed":
            continue
        resource_type = entry.get("type") or ""
        if resource_type not in SUPPORTED_TYPES:
            if resource_type and resource_type not in unsupported:
                unsupported.append(resource_type)
            continue
        address = entry.get("address", "")
        if address.startswith("module.") or "[" in address:
            unsupported.append(f"{address} (module/indexed address not modeled)")
            continue
        values = entry.get("values") or {}
        resources.append(
            TerraformResource(
                type=resource_type,
                name=entry.get("name") or "",
                attributes=dict(values),
                source_file=source,
            )
        )

    _relink(resources, _configuration_references(data) if phase == "after" else {})
    resources.sort(key=lambda r: (SUPPORTED_TYPES.index(r.type), r.name))
    return ParsedConfig(
        resources=resources, source_dir=f"{source}#{phase}", unsupported=sorted(unsupported)
    )


def parse_plan_file(path: PathLike, phase: str = "after") -> ParsedConfig:
    return parse_plan(load_plan(path), phase=phase, source=str(path))


def parse_plan_pair(path: PathLike) -> Tuple[ParsedConfig, ParsedConfig]:
    """Return `(before, after)` configurations from a single plan file."""
    data = load_plan(path)
    return (
        parse_plan(data, "before", source=str(path)),
        parse_plan(data, "after", source=str(path)),
    )
