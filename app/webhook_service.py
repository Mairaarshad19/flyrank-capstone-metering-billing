import json


def already_processed(conn, event_id):
    row = conn.execute(
        "SELECT 1 FROM processed_stripe_events WHERE stripe_event_id = ?", (event_id,)
    ).fetchone()
    return row is not None


def _mark_processed(conn, event_id):
    conn.execute(
        "INSERT INTO processed_stripe_events (stripe_event_id) VALUES (?)", (event_id,)
    )


def _upsert_subscription(conn, tenant_id, stripe_customer_id, stripe_subscription_id, status):
    existing = conn.execute(
        "SELECT id FROM subscriptions WHERE tenant_id = ?", (tenant_id,)
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE subscriptions
            SET stripe_customer_id = ?, stripe_subscription_id = ?, status = ?, updated_at = datetime('now')
            WHERE tenant_id = ?
            """,
            (stripe_customer_id, stripe_subscription_id, status, tenant_id),
        )
    else:
        conn.execute(
            """
            INSERT INTO subscriptions (tenant_id, stripe_customer_id, stripe_subscription_id, status)
            VALUES (?, ?, ?, ?)
            """,
            (tenant_id, stripe_customer_id, stripe_subscription_id, status),
        )


def _tenant_for_subscription(conn, stripe_subscription_id):
    row = conn.execute(
        "SELECT tenant_id FROM subscriptions WHERE stripe_subscription_id = ?",
        (stripe_subscription_id,),
    ).fetchone()
    return row["tenant_id"] if row else None


def apply_event(conn, event):
    """Applies one verified, not yet seen Stripe event to the database.

    Returns a short string describing what happened, mostly useful for
    EVIDENCE.md transcripts and for the tests.
    """
    event_id = event["id"]
    event_type = event["type"]
    data_object = event["data"]["object"]

    conn.execute("BEGIN IMMEDIATE")
    try:
        if already_processed(conn, event_id):
            conn.commit()
            return "ignored, already processed"

        if event_type == "checkout.session.completed":
            tenant_id = data_object.get("client_reference_id") or data_object.get("metadata", {}).get("tenant_id")
            tenant_id = int(tenant_id)
            conn.execute("UPDATE tenants SET plan = 'pro' WHERE id = ?", (tenant_id,))
            _upsert_subscription(
                conn,
                tenant_id,
                data_object.get("customer"),
                data_object.get("subscription"),
                "active",
            )
            outcome = f"tenant {tenant_id} upgraded to pro"

        elif event_type == "customer.subscription.updated":
            stripe_subscription_id = data_object["id"]
            tenant_id = _tenant_for_subscription(conn, stripe_subscription_id)
            status = data_object.get("status", "unknown")
            if tenant_id is not None:
                plan = "pro" if status in ("active", "trialing") else "free"
                conn.execute("UPDATE tenants SET plan = ? WHERE id = ?", (plan, tenant_id))
                conn.execute(
                    "UPDATE subscriptions SET status = ?, updated_at = datetime('now') WHERE tenant_id = ?",
                    (status, tenant_id),
                )
            outcome = f"subscription {stripe_subscription_id} status set to {status}"

        elif event_type == "customer.subscription.deleted":
            stripe_subscription_id = data_object["id"]
            tenant_id = _tenant_for_subscription(conn, stripe_subscription_id)
            if tenant_id is not None:
                conn.execute("UPDATE tenants SET plan = 'free' WHERE id = ?", (tenant_id,))
                conn.execute(
                    "UPDATE subscriptions SET status = 'canceled', updated_at = datetime('now') WHERE tenant_id = ?",
                    (tenant_id,),
                )
            outcome = f"subscription {stripe_subscription_id} canceled, tenant back on free"

        else:
            outcome = f"event type {event_type} received, nothing to do"

        _mark_processed(conn, event_id)
        conn.commit()
        return outcome
    except Exception:
        conn.rollback()
        raise
