# Optional Stripe test-mode billing

This backend implements **Stripe test mode only**. It does not collect real
payments or support a live commercial launch. Missing credentials are a clear,
usable disabled state; there is no local plan-selector bypass.

## Configuration

In a Stripe test-mode account/sandbox, create two recurring prices and configure
the hosted customer portal. Inject all four variables together:

```text
BR_STRIPE_SECRET_KEY=sk_test_<secret>
BR_STRIPE_WEBHOOK_SECRET=whsec_<secret>
BR_STRIPE_PRICE_PRO=price_<pro-test-price>
BR_STRIPE_PRICE_TEAM=price_<team-test-price>
```

`sk_live_…` and incomplete configuration are rejected at startup. Price IDs must
be distinct and start with `price_`; provider events must confirm an allowlisted
price and test-mode objects. These values and plan quotas are server-controlled.
Never expose the secret key/webhook secret to the frontend. No publishable key
is needed because checkout and portal use hosted Stripe redirects.

Configure a webhook endpoint `${BR_PUBLIC_URL}/api/billing/webhook` for:

* `customer.subscription.created`
* `customer.subscription.updated`
* `customer.subscription.deleted`

The official Python SDK is pinned in the server extra. Official contracts used:

* [Create customer](https://docs.stripe.com/api/customers/create)
* [Create Checkout Session](https://docs.stripe.com/api/checkout/sessions/create)
* [Create portal session](https://docs.stripe.com/api/customer_portal/sessions/create)
* [Verify webhook signatures](https://docs.stripe.com/webhooks/signature)
* [Subscription event handling](https://docs.stripe.com/billing/subscriptions/webhooks)

Development/tests do not call real Stripe customer, checkout, portal or
subscription write APIs. Enabling credentials and invoking these endpoints will
perform **test-mode provider writes**; operators must authorize and verify that
setup separately.

## Browser API

Every billing browser endpoint checks organization membership and requires the
owner role. POSTs require session-bound CSRF. Neither user ID, customer ID,
subscription ID, price ID nor return URL is accepted from the browser.

`GET /api/organizations/{id}/billing` returns:

```json
{
  "enabled":false,"test_mode":true,"plan":"free","subscription_status":"none",
  "usage":{"period":"2026-09","analyses":0,"plan":"free",
           "limits":{"analyses_per_month":20,"projects":3,"members":1}}
}
```

`POST /api/organizations/{id}/billing/checkout {"plan":"pro"}` (or `team`)
returns `{"url":"https://checkout.stripe.com/…"}`. It creates/maps a customer
server-side, with an organization-specific customer-creation idempotency key,
and creates a subscription-mode checkout for exactly one allowlisted price with
quantity one. Customer IDs are unique across organizations in the database.
Success/cancel URLs are fixed to `${BR_PUBLIC_URL}/billing?checkout=success`
and `?checkout=cancelled`. No open redirect parameter is accepted.

The return query parameter never changes plan state. Refresh `/api/me` or billing
state while awaiting a verified webhook. Existing active, trialing, past-due,
unpaid or paused subscriptions return `409 use_billing_portal` from checkout.
Disable repeat checkout submissions in the UI: outstanding checkout sessions
are not persisted/reused, and abandoned simultaneous checkouts are not reconciled.
The customer mapping is idempotent; session creation is not globally idempotent.

`POST /api/organizations/{id}/billing/portal` returns
`{"url":"https://billing.stripe.com/…"}` for the organization's stored customer,
with return URL `${BR_PUBLIC_URL}/billing`. Missing customer returns
`409 billing_customer_missing`. Without billing configuration, writes return
`503 billing_disabled`. SDK/network failures return sanitized
`502 billing_provider_unavailable` without echoing credentials or provider details.
Redirect URLs from the SDK must have HTTPS and the exact expected Stripe hostname.

## Webhook security and plan effects

`POST /api/billing/webhook` verifies the signature over the **raw request bytes**
using the official Stripe verifier. The timestamp must be within 300 seconds in
both directions; expired and future-dated signatures fail. Both the event and
subscription/price objects must have `livemode: false`. Forged, malformed, live,
unmapped-customer, unapproved-price and unsupported-item events return 400.

Event IDs are persisted with a unique primary key. Repeated events return
`{"received":true,"duplicate":true}` without changing state. Other authentic
event types are recorded and ignored. Subscription events select the organization
by its server-created **customer mapping**, never by untrusted event metadata.
An event with another subscription ID cannot replace an existing non-canceled
subscription. Unknown customers/conflicting mappings are not auto-provisioned.

Changes are transactional with organization locking. The latest accepted
`event.created` timestamp is stored per organization; older or equal timestamp
events return `{"received":true,"stale":true}`. Stripe timestamps have one-second
resolution: two real changes in the same second may require a later provider
update/reconciliation. The service deliberately does not guess their ordering.
Do not treat this bounded test-mode event projection as a complete billing ledger.

For an allowlisted subscription:

* `active` and `trialing`: Pro or Team quotas from its price ID.
* `past_due`, `unpaid`, `paused`, `incomplete`, `incomplete_expired`, `canceled`
  or deletion: Free quotas.
* A later valid active event restores its paid-plan test quotas.

Quota changes do not reset monthly submitted-analysis counts and do not delete
existing projects, members or analysis history. Objects over downgraded limits
remain readable; new objects/analyses are rejected with `402` until usage permits.

## Verified scope and remaining work

Tests construct real signed webhook payloads and use the official signature
verifier, checking signature forgery, expired/future timestamps, live events,
unknown customers/metadata impersonation, unapproved prices, invalid quantities,
deduplication, stale ordering and quota transitions. The official SDK adapter's
customer/checkout/portal parameters are tested through mocks. No provider writes
or live charges are represented as tested.

Before any commercial billing implementation, add explicit authorization and a
separate design for live keys/payments, subscription reconciliation/backfills,
checkout deduplication, tax/invoices/refunds, entitlement grace periods,
subscription ownership recovery and operational alerting. Current test-mode
webhook state can remain stale if events are never delivered; there is no provider
polling, replay scheduler, self-service reconciliation or event retention job.
