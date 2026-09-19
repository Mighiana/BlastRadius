"""Targeted, text-level edits to Terraform source.

Both remediation (narrow a CIDR) and what-if simulation (widen a CIDR) need to
rewrite the same construct, so the block-aware logic lives here once.

These edits are deliberately conservative:
  * only `ingress` blocks are touched - public `egress` is normal
  * only blocks that reach an administrative port (22/3389) are touched, so a
    legitimately public listener on 443 is never "fixed" into an outage
  * rewriting is idempotent: widening an already-public rule, or restricting an
    already-private one, is a no-op

Ingress blocks in supported configurations contain no nested braces, so a
non-greedy block match is sufficient and much safer than a blind replace.
"""

from __future__ import annotations

import re
from typing import Tuple

from blastradius.security.rules import ADMIN_PORTS, PUBLIC_CIDRS

DEFAULT_PUBLIC_CIDR = "0.0.0.0/0"
DEFAULT_PRIVATE_CIDR = "10.0.0.0/24"

_INGRESS_BLOCK_RE = re.compile(r"ingress\s*\{.*?\n\s*\}", re.DOTALL)
_CIDR_LINE_RE = re.compile(r'(?P<indent>[ \t]*)cidr_blocks\s*=\s*\[[^\]]*\]')
_PORT_RE = re.compile(r"(?:from|to)_port\s*=\s*(\d+)")
_ACL_RE = re.compile(r'(?P<prefix>acl\s*=\s*)"(?P<acl>[a-z-]+)"')


def _reaches_admin_port(block: str) -> bool:
    if re.search(r'protocol\s*=\s*"(-1|all)"', block):
        return True
    ports = [int(p) for p in _PORT_RE.findall(block)]
    if not ports:
        return False
    low, high = min(ports), max(ports)
    return any(low <= port <= high for port in ADMIN_PORTS)


def _is_public(block: str) -> bool:
    return any(cidr in block for cidr in PUBLIC_CIDRS)


def _rewrite_admin_ingress(source: str, new_cidr: str, target_public: bool) -> Tuple[str, int]:
    """Rewrite admin-port ingress CIDRs.

    `target_public=True` rewrites blocks that are currently public (restrict),
    `False` rewrites blocks that are currently private (widen).
    """
    replacements = 0

    def rewrite_block(match: re.Match) -> str:
        nonlocal replacements
        block = match.group(0)
        if not _reaches_admin_port(block) or _is_public(block) is not target_public:
            return block

        def rewrite_cidr(cidr_match: re.Match) -> str:
            nonlocal replacements
            replacements += 1
            return f'{cidr_match.group("indent")}cidr_blocks = ["{new_cidr}"]'

        return _CIDR_LINE_RE.sub(rewrite_cidr, block, count=1)

    return _INGRESS_BLOCK_RE.sub(rewrite_block, source), replacements


def widen_admin_ingress(source: str, public_cidr: str = DEFAULT_PUBLIC_CIDR) -> Tuple[str, int]:
    """Open administrative ingress to the internet (used by the simulator)."""
    return _rewrite_admin_ingress(source, public_cidr, target_public=False)


def restrict_admin_ingress(source: str, private_cidr: str = DEFAULT_PRIVATE_CIDR) -> Tuple[str, int]:
    """Restrict internet-open administrative ingress (used by remediation)."""
    return _rewrite_admin_ingress(source, private_cidr, target_public=True)


def broaden_s3_policy(source: str) -> Tuple[str, int]:
    """Replace a scoped S3 action list with `s3:*` (used by the simulator)."""
    pattern = re.compile(r'"Action":\s*\[(?![^\]]*"s3:\*")[^\]]*"s3:[^\]]*\]')
    return pattern.subn('"Action": ["s3:*"]', source, count=1)


def make_bucket_acls_private(source: str) -> Tuple[str, int]:
    """Turn public canned ACLs back into `private` (used by remediation)."""
    replacements = 0

    def rewrite(match: re.Match) -> str:
        nonlocal replacements
        if not match.group("acl").startswith("public-"):
            return match.group(0)
        replacements += 1
        return f'{match.group("prefix")}"private"'

    return _ACL_RE.sub(rewrite, source), replacements
