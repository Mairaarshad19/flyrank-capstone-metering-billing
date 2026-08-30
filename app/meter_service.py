import json
import sqlite3
from datetime import datetime, timezone

from app.pricing import plan_limit


class TenantNotFound(Exception):
    pass


def _current_period():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m")


def _get_tenant(conn, tenant_id):
    row = conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
    if row is None:
        raise TenantNotFound(f"no tenant with id {tenant_id}")
    return row


def _period_usage(conn, tenant_id, usage_type, period):
    row = conn.execute(
        """
        SELECT COALESCE(SUM(quantity), 0) AS total
        FROM usage_events
        WHERE tenant_id = ? AND usage_type = ? AND strftime('%Y-%m', created_at) = ?
        """,
        (tenant_id, usage_type, period),
    ).fetchone()
    return row["total"]


def record_usage(conn, tenant_id, idempotency_key, usage_type, quantity=0, tokens=None):
    """Records one billable action for a tenant, exactly once per idempotency key.

    Returns a tuple of (status_code, response_body_dict, was_replay_bool).
    """
    tokens = tokens or {}
    conn.execute("BEGIN IMMEDIATE")
    try:
        existing = conn.execute(
            "SELECT status_code, response_body FROM idempotency_responses WHERE tenant_id = ? AND idempotency_key = ?",
            (tenant_id, idempotency_key),
        ).fetchone()
        if existing is not None:
            conn.commit()
            return existing["status_code"], json.loads(existing["response_body"]), True

        tenant = _get_tenant(conn, tenant_id)
        period = _current_period()

        if usage_type == "ai_tokens":
            requested = (
                int(tokens.get("input_tokens", 0))
                + int(tokens.get("cached_input_tokens", 0))
                + int(tokens.get("output_tokens", 0))
                + int(tokens.get("reasoning_tokens", 0))
            )
        else:
            requested = int(quantity)

        current_used = _period_usage(conn, tenant_id, usage_type, period)
        limit = plan_limit(tenant["plan"], usage_type)
        new_total = current_used + requested

        if new_total <= limit:
            conn.execute(
                """
                INSERT INTO usage_events
                    (tenant_id, usage_type, quantity, idempotency_key,
                     input_tokens, cached_input_tokens, output_tokens, reasoning_tokens)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant_id,
                    usage_type,
                    requested,
                    idempotency_key,
                    int(tokens.get("input_tokens", 0)),
                    int(tokens.get("cached_input_tokens", 0)),
                    int(tokens.get("output_tokens", 0)),
                    int(tokens.get("reasoning_tokens", 0)),
                ),
            )
            status_code = 200
            body = {
                "recorded": True,
                "tenant_id": tenant_id,
                "usage_type": usage_type,
                "quantity_recorded": requested,
                "period": period,
                "period_used": new_total,
                "period_limit": limit,
            }
        else:
            if tenant["plan"] == "free":
                status_code = 402
                reason = "free plan limit reached for this billing period, upgrade to pro to continue"
            else:
                status_code = 429
                reason = "usage quota exceeded for this billing period, it resets next month"
            body = {
                "recorded": False,
                "tenant_id": tenant_id,
                "usage_type": usage_type,
                "quantity_requested": requested,
                "period": period,
                "period_used": current_used,
                "period_limit": limit,
                "reason": reason,
            }

        conn.execute(
            "INSERT INTO idempotency_responses (tenant_id, idempotency_key, status_code, response_body) VALUES (?, ?, ?, ?)",
            (tenant_id, idempotency_key, status_code, json.dumps(body)),
        )
        conn.commit()
        return status_code, body, False
    except Exception:
        conn.rollback()
        raise
