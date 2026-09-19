# Billing terms template — LEGAL REVIEW REQUIRED

**Draft only. Live billing is not activated or authorized.**
Any integrated Stripe behavior must remain test mode until separately approved.
The implementation-owned billing document defines actual API/configuration.

| Decision | Owner must specify |
|---|---|
| Plans | Actual Free/Trial, Pro, Team features and measurable quota unit |
| Pricing | Amount, currency, tax inclusion/exclusion, supported countries |
| Trial | Duration, eligibility, card requirement, conversion behavior |
| Metering | Successful versus attempted analyses, reset period, concurrency |
| Renewals | Billing interval, notices, prorations and plan changes |
| Quota exhaustion | Clear rejection/upgrade behavior; no surprise overage charge |
| Cancellation | Effective date, access/export window, data handling |
| Refunds/disputes | Process, applicable rights, verified contact |
| Failed payments | Grace period, suspension, recovery rules |
| Records | Required retention and privacy disclosures |

Server-authoritative verified events must control entitlements; client navigation
or a checkout success URL is not proof of payment. Duplicate/out-of-order
webhooks need idempotency, signature checks and account/tenant identity validation.

Sandbox checkout is not evidence of live-payment readiness. Before launch verify
plans/price IDs, reconciliation, cancellation, quotas under concurrency, replay
defense and no leakage of billing secrets into logs or `VITE_*` variables.
Do not invent prices or claim any plan is available for purchase.
