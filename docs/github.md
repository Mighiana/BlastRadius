# GitHub App integration

The commercial-beta backend supports GitHub.com Apps. The existing
[Actions integration](github-actions.md) remains available. Provider interactions
are covered by mocked tests; no live App installation, webhook delivery, check or
comment has been verified by this implementation.

## Operator setup

Create an App in [GitHub developer settings](https://github.com/settings/apps/new).
Use **selected repositories** and these repository permissions only:

| Permission | Access |
| --- | --- |
| Contents | Read |
| Pull requests | Read and write |
| Checks | Read and write |
| Metadata | Read |

Subscribe to pull request events. Installation and installation-repositories
events revoke access when GitHub suspends/uninstalls the App or removes a
repository. The webhook URL is `BR_PUBLIC_URL/api/github/webhook`; select JSON
payloads and configure the same random webhook secret at GitHub and the server.
Do not configure a setup callback as a workspace authorization mechanism.

| Configuration | Requirement |
| --- | --- |
| `BR_GITHUB_APP_ID` | Positive numeric App ID; `0` is disabled |
| `BR_GITHUB_APP_SLUG` | App URL slug, lowercase letters, digits and hyphens |
| `BR_GITHUB_PRIVATE_KEY_FILE` | RSA PEM path, regular private file, mode `0600` or stricter; at most 16 KiB; no symlink |
| `BR_GITHUB_WEBHOOK_SECRET` | Random shared secret, at least 32 characters |
| `BR_PUBLIC_URL` | Browser origin used in private analysis links; HTTPS in production |
| `BR_ADMIN_ENABLED` | `true` only in the trusted local operator environment for registration |

All four `BR_GITHUB_*` values are required to configure the integration. A missing
or unreadable PEM makes configuration status unavailable. Configuration status
only checks local setup; connection and job processing verify provider access.
There is no GitHub OAuth client ID/secret requirement for this operator-managed
flow. GitHub credentials are never returned in JSON, persisted in the database,
passed to the analysis subprocess, or included in comments.

Before registration, the operator must independently verify that the workspace
owner is authorized to connect the GitHub account, for example using an approved
support request verified against both identities. **GitHub confirming that an
installation belongs to this App does not prove workspace ownership.** Record
the verification ticket/reference and run:

```sh
BR_ADMIN_ENABLED=true blastradius-admin github-register \
  WORKSPACE_UUID INSTALLATION_ID GITHUB_ACCOUNT_ID \
  --verification-reference approved-ticket-123
```

The command checks App ID, installation ID, account ID, suspension and permissions
through GitHub, then records the verified workspace mapping and an audit event.
It refuses to move an existing installation between workspaces/accounts. The
verification reference is a nonsecret audit identifier (letters, numbers,
`_ . : / -`, at most 200 characters). Do not put access tokens in it.
Registration is local operator administration, not an HTTP route or a tenant
capability. The operator flag must not be delegated to tenants.

An owner/admin can then connect one verified installation repository to a project.
Each numeric repository ID belongs to one project globally. An installation maps
to one workspace. Disconnect preserves the mapping/tombstone; reconnecting that
project revalidates the same installation and repository. Use a new project for a
different repository. The project metadata's repository name is descriptive;
editing it does not change the authorized connection.

After suspension/deletion, connections remain revoked even if an old event is
replayed or an `unsuspend` event arrives. A verified operator must re-register
an active installation, and an owner/admin must reconnect each project.
Repository removal also requires explicit reconnection and fresh provider checks.

## Frontend contract

`GET /api/github/config` is public, contains no secrets, and returns:

```json
{
  "configured": true,
  "available": true,
  "mode": "operator_registration",
  "self_service": false,
  "app_slug": "your-app",
  "installation_url": "https://github.com/apps/your-app/installations/new",
  "reason": "operator_registration_required",
  "permissions": {
    "contents": "read",
    "pull_requests": "write",
    "checks": "write",
    "metadata": "read"
  }
}
```

When unavailable, `installation_url` is `null` and `reason` is
`github_not_configured`. An installation link does **not** complete workspace
registration. Explain the operator step; do not present an OAuth success state
or an arbitrary installation-ID claim form.

All remaining tenant routes use the existing login session. Mutations require
the existing CSRF token, Origin checks and owner/admin role.

| Route | Contract |
| --- | --- |
| `GET /api/organizations/{id}/github/installations` | Any member; `installations` array, at most 100, with `id`, `account_id`, `account_login`, `status`, `verified_at` |
| `PUT /api/projects/{id}/github` | Owner/admin; exact JSON `{ "installation_id": 123, "repository_id": 456 }`; must use a workspace's operator-verified active installation |
| `GET /api/projects/{id}/github` | Any member; `connection` and `latest_run`, both nullable |
| `DELETE /api/projects/{id}/github` | Owner/admin; 204, sets connection `disconnected` |

A connection contains `id` (UUID), `installation_id`, `repository_id`,
`full_name`, `status` (`active`, `revoked`, `disconnected`), and `created_at`.
A latest run contains `id` (digest), `analysis_id` (nullable UUID), `pull_number`,
`base_sha`, `head_sha`, `base_ref`, `head_ref`, `head_repository_id`, `status`,
`error`, and `check_id`. Run states are `pending`, `ready`, `published`, `expired`.
`ready` means analysis finished or failed and publication may need attention.
`published` means delivery succeeded, **not** that the analysis was SAFE;
render the analysis's `decision` and `status`. `error` is a bounded safe code.
Runs outside current workspace retention are omitted.

The analysis API and existing history expose `input_type: "github"`, refs, commit
SHAs, scores, paths, decision and snapshotted trusted policy. Analysis links are
`/dashboard?project=UUID&analysis=UUID`; quota failures link to the project.
Normal workspace authorization and current retention apply to reports and
evidence. The GitHub comment only includes summary data, not source, full paths,
findings or policy secrets; it is visible to anyone who can view that PR.

Errors include 401 for missing login, 403 for role/CSRF/Origin violations, 404
for unavailable/cross-workspace resources, 409 for provider/mapping conflicts,
and 503 when GitHub is not configured. A missing provider permission is not
silently downgraded to successful analysis.

## Webhook and worker behavior

`POST /api/github/webhook` uses GitHub's `X-Hub-Signature-256`,
`X-GitHub-Delivery`, and `X-GitHub-Event`. HMAC-SHA256 covers the exact raw bytes,
compared in constant time before JSON parsing. The existing middleware enforces
`BR_MAX_BODY_BYTES` (default 1 MiB), rejects content encoding, bounds receive time
to 15 seconds, and rate limits requests. Delivery IDs are limited to 100
alphanumeric/hyphen characters. No payload body is persisted.

Only PR `opened`, `synchronize` and `reopened` are analyzed. Unsupported events
or actions return 202 with `status: ignored` after signature validation.
Lifecycle events return `handled`; accepted PRs return `queued`. A duplicate
delivery ID or event/body digest returns `duplicate`. Reusing an ID with other
content returns 409. Invalid signatures return 401; invalid supported payloads
return 400. When the shared job semaphore is full, return 503 without recording
acceptance so the event can be redelivered.

Each PR is re-read using a repository-scoped read token. Installation, repository,
PR number, open state, head/base repository IDs, refs and SHAs must match.
Repository renames use the provider's canonical name after stable-ID/account
validation; payload URLs are ignored. Fork head commits are fetched only through
the authorized **base repository** Git API. An inaccessible fork commit fails
with REVIEW; there is no fallback that grants write tokens to fork code.

Source is fetched by commit/tree/blob SHA, with a SHA-1 Git object integrity check
on each blob. Truncated trees and invalid paths fail closed. The configured
`terraform_root` must contain only supported simple `.tf` filenames for analysis.
Nested Terraform, `.tf.json`, `.tfvars`, symlinks, submodules, Git LFS pointers,
binary/NUL data, invalid UTF-8 and empty Terraform snapshots require review.
The engine also marks unsupported Terraform semantics incomplete.
Scripts, workflows, Terraform, providers and modules are never executed.

Admission and quota accounting use the existing workspace lock and monthly quota.
Accepted analysis attempts count even on failure. Policy is captured from trusted
workspace/project/default settings at admission, never from candidate files.
The existing isolated subprocess receives only bounded source and policy data.
PR identity and run state stay in the control process. Worker timeout/resource
limits and normalized evidence persistence are unchanged.

## Publication and bounds

Checks use the name `BlastRadius`, the immutable head SHA and a deterministic
external ID incorporating connection, PR/base/head/ref identity, root, trusted
policy, package version and integration protocol revision. Before each check or
comment mutation, current PR identity/head and local authorization are rechecked.
Provider installation permissions are revalidated at publication. Publication is
serialized by the single GitHub control worker.

Only a complete `SAFE TO MERGE` result produces a successful check. BLOCK,
REVIEW, fetch/parser/worker failures and quota failures produce a failing check.
When identity or authorization cannot be trusted, no check/comment is written;
configure the GitHub check as required to keep a missing result from authorizing
a merge. Checks/comments cannot atomically prevent a head change on GitHub.

Exactly one marked comment is updated when its author is a bot and
`performed_via_github_app.id` matches this App. Human look-alikes and other Apps'
comments are never changed. The marker is `<!-- blastradius-app-result -->`.
The comment contains the commit, decision, score/path summary, private analysis
link and model/retention limitations. New heads update the same comment.

| Limit | Value |
| --- | --- |
| API origin | Fixed `https://api.github.com`; no redirects/proxy environment |
| API headers | Version `2022-11-28`, JSON, identity content encoding |
| Per-client request budget/deadline | 100 attempts / 90 seconds |
| HTTP timeout | 5 seconds; 3-second connection timeout |
| API response size | 2 MiB |
| GET retries | At most 3 attempts, bounded backoff |
| Mutation HTTP attempts | One; uncertain POSTs reconcile by reads |
| Publication passes | At most 2 per delivery attempt |
| Delivery retries | At most 3 total attempts via signed redelivery |
| Recursive tree | At most 10,000 entries, never truncated |
| Source | `BR_MAX_FILES` per snapshot; half `BR_MAX_BODY_BYTES` source bytes per snapshot; combined serialized input at most `BR_MAX_BODY_BYTES` |
| Check discovery | At most 100 checks at the head |
| Comment discovery | At most 500 comments |
| App JWT / installation token | JWT lifetime at most 10 minutes; token expires in 1–61 minutes and is scoped to exactly one repository |

Tokens are minted separately for source reads and publication, requested with
only the necessary permissions, used in memory and discarded. They are not
cached. GET retries are bounded; writes are not blindly retried. Intent is stored
before a check/comment POST. If the response is lost, a matching remote object
is discovered and reused. If it cannot be found, publication stops with a
`github_*_reconciliation_required` error rather than creating another object.
An operator must investigate that state; there is no unsafe automatic flag-reset
endpoint.

## Storage, recovery and limitations

Alembic migration `0003` adds `github_installations`, `repository_connections`,
`github_deliveries` and `github_runs`; it is additive after `0002` and preserves
the populated `0001` upgrade path. Stable GitHub IDs use signed 64-bit columns.
Workspace/project deletion cascades mapped rows. Analysis deletion/cleanup
nulls the run's analysis link without deleting replay/publication protection.

The existing single-process service lease is required. Jobs and webhook payloads
are not a durable broker: on restart accepted pending analyses fail closed and
queued deliveries become retryable. Redeliver the original event from GitHub's
delivery UI; GitHub does not automatically retry every failed delivery.
No webhook payload is retained for autonomous replay. Security deduplication
hashes and publication tombstones remain stored; there is no automatic age purge
of GitHub delivery rows or old run metadata. Current retention gates all report
reads and run status visibility, and normal operator cleanup removes evidence.
Redelivery retries publication of an existing retryable delivery; an already
handled body remains a duplicate, even under a new delivery ID. It does not rerun
an already failed analysis or refund quota. Authenticated pull-request `edited`
events are revalidated against GitHub and base retargets produce a new analysis,
including when the head is unchanged. Unchanged edits reuse the existing run.

After a workspace policy, Terraform root or model change, require a new head
commit and its fresh completed check before merging. Changing configuration alone
does not refresh existing checks; replaying the original body cannot do so.
There is no authorized refresh endpoint. Keep merges paused until that new-head
check completes. Same-head required-check behavior after base retargeting still
needs real GitHub acceptance; local provider mocks do not establish hosted merge
behavior.

The example and repository Actions gates also run on PR edits and use
`--fail-on-review`: REVIEW and BLOCK both fail the gate. Historical hosted green
checks documented before this change are not evidence of complete SAFE analysis
under the current model. The immutable example analyzer pin supports the flag;
hosted acceptance of this stricter gate
remains a release-owner action.

The integration currently supports GitHub.com, one explicit Terraform root,
one repository per project and an operator-managed installation process.
GitHub Enterprise, self-service GitHub-user OAuth verification, distributed
queues, automatic redelivery and production provider acceptance remain future
work. A new engine release must advance the package/model version before
re-analyzing identical inputs. Source-provider and publication budgets are
separate so analysis runtime cannot spend the publisher's deadline.

## Provider references

- [Webhook signature validation](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries)
- [Installation-token authentication](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation)
- [Installation API](https://docs.github.com/en/rest/apps/installations)
- [Pull requests](https://docs.github.com/en/rest/pulls/pulls#get-a-pull-request)
- [Git trees](https://docs.github.com/en/rest/git/trees#get-a-tree)
- [Git blobs](https://docs.github.com/en/rest/git/blobs#get-a-blob)
- [Check runs](https://docs.github.com/en/rest/checks/runs)
- [Issue comments](https://docs.github.com/en/rest/issues/comments)
- [Webhook redelivery](https://docs.github.com/en/webhooks/using-webhooks/handling-failed-webhook-deliveries)
