# Limitations

## Analysis

BlastRadius performs bounded static analysis of selected AWS/Terraform inputs.
It does not inspect live cloud state, evaluate effective IAM or complete routing,
execute Terraform/providers, expand arbitrary modules, or certify compliance.
See the exact [coverage table and budgets](coverage.md) and
[security model](security-model.md). Unknowns and truncation require review;
a high score or absent path cannot establish infrastructure safety.

## Product

The service supports one ASGI process per DB with an in-memory queue and bounded
subprocess workers. Restarted jobs fail closed, and GitHub deliveries require
redelivery; no distributed queue/HA/priority service is promised.
Invitations require matching verified OIDC email and manual link delivery.
There is no local password recovery, mail transport, SAML/SCIM or public API token.

GitHub.com App installations require operator ownership verification. GitHub
Enterprise, multi-root aggregation, archive uploads and arbitrary URL inputs
are unavailable. Project pickers are bounded to 100 records; audit/invitation
pagers lack totals. Reports are authenticated JSON/Markdown/SARIF, not PDF or
public share links.

## Operations and commercial use

Read-time retention is enforced, but physical cleanup, backups, deletion replay,
monitoring and retention scheduling are operator tasks. GitHub metadata,
downloaded files and backups can outlive evidence in the live database.
No production availability, recovery or performance SLA has been verified.
Non-root/read-only containers and subprocess limits are not a complete sandbox.

Payments are absent. Proposed plan pricing and operator grants do not represent
subscriptions. Legal templates require review before commercial launch.
The [readiness report](readiness.md) lists external setup, security promotion
blockers and acceptance work; no new public deployment is claimed.
