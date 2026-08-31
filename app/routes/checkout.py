from flask import Blueprint, request, jsonify

from app.stripe_client import create_checkout_session
import requests


checkout_bp = Blueprint("checkout", __name__)


@checkout_bp.route("/checkout", methods=["POST"])
def checkout():

    payload = request.get_json(silent=True) or {}

    tenant_id = payload.get("tenant_id")

    if tenant_id is None:
        return jsonify({
            "error": "tenant_id is required"
        }), 400

    try:
        session = create_checkout_session(
            tenant_id
        )
    except requests.RequestException as exc:
        return jsonify({
            "error": "could not reach stripe",
            "detail": str(exc),
        }), 502
    except ValueError as exc:
        return jsonify({
            "error": str(exc)
        }), 400

    return jsonify({
        "checkout_url": session.get("url"),
        "session_id": session.get("id"),
    }), 200


@checkout_bp.route("/checkout/success", methods=["GET"])
def checkout_success():
    return jsonify({
        "message": (
            "payment complete, "
            "the webhook will update your plan shortly"
        )
    }), 200


@checkout_bp.route("/checkout/cancel", methods=["GET"])
def checkout_cancel():
    return jsonify({
        "message": (
            "checkout was canceled, "
            "no changes were made"
        )
    }), 200