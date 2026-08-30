from flask import Blueprint, request, jsonify, current_app, g

from app.db import get_connection
from app.meter_service import record_usage, TenantNotFound

generate_bp = Blueprint("generate", __name__)


def _db():
    if "db" not in g:
        g.db = get_connection(current_app.config["DB_PATH"])
    return g.db


@generate_bp.teardown_app_request
def _close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@generate_bp.route("/generate", methods=["POST"])
def generate():
    payload = request.get_json(silent=True) or {}

    tenant_id = payload.get("tenant_id")
    idempotency_key = payload.get("idempotency_key")
    usage_type = payload.get("usage_type")

    if tenant_id is None or not idempotency_key or usage_type not in ("api_call", "ai_tokens"):
        return jsonify({
            "error": "tenant_id, idempotency_key and a usage_type of api_call or ai_tokens are all required"
        }), 400

    tokens = payload.get("tokens")
    quantity = payload.get("quantity", 1)

    if usage_type == "ai_tokens" and not isinstance(tokens, dict):
        return jsonify({"error": "usage_type ai_tokens requires a tokens object"}), 400

    try:
        status_code, body, was_replay = record_usage(
            _db(), tenant_id, idempotency_key, usage_type, quantity=quantity, tokens=tokens
        )
    except TenantNotFound:
        return jsonify({"error": f"no tenant with id {tenant_id}"}), 404

    # the body itself is byte for byte the same on a replay, the replay flag
    # only shows up as a header so a retried request truly mirrors the first
    response = jsonify(body)
    response.status_code = status_code
    response.headers["X-Idempotent-Replay"] = "true" if was_replay else "false"
    return response
