import hashlib
import hmac
import os
import time

import requests

STRIPE_API_BASE = "https://api.stripe.com/v1"


class SignatureVerificationError(Exception):
    pass


def create_checkout_session(tenant_id, http_post=None):
    """Creates a Stripe test mode Checkout Session for the Pro plan."""

    secret_key = os.environ.get("STRIPE_SECRET_KEY")
    price_id = os.environ.get("STRIPE_PRICE_ID_PRO")
    success_url = os.environ.get(
        "STRIPE_SUCCESS_URL",
        "http://localhost:5000/checkout/success",
    )
    cancel_url = os.environ.get(
        "STRIPE_CANCEL_URL",
        "http://localhost:5000/checkout/cancel",
    )

    if not secret_key:
        raise ValueError("STRIPE_SECRET_KEY is not configured")

    if not price_id:
        raise ValueError("STRIPE_PRICE_ID_PRO is not configured")

    if tenant_id is None:
        raise ValueError("tenant_id is required")

    tenant_id = str(tenant_id)

    data = {
        "mode": "subscription",
        "success_url": success_url,
        "cancel_url": cancel_url,

        # This identifies which tenant created the Checkout Session.
        "client_reference_id": tenant_id,

        "line_items[0][price]": price_id,
        "line_items[0][quantity]": "1",

        # This is also included in the Checkout Session metadata.
        "metadata[tenant_id]": tenant_id,
    }

    poster = http_post or requests.post

    response = poster(
        f"{STRIPE_API_BASE}/checkout/sessions",
        data=data,
        auth=(secret_key, ""),
        timeout=10,
    )

    response.raise_for_status()

    return response.json()


def verify_webhook_signature(
    payload_bytes,
    signature_header,
    secret,
    tolerance_seconds=300,
):
    """Verifies a Stripe webhook signature."""

    if not signature_header:
        raise SignatureVerificationError(
            "missing Stripe-Signature header"
        )

    if not secret:
        raise SignatureVerificationError(
            "webhook secret is not configured"
        )

    parts = {}

    for item in signature_header.split(","):
        if "=" not in item:
            continue

        key, _, value = item.partition("=")
        parts.setdefault(key.strip(), []).append(value.strip())

    timestamps = parts.get("t")
    signatures = parts.get("v1")

    if not timestamps or not signatures:
        raise SignatureVerificationError(
            "malformed Stripe-Signature header"
        )

    timestamp = timestamps[0]

    if tolerance_seconds is not None:
        try:
            age = time.time() - int(timestamp)
        except ValueError:
            raise SignatureVerificationError(
                "malformed timestamp in Stripe-Signature header"
            )

        if abs(age) > tolerance_seconds:
            raise SignatureVerificationError(
                "webhook timestamp is outside the allowed tolerance"
            )

    signed_payload = (
        f"{timestamp}.".encode("utf-8") + payload_bytes
    )

    expected = hmac.new(
        secret.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()

    for candidate in signatures:
        if hmac.compare_digest(expected, candidate):
            return True

    raise SignatureVerificationError(
        "no matching signature found"
    )


def sign_payload(payload_bytes, secret, timestamp=None):
    """Builds a Stripe-Signature header for testing."""

    timestamp = (
        timestamp
        if timestamp is not None
        else int(time.time())
    )

    signed_payload = (
        f"{timestamp}.".encode("utf-8") + payload_bytes
    )

    signature = hmac.new(
        secret.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()

    return f"t={timestamp},v1={signature}"