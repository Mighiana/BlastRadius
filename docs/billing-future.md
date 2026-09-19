# Future billing adapter boundary

This release has **no payment integration**. The old SDK, configuration and
payment routes were removed. The nullable organization customer/subscription
identifiers, subscription status/event timestamp and legacy `billing_events`
table are preserved solely to avoid destructive migrations. Runtime entitlement
code never reads them. Historical values are not evidence of an active purchase.

A future, separately approved adapter can project verified external billing state
into `Organization.plan` and optional Enterprise `plan_limits`, using the same
organization lock and audit transaction as operator assignment. Entitlement
consumers must continue to use the central catalog; do not add provider checks
to analyzers, API handlers or the frontend.

Before implementing that adapter, separately design customer/tenant ownership,
signed event verification, replay and ordering rules, reconciliation, tax,
refunds, failure/grace periods and downgrade notices. An adapter must never trust
browser plan names, success URLs or candidate Terraform input as payment proof.
No current variable, HTTP request or frontend interaction activates this design.
