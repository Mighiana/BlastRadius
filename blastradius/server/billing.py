from __future__ import annotations

import json
import time
from typing import Protocol
from urllib.parse import urlsplit

import stripe
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from blastradius.server.config import Settings
from blastradius.server.models import BillingEvent, Organization


class Gateway(Protocol):
    def customer(self, organization_id: str) -> str: ...
    def checkout(self, customer_id: str, price: str, return_url: str) -> str: ...
    def portal(self, customer_id: str, return_url: str) -> str: ...


class StripeGateway:
    def __init__(self, settings: Settings):
        self.client = stripe.StripeClient(
            settings.stripe_secret_key,
            max_network_retries=1,
            http_client=stripe.HTTPXClient(timeout=10),
        )

    def customer(self, organization_id: str) -> str:
        customer = self.client.v1.customers.create(
            params={"metadata": {"blastradius_organization": organization_id}},
            options={"idempotency_key": f"blastradius-customer-{organization_id}"},
        )
        if customer.livemode:
            raise ValueError("Live customer rejected")
        return customer.id

    def checkout(self, customer_id: str, price: str, return_url: str) -> str:
        checkout = self.client.v1.checkout.sessions.create(
            params={
                "mode": "subscription",
                "customer": customer_id,
                "line_items": [{"price": price, "quantity": 1}],
                "success_url": return_url + "?checkout=success",
                "cancel_url": return_url + "?checkout=cancelled",
            }
        )
        if checkout.livemode or not checkout.url:
            raise ValueError("Invalid checkout")
        return safe_provider_url(checkout.url, "checkout.stripe.com")

    def portal(self, customer_id: str, return_url: str) -> str:
        portal = self.client.v1.billing_portal.sessions.create(
            params={"customer": customer_id, "return_url": return_url}
        )
        return safe_provider_url(portal.url, "billing.stripe.com")


def safe_provider_url(url: str, hostname: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != hostname
        or parsed.username
        or parsed.port not in (None, 443)
    ):
        raise ValueError("Invalid provider redirect")
    return url


def verified_event(body: bytes, signature: str, settings: Settings) -> dict:
    if not settings.billing_enabled:
        raise HTTPException(503, "billing_disabled")
    try:
        stripe.Webhook.construct_event(
            body, signature, settings.stripe_webhook_secret, tolerance=300
        )
        event = json.loads(body)
        timestamps = [
            int(part[2:]) for part in signature.split(",") if part.startswith("t=")
        ]
        if not timestamps or abs(time.time() - timestamps[0]) > 300:
            raise ValueError("Invalid timestamp")
        if not isinstance(event, dict) or event.get("livemode") is not False:
            raise ValueError("Invalid event")
        if (
            not isinstance(event.get("id"), str)
            or not event["id"].startswith("evt_")
            or len(event["id"]) > 255
        ):
            raise ValueError("Invalid event ID")
        if type(event.get("created")) is not int or not isinstance(
            event.get("type"), str
        ):
            raise ValueError("Invalid event creation")
        if not 0 <= event["created"] <= time.time() + 300:
            raise ValueError("Invalid event creation")
        return event
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        stripe.SignatureVerificationError,
    ):
        raise HTTPException(400, "invalid_webhook") from None


def apply_event(db: Session, event: dict, settings: Settings) -> dict:
    if db.get(BillingEvent, event["id"]):
        return {"received": True, "duplicate": True}
    accepted = {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }
    if event.get("type") not in accepted:
        db.add(BillingEvent(id=event["id"]))
        return {"received": True, "ignored": True}
    data = event.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("object"), dict):
        raise HTTPException(400, "invalid_webhook")
    obj = data["object"]
    if obj.get("livemode") is not False:
        raise HTTPException(400, "invalid_webhook")
    customer_id = obj.get("customer")
    if not isinstance(customer_id, str):
        raise HTTPException(400, "invalid_customer")
    org = db.scalar(
        select(Organization)
        .where(Organization.customer_id == customer_id)
        .with_for_update()
    )
    if not org:
        raise HTTPException(400, "unknown_customer")
    subscription_id = obj.get("id")
    if (
        not isinstance(subscription_id, str)
        or not subscription_id.startswith("sub_")
        or len(subscription_id) > 255
    ):
        raise HTTPException(400, "invalid_subscription")
    if (
        org.subscription_id
        and org.subscription_id != subscription_id
        and org.subscription_status not in {"none", "canceled", "incomplete_expired"}
    ):
        raise HTTPException(409, "subscription_conflict")
    items_object = obj.get("items")
    if not isinstance(items_object, dict):
        raise HTTPException(400, "invalid_subscription_items")
    items = items_object.get("data")
    if (
        not isinstance(items, list)
        or len(items) != 1
        or not isinstance(items[0], dict)
        or items[0].get("quantity") != 1
    ):
        raise HTTPException(400, "invalid_subscription_items")
    price = items[0].get("price", {})
    plans = {settings.stripe_price_pro: "pro", settings.stripe_price_team: "team"}
    if (
        not isinstance(price, dict)
        or not isinstance(price.get("id"), str)
        or price["id"] not in plans
        or price.get("livemode") is not False
    ):
        raise HTTPException(400, "unapproved_price")
    status = obj.get("status")
    if not isinstance(status, str) or status not in {
        "active",
        "trialing",
        "past_due",
        "canceled",
        "unpaid",
        "incomplete",
        "incomplete_expired",
        "paused",
    }:
        raise HTTPException(400, "invalid_subscription_status")
    db.add(BillingEvent(id=event["id"]))
    if event["created"] <= org.billing_event_created:
        return {"received": True, "stale": True}
    org.billing_event_created = event["created"]
    org.subscription_id = subscription_id
    org.subscription_status = (
        "canceled" if event["type"].endswith(".deleted") else status
    )
    org.plan = (
        plans[price["id"]]
        if org.subscription_status in {"active", "trialing"}
        else "free"
    )
    return {"received": True}
