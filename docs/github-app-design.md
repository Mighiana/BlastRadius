# GitHub App security design

The backend implementation and frontend/operator contracts are documented in
[GitHub App integration](github.md). The existing [Actions](github-actions.md)
integration remains available. App provider interactions are mock-tested;
production credentials, hosted infrastructure and live provider acceptance
require operator setup and approval. There is no public installation-claim or
GitHub-user OAuth flow.

## Identity

Use selected repositories and minimum permissions: contents read, pull requests
read/write for comments, checks write only if needed, metadata read.
Do not request workflow write or organization administration.

Map authenticated application organizations to installation IDs and explicit
repository IDs, validated against GitHub. A repository name, redirect query or
client-provided installation ID is not authorization. Uninstall and repository
removal revoke mappings and stop admission/publication; a bounded in-flight
worker may finish, but its result is discarded. Renames must not cross tenant boundaries.
Workspace/account mapping requires a trusted operator's independently verified
registration, followed by authoritative App/installation/account/permission
checks. A callback state alone cannot prove installation access. A future public
flow must verify the authenticated GitHub user's installation permissions.
Use protected PEM files and short-lived repository-scoped installation tokens.
Never expose them in browser bundles.

## Webhooks

Verify `X-Hub-Signature-256` with HMAC-SHA256 over the **raw body** and a
constant-time comparison. Enforce body limits before JSON parsing. Reject missing
or invalid signatures before queueing. Signature validity authenticates delivery,
not authorization for every tenant/repository in the payload.

Validate event/action, installation ID, repository ID, pull number and base/head
SHAs against mappings. Fetch current PR metadata using the installation token
and match identities again. Deduplicate delivery IDs and
repository/PR/head/model-version jobs. Log redacted metadata, not full payloads.

## Untrusted code

Separate ingress/control plane, analysis workers and result publisher.
Workers receive bounded Terraform snapshots and trusted policy/model revisions,
without write tokens, cloud credentials, Docker sockets or host paths.
Never execute candidate scripts, package installs, providers or module downloads.

Bound compressed/expanded size, file count, parse time, resources and graph paths.
Cancel on timeout. Any future archive support must prevent zip-slip, symlinks
and decompression bombs. Contributor-produced plan data does not justify running
Terraform in a privileged worker.

## Results, forks and stale work

Key jobs by installation/repository/PR/head SHA/model revision. Before publication,
recheck installation authorization and current PR head. Discard outdated work,
serialize publishing by PR, and use idempotency for check runs/marked comments.
Record source SHA/model revision. Comments cannot provide atomic merge authorization.

Read fork changes through authorized PR Git objects with read-only access.
Do not request broader fork access or give workers write tokens. If data cannot
be read, return incomplete with a manual/Actions fallback, never PASS.

## Promotion criteria

Test invalid signatures, raw-body mutations, replays, installation spoofing,
cross-tenant IDs, renames/deletions, revocation, malicious/oversized input, stale
heads, fork permissions, token expiry, retries and concurrent results.
Use mock/recorded interactions first. Sandbox installs and any live comments or
checks need separate approval. GitHub Enterprise and multi-root aggregation are
separate compatibility decisions.

## Current operational boundary

The control queue is serialized within the existing single-replica service
lease. Admission shares the ordinary analysis semaphore and quota controls.
Analysis runs in the existing isolated worker. Publication rechecks the head
before each mutation and records intent before POSTs; uncertain outcomes require
remote reconciliation, never blind creation retries.

Durable delivery hashes and run metadata protect replay/idempotency, but raw
webhooks are not stored. Restart recovery is fail-closed and requires operator
redelivery from GitHub. Physical evidence retention uses normal operator cleanup;
delivery hashes and run tombstones have no age purge. See the integration
document for exact limits, errors and supported inputs.
