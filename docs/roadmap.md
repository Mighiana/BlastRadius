# Coverage and release roadmap

The implemented [coverage table](coverage.md) and [readiness assessment](readiness.md)
are authoritative. Proposed work is not a shipping promise.

## Next phase: accept the commercial beta

Finish parent-owned browser acceptance, real OIDC/verified-email invitation and
GitHub App acceptance, final-image security remediation, TLS/database/backups,
retention scheduling, monitoring and legal review. Validate the single-process
capacity envelope before inviting real tenants.

## Reliability and enterprise

Design durable jobs and publication reconciliation before horizontal scaling.
Add project pagination above 100, complete invitation/audit page totals, email
delivery, user erasure/deletion ledger and backup lifecycle automation.
SAML/SCIM, enterprise API credentials, GitHub Enterprise and self-service
installation ownership require separate authorization designs and tests.

## Broader model coverage

Prioritize routing/public-IP prerequisites, SG-to-SG/NACL semantics, effective
IAM deny/conditions/boundaries, module/indexed identities and resource-specific
ALB/RDS/Lambda/KMS relationships. Each needs positive/negative fixtures,
deterministic evidence and explicit uncertainty; preserve incomplete-result
gating while extending coverage.

## Future commercial work

Payments remain disabled. Any future adapter must follow the separately reviewed
[billing boundary](billing-future.md); no price display, environment flag or
operator entitlement grant may activate checkout or subscriptions.
Public release artifacts and deployment require owner approval.
