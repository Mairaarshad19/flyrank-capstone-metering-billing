import hashlib
import hmac
import os
import time

import requests

STRIPE_API_BASE = "https://api.stripe.com/v1"


class SignatureVerificationError(Exception):
    pass


def create_checkout_session(tenant_id, http_post=None):
    """Creates a Stripe test mode checkout session for the Pro plan.

    http_post is injectable so tests can stub the actual network call without
    needing a real Stripe secret key or network access.
    """
    secret_key = os.environ.get("STRIPE_SECRET_KEY")
    price_id = os.environ.get("STRIPE_PRICE_ID_PRO")
    success_url = os.environ.get("STRIPE_SUCCESS_URL", "http://localhost:5000/checkout/success")
    cancel_url = os.environ.get("STRIPE_CANCEL_URL", "http://localhost:5000/checkout/cancel")

    data = {
        "mode": "subscription",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": str(tenant_id),
        "line_items[0][price]": price_id,
        "line_items[0][quantity]": "1",
        "metadata[tenant_id]": str(tenant_id),
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


def verify_webhook_signature(payload_bytes, signature_header, secret, tolerance_seconds=300):
    """Verifies a Stripe webhook signature the same way the Stripe libraries do.

    The header looks like t=1614556800,v1=hex,v1=hex. We build the signed
    payload as timestamp.payload, HMAC it with the webhook secret, and compare
    against every v1 value using a constant time comparison.
    """
    if not signature_header:
        raise SignatureVerificationError("missing Stripe-Signature header")

    parts = {}
    for item in signature_header.split(","):
        if "=" not in item:
            continue
        key, _, value = item.partition("=")
        parts.setdefault(key.strip(), []).append(value.strip())

    timestamps = parts.get("t")
    signatures = parts.get("v1")
    if not timestamps or not signatures:
        raise SignatureVerificationError("malformed Stripe-Signature header")

    timestamp = timestamps[0]

    if tolerance_seconds is not None:
        try:
            age = time.time() - int(timestamp)
        except ValueError:
            raise SignatureVerificationError("malformed timestamp in Stripe-Signature header")
        if age > tolerance_seconds:
            raise SignatureVerificationError("webhook timestamp is outside the allowed tolerance")

    signed_payload = f"{timestamp}.".encode("utf-8") + payload_bytes
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()

    for candidate in signatures:
        if hmac.compare_digest(expected, candidate):
            return True

    raise SignatureVerificationError("no matching signature found")


def sign_payload(payload_bytes, secret, timestamp=None):
    """Builds a Stripe-Signature header value. Used by the webhook tests and
    by the Stripe CLI itself, included here so tests can simulate stripe
    trigger without needing the CLI or network access."""
    timestamp = timestamp if timestamp is not None else int(time.time())
    signed_payload = f"{timestamp}.".encode("utf-8") + payload_bytes
    signature = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"
