from flask import Blueprint, request, jsonify, current_app, g

from app.db import get_connection
from app.usage_service import get_usage_summary
from app.meter_service import TenantNotFound

usage_bp = Blueprint("usage", __name__)


def _db():
    if "db" not in g:
        g.db = get_connection(current_app.config["DB_PATH"])
    return g.db


@usage_bp.route("/usage", methods=["GET"])
def usage():
    tenant_id = request.args.get("tenant_id", type=int)
    if tenant_id is None:
        return jsonify({"error": "tenant_id query parameter is required"}), 400

    try:
        summary = get_usage_summary(_db(), tenant_id)
    except TenantNotFound:
        return jsonify({"error": f"no tenant with id {tenant_id}"}), 404

    return jsonify(summary), 200
