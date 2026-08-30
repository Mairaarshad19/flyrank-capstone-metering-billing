"""Background job that pre computes a usage rollup per tenant.

This runs off the request path, GET /usage always computes live numbers so it
is never stale, but a dashboard or a nightly export can read usage_rollups
instead of recomputing the aggregate every time. This job is meant to be run
on a schedule, for example a cron entry or a scheduled task, not from inside
a web request.
"""

import logging
import os
import time

from dotenv import load_dotenv

load_dotenv()

from app.db import init_db
from app.usage_service import get_usage_summary
from app.meter_service import _current_period

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("rollup_job")

MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 1


def _write_rollup(conn, tenant_id, summary, period):
    conn.execute(
        """
        INSERT INTO usage_rollups (tenant_id, period, api_calls_used, ai_tokens_used, ai_tokens_cost_cents, computed_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(tenant_id, period) DO UPDATE SET
            api_calls_used = excluded.api_calls_used,
            ai_tokens_used = excluded.ai_tokens_used,
            ai_tokens_cost_cents = excluded.ai_tokens_cost_cents,
            computed_at = datetime('now')
        """,
        (
            tenant_id,
            period,
            summary["api_calls"]["used"],
            summary["ai_tokens"]["used"],
            summary["cost"]["ai_tokens_cost_cents"],
        ),
    )
    conn.commit()


def rollup_tenant(conn, tenant_id, period):
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            summary = get_usage_summary(conn, tenant_id, period=period)
            _write_rollup(conn, tenant_id, summary, period)
            logger.info("rolled up tenant %s for period %s on attempt %s", tenant_id, period, attempt)
            return True
        except Exception as exc:
            last_error = exc
            logger.warning("rollup attempt %s failed for tenant %s: %s", attempt, tenant_id, exc)
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_DELAY_SECONDS)

    logger.error("rollup failed for tenant %s after %s attempts, last error: %s", tenant_id, MAX_ATTEMPTS, last_error)
    return False


def run(db_path=None, period=None):
    db_path = db_path or os.environ.get("DATABASE_PATH", "data/billing.db")
    conn = init_db(db_path)
    period = period or _current_period()

    tenant_ids = [row["id"] for row in conn.execute("SELECT id FROM tenants").fetchall()]
    failures = []
    for tenant_id in tenant_ids:
        ok = rollup_tenant(conn, tenant_id, period)
        if not ok:
            failures.append(tenant_id)

    conn.close()

    if failures:
        logger.error("rollup job finished with failures for tenants: %s", failures)
    else:
        logger.info("rollup job finished cleanly for %s tenants", len(tenant_ids))

    return failures


if __name__ == "__main__":
    run()
