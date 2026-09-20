"""Pure data and configuration for the public BlastRadius showcase."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlparse

HERO_TITLE = "Your Terraform diff shows what changed. BlastRadius shows what became reachable."
HERO_SUBTITLE = "Attack-path change analysis for Terraform pull requests."
HERO_BODY = (
    "A small Terraform change can connect existing network exposure, identity permissions "
    "and sensitive data. BlastRadius compares BEFORE vs AFTER and identifies newly "
    "introduced modeled attack paths before merge."
)
DEMO_NOTICE = (
    "You're using the public BlastRadius demo. The multi-user workspace platform is currently "
    "in private beta."
)


@dataclass(frozen=True)
class PricingTier:
    code: str
    name: str
    price_label: str
    note: str
    features: tuple[str, ...]
    cta_label: str
    cta_kind: str


PRICING = (
    PricingTier(
        "free",
        "Free",
        "$0/month",
        "",
        ("1 repository", "25 analyses/month", "7-day history"),
        "Try demo",
        "demo",
    ),
    PricingTier(
        "pro",
        "Pro",
        "$49/month",
        "Proposed beta pricing",
        ("5 repositories", "500 analyses/month", "90-day history", "advanced policies", "SARIF", "history"),
        "Request beta access",
        "beta",
    ),
    PricingTier(
        "team",
        "Team",
        "$149/month",
        "Proposed beta pricing",
        ("25 repositories", "5,000 analyses/month", "365-day history", "team access", "RBAC", "organization policies"),
        "Request beta access",
        "beta",
    ),
    PricingTier(
        "enterprise",
        "Enterprise",
        "Custom",
        "",
        ("Custom limits", "team access", "RBAC", "organization policies", "dedicated onboarding"),
        "Contact",
        "contact",
    ),
)
PRICING_DISCLAIMER = "Beta pricing. Payments are not yet enabled."

TRUST_FAQ = (
    ("Does BlastRadius need AWS credentials?", "No, not for static Terraform analysis."),
    ("Does BlastRadius deploy Terraform?", "No."),
    ("Does it execute Terraform providers?", "No."),
    ("Does it execute repository candidate code?", "No."),
    (
        "Does SAFE mean my cloud environment is completely secure?",
        "No. SAFE TO MERGE means no new modeled blocking findings were detected within "
        "BlastRadius's supported security model and selected policy.",
    ),
)

LIMITATIONS = (
    "BlastRadius models only documented AWS/Terraform relationships.",
    "It does not currently provide:",
    "complete AWS security assurance",
    "live account discovery",
    "complete effective IAM authorization",
    "every network routing behavior",
    "every Terraform construct",
    "Azure/GCP coverage",
    "compliance certification",
)

BUILT_FOR = ("Terraform", "AWS", "GitHub")
TYPICAL_USERS = (
    "DevOps engineers",
    "Platform engineers",
    "Cloud security engineers",
    "Security-conscious startups",
)
BETA_LOOKING_FOR = (
    "Terraform users",
    "AWS users",
    "GitHub teams",
    "DevOps/platform engineers",
    "cloud security engineers",
    "small SaaS engineering teams",
)
VALIDATION_QUESTION = "Would you want BlastRadius to check your Terraform PRs?"

REPO_URL = "https://github.com/Mighiana/BlastRadius"
DOC_LINKS = (
    ("GitHub repository", ""),
    ("README", "README.md"),
    ("Getting started", "docs/getting-started.md"),
    ("Security model", "docs/security-model.md"),
    ("Supported coverage", "docs/coverage.md"),
    ("Limitations", "docs/limitations.md"),
    ("GitHub Actions", "docs/github-actions.md"),
    ("Beta information", "docs/beta-guide.md"),
)

_REF_PATTERN = re.compile(r"^[A-Za-z0-9._/-]{1,100}$")
_EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def doc_url(path: str, ref: str | None = None) -> str:
    """Return a stable GitHub URL for a repository document."""
    selected_ref = ref if ref is not None else os.environ.get("BLASTRADIUS_DOCS_REF", "main")
    if not _REF_PATTERN.fullmatch(selected_ref):
        selected_ref = "main"
    return REPO_URL if not path else f"{REPO_URL}/blob/{selected_ref}/{path}"


@dataclass(frozen=True)
class BetaContact:
    form_url: str | None
    email: str | None

    @property
    def configured(self) -> bool:
        return bool(self.form_url or self.email)


def _secret_value(secrets: Mapping[str, object] | None, key: str) -> str | None:
    if not secrets:
        return None
    try:
        value = secrets.get(key)
    except Exception:
        return None
    return value if isinstance(value, str) else None


def beta_contact(
    env: Mapping[str, str], secrets: Mapping[str, object] | None
) -> BetaContact:
    """Read optional beta contact destinations, preferring environment values."""
    form_url = env.get("BLASTRADIUS_BETA_FORM_URL") or _secret_value(
        secrets, "BLASTRADIUS_BETA_FORM_URL"
    )
    email = env.get("BLASTRADIUS_BETA_CONTACT") or _secret_value(
        secrets, "BLASTRADIUS_BETA_CONTACT"
    )
    if not form_url or len(form_url) > 300:
        form_url = None
    else:
        parsed = urlparse(form_url)
        if parsed.scheme != "https" or not parsed.hostname:
            form_url = None
    if not email or len(email) > 254 or not _EMAIL_PATTERN.fullmatch(email):
        email = None
    return BetaContact(form_url=form_url, email=email)


BETA_CONTACT_FALLBACK = (
    "Contact us to join the beta",
    "No beta contact is configured for this deployment yet. Follow the GitHub repository "
    "for the private-beta announcement.",
)
