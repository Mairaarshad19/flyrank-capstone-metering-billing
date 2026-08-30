from datetime import datetime, timezone

from app.pricing import plan_limit, calculate_ai_token_cost_cents
from app.meter_service import TenantNotFound, _get_tenant, _current_period


def get_usage_summary(conn, tenant_id, period=None):
    tenant = _get_tenant(conn, tenant_id)
    period = period or _current_period()

    api_calls_used = conn.execute(
        """
        SELECT COALESCE(SUM(quantity), 0) AS total FROM usage_events
        WHERE tenant_id = ? AND usage_type = 'api_call' AND strftime('%Y-%m', created_at) = ?
        """,
        (tenant_id, period),
    ).fetchone()["total"]

    token_row = conn.execute(
        """
        SELECT
            COALESCE(SUM(input_tokens), 0) AS input_tokens,
            COALESCE(SUM(cached_input_tokens), 0) AS cached_input_tokens,
            COALESCE(SUM(output_tokens), 0) AS output_tokens,
            COALESCE(SUM(reasoning_tokens), 0) AS reasoning_tokens
        FROM usage_events
        WHERE tenant_id = ? AND usage_type = 'ai_tokens' AND strftime('%Y-%m', created_at) = ?
        """,
        (tenant_id, period),
    ).fetchone()

    ai_tokens_used = (
        token_row["input_tokens"]
        + token_row["cached_input_tokens"]
        + token_row["output_tokens"]
        + token_row["reasoning_tokens"]
    )

    ai_tokens_cost_cents = calculate_ai_token_cost_cents(
        input_tokens=token_row["input_tokens"],
        cached_input_tokens=token_row["cached_input_tokens"],
        output_tokens=token_row["output_tokens"],
        reasoning_tokens=token_row["reasoning_tokens"],
    )

    return {
        "tenant_id": tenant_id,
        "plan": tenant["plan"],
        "period": period,
        "api_calls": {
            "used": api_calls_used,
            "limit": plan_limit(tenant["plan"], "api_calls"),
        },
        "ai_tokens": {
            "used": ai_tokens_used,
            "limit": plan_limit(tenant["plan"], "ai_tokens"),
            "breakdown": {
                "input_tokens": token_row["input_tokens"],
                "cached_input_tokens": token_row["cached_input_tokens"],
                "output_tokens": token_row["output_tokens"],
                "reasoning_tokens": token_row["reasoning_tokens"],
            },
        },
        "cost": {
            "ai_tokens_cost_cents": ai_tokens_cost_cents,
            "currency": "usd",
            "note": "api calls are included in the subscription price, only ai tokens carry a usage based cost",
        },
    }
