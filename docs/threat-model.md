# Product threat model

This models BlastRadius as an application, separate from the AWS graph model.
It records requirements and verification needs; it is not a security certification.

## Assets and actors

Assets: private Terraform/plan data, topology/evidence reports, organization
membership, project history, usage/billing state, identity tokens, GitHub
installation/Actions credentials, backups and service availability.

Actors include authenticated users, malicious tenants, fork contributors,
unauthenticated clients, compromised dependencies and privileged operators.
Trust boundaries: browser → API, API → tenant storage, input → parser/worker,
worker → publisher, webhook → GitHub integration state, and operator → backups.

## Abuse cases and controls

| Threat | Required control | Verification |
|---|---|---|
| IDOR/cross-tenant read or delete | Scope every query and export by authorized membership, not only UI filtering | Two-tenant API negative tests for projects, jobs, reports and deletions |
| Forged/expired identity | Established JWT/OIDC libraries, issuer/audience/expiry checks, fail-closed config | Invalid key, issuer, audience, algorithm and missing-config tests |
| CSRF/session theft | Secure cookie policy and CSRF checks if cookie auth; exact CORS/origins | Cross-origin requests and credentialed-browser tests |
| XSS in resource names/evidence | Escaped rendering, no unsanitized HTML, safe downloads/content types | Malicious names, SVG/HTML strings, report rendering |
| SSRF through repository/upload inputs | No arbitrary URL fetches or host paths; provider allowlists if added | Loopback, metadata IP, redirects and path traversal rejected |
| Candidate code execution | Trusted analyzer, candidate files only as data; no providers/module downloads | Existing workflow trust tests plus malicious repository fixtures |
| Host-file access | Server-controlled job roots; reject traversal/symlinks and filesystem selectors | Absolute/relative traversal and cross-job tests |
| Input/graph denial of service | Body/file/resource/path limits, timeouts, concurrency quotas | Large HCL/plans, cycles, explosive path counts, cancellation |
| Archive/file bombs | Reject unsupported archives; bound compressed and expanded sizes if introduced | Zip-slip, symlinks, decompression ratios |
| Webhook forgery/replay | Raw-body signatures, identity mapping, deduplication | Forged body, wrong tenant/provider, duplicate delivery |
| Entitlement tampering | Singular server plan catalog, audited operator grants; no HTTP/payment plan mutation | Removed-route tests, plan/role combinations, concurrent quotas |
| Report/secret leakage | Redacted logs, tenant-scoped downloads, limited artifact retention | Secret canaries in logs/errors/exports |
| Supply-chain compromise | Exact dependency/action revisions, audits, no candidate installs in privileged jobs | CI audits, reviewed updates, clean image build |
| Data surviving deletion | Explicit live data/backup/external artifact lifecycle | Delete/read denial, restore with deletion replay |

Controls already present in the baseline include trusted Git snapshot extraction,
base-policy selection, isolated consumer Python and local publisher identity/stale
checks. Integrated API/identity/storage/entitlement controls have negative tests
for tenant IDs, roles, quotas, verified-email invitations and read/export
retention. These tests do not certify a production deployment's tenant safety.

## Residual limits

Python HCL parsing and graph enumeration process hostile data and require resource
limits even when no code is evaluated. A container is not a complete sandbox.
Network access, host mounts, privileged runners and credentials amplify a parser
bug; minimize them independently.

Reports expose architecture even after obvious secrets are removed. JSON/SARIF
are not inherently safe to publish. A passing gate has bounded model coverage
and can miss real paths; humans still review unsupported or unknown constructs.

Public demo access is not evidence of service isolation. Local SQLite and mocked
provider tests do not establish hosted production behavior. Production identity,
TLS, PostgreSQL, retention, rate limiting and backup recovery need acceptance.

## Changes requiring renewed review

Arbitrary repository fetching, archive uploads, Terraform execution, automatic
patch application, live billing, GitHub App installation, public share links,
background queues, multi-replica deployment, new graph rules and broader auth
permissions each change a boundary. Add targeted regression tests before promotion.
