# Plans and commercial beta

Payments are unavailable. There is no checkout, customer portal, payment webhook,
card collection, subscription activation, or payment SDK. Old payment endpoints
are removed. `BR_STRIPE_*` variables are ignored. No environment flag enables
payments. Pro and Team prices are proposed; these plans cannot be purchased.

`blastradius/server/plans.py` is the source of truth. `GET /api/plans` returns its
public catalog, limits, proposed pricing, assignment method and feature flags.
`/api/me` embeds each workspace's effective usage, limits and features, including
operator-configured Enterprise overrides.

| Plan | Monthly USD | Active projects/repositories | Analyses / UTC month | History | Members including pending invitations |
|---|---:|---:|---:|---:|---:|
| Free | 0 | 1 | 25 | 7 days | 1 |
| Pro | 49 proposed | 5 | 500 | 90 days | 1 |
| Team | 149 proposed | 25 | 5000 | 365 days | 25 |
| Enterprise | Contact; no fixed price | Configurable | Configurable | Configurable | Configurable |

Enterprise defaults use Team limits until explicitly configured by an operator.
Every new workspace starts on Free. All plans support JSON and Markdown reports.
Pro adds project policy editing and SARIF. Team adds invitations, role management,
organization default policy and manager audit visibility. Enterprise includes the
implemented Team features with configurable limits. Priority queues, payments,
SAML and unimplemented services are explicitly unavailable.

The browser may show **Request early access** or a usage explanation, never a
fake upgrade button. `402` means an enforced entitlement or quota rejection, not
a request to provide card details. A workspace owner can inspect plan identity;
even an owner cannot change the plan over HTTP. Only an operator with database
access can run [beta administration](operations.md#beta-administration).

## Metering

Submitted analyses reserve monthly quota before enqueue, under an organization
row lock on PostgreSQL or `BEGIN IMMEDIATE` on SQLite. A full queue or rejected
request consumes no quota. Accepted jobs count even when they later fail, time
out, or are deleted. UTC calendar months reset naturally with a new usage row.
There is no overage billing.

Active projects consume slots; archived projects release a slot and cannot run
new analyses. Restoring a project checks capacity. Members and unexpired,
unrevoked, unaccepted invitations share one seat budget. Each pending invitation
reserves a seat, including repeat invitations for the same email. Revoke stale
links to release their reservations. Acceptance swaps its reserved seat for a
membership atomically. JSON, Markdown and SARIF report/artifact downloads increment
the monthly export counter; ordinary analysis reads and `format=web` do not.
Downloads are counted requests, not unique viewers.

Downgrades do not remove projects or members, reset usage, or rewrite completed
policy snapshots. Existing roles still authorize access; adding invitations and
changing roles require Team entitlements. Excess active projects can be archived
or deleted. New reservations stop at the lower limit. Advanced policies remain
stored but only apply to new jobs while entitled. SARIF gates apply to all
persisted report endpoints, including nested SARIF inside JSON. Public synthetic
demo evidence remains available in all formats.

Retention changes apply immediately at read time. Data outside the current plan
window cannot be read/exported, even before cleanup. See [data lifecycle](data-lifecycle.md)
and the [future billing boundary](billing-future.md).
