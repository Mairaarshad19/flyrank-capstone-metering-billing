import json
import os

from flask import Blueprint, request, jsonify, current_app, g

from app.db import get_connection
from app.stripe_client import (
    verify_webhook_signature,
    SignatureVerificationError,
)
from app.webhook_service import apply_event


webhooks_bp = Blueprint("webhooks", __name__)


def _db():
    if "db" not in g:
        g.db = get_connection(
            current_app.config["DB_PATH"]
        )
    return g.db


@webhooks_bp.route("/webhooks/stripe", methods=["POST"])
def stripe_webhook():

    payload_bytes = request.get_data()

    signature_header = request.headers.get(
        "Stripe-Signature"
    )

    secret = os.environ.get(
        "STRIPE_WEBHOOK_SECRET",
        "",
    )

    try:
        verify_webhook_signature(
            payload_bytes,
            signature_header,
            secret,
        )
    except SignatureVerificationError as exc:
        return jsonify({
            "error": "signature verification failed",
            "detail": str(exc),
        }), 400

    try:
        event = json.loads(payload_bytes)
    except ValueError:
        return jsonify({
            "error": "invalid json body"
        }), 400

    try:
        outcome = apply_event(
            _db(),
            event,
        )
    except ValueError as exc:
        return jsonify({
            "error": str(exc)
        }), 400

    return jsonify({
        "received": True,
        "outcome": outcome,
    }), 200