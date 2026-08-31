def already_processed(conn, event_id):
    row = conn.execute(
        """
        SELECT 1
        FROM processed_stripe_events
        WHERE stripe_event_id = ?
        """,
        (event_id,),
    ).fetchone()

    return row is not None


def _mark_processed(conn, event_id):
    conn.execute(
        """
        INSERT INTO processed_stripe_events (stripe_event_id)
        VALUES (?)
        """,
        (event_id,),
    )


def _upsert_subscription(
    conn,
    tenant_id,
    stripe_customer_id,
    stripe_subscription_id,
    status,
):
    existing = conn.execute(
        """
        SELECT id
        FROM subscriptions
        WHERE tenant_id = ?
        """,
        (tenant_id,),
    ).fetchone()

    if existing:
        conn.execute(
            """
            UPDATE subscriptions
            SET stripe_customer_id = ?,
                stripe_subscription_id = ?,
                status = ?,
                updated_at = datetime('now')
            WHERE tenant_id = ?
            """,
            (
                stripe_customer_id,
                stripe_subscription_id,
                status,
                tenant_id,
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO subscriptions (
                tenant_id,
                stripe_customer_id,
                stripe_subscription_id,
                status
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                tenant_id,
                stripe_customer_id,
                stripe_subscription_id,
                status,
            ),
        )


def _tenant_for_subscription(conn, stripe_subscription_id):
    row = conn.execute(
        """
        SELECT tenant_id
        FROM subscriptions
        WHERE stripe_subscription_id = ?
        """,
        (stripe_subscription_id,),
    ).fetchone()

    return row["tenant_id"] if row else None


def _get_checkout_tenant_id(data_object):
    """
    Gets tenant_id from a Stripe Checkout Session.

    We support both client_reference_id and metadata
    so either method can identify the tenant.
    """

    tenant_id = data_object.get("client_reference_id")

    if tenant_id is None:
        metadata = data_object.get("metadata") or {}
        tenant_id = metadata.get("tenant_id")

    return tenant_id


def apply_event(conn, event):
    """Applies one verified, not yet seen Stripe event to the database."""

    event_id = event["id"]
    event_type = event["type"]
    data_object = event["data"]["object"]

    conn.execute("BEGIN IMMEDIATE")

    try:
        # Prevent duplicate Stripe webhook processing.
        if already_processed(conn, event_id):
            conn.commit()
            return "ignored, already processed"

        # ---------------------------------------------------------
        # CHECKOUT COMPLETED
        # ---------------------------------------------------------
        if event_type == "checkout.session.completed":

            tenant_id = _get_checkout_tenant_id(data_object)

            if tenant_id is None:
                raise ValueError(
                    "Missing tenant_id in checkout.session.completed event. "
                    "Expected client_reference_id or metadata.tenant_id."
                )

            try:
                tenant_id = int(tenant_id)
            except (TypeError, ValueError):
                raise ValueError(
                    f"Invalid tenant_id in Stripe event: {tenant_id!r}"
                )

            # Make sure the tenant actually exists.
            tenant = conn.execute(
                """
                SELECT id
                FROM tenants
                WHERE id = ?
                """,
                (tenant_id,),
            ).fetchone()

            if tenant is None:
                raise ValueError(
                    f"Tenant {tenant_id} does not exist"
                )

            # Upgrade tenant to Pro.
            conn.execute(
                """
                UPDATE tenants
                SET plan = 'pro'
                WHERE id = ?
                """,
                (tenant_id,),
            )

            # Save subscription information.
            _upsert_subscription(
                conn,
                tenant_id,
                data_object.get("customer"),
                data_object.get("subscription"),
                "active",
            )

            outcome = (
                f"tenant {tenant_id} upgraded to pro"
            )

        # ---------------------------------------------------------
        # SUBSCRIPTION UPDATED
        # ---------------------------------------------------------
        elif event_type == "customer.subscription.updated":

            stripe_subscription_id = data_object["id"]

            tenant_id = _tenant_for_subscription(
                conn,
                stripe_subscription_id,
            )

            status = data_object.get(
                "status",
                "unknown",
            )

            if tenant_id is not None:

                plan = (
                    "pro"
                    if status in ("active", "trialing")
                    else "free"
                )

                conn.execute(
                    """
                    UPDATE tenants
                    SET plan = ?
                    WHERE id = ?
                    """,
                    (plan, tenant_id),
                )

                conn.execute(
                    """
                    UPDATE subscriptions
                    SET status = ?,
                        updated_at = datetime('now')
                    WHERE tenant_id = ?
                    """,
                    (status, tenant_id),
                )

            outcome = (
                f"subscription {stripe_subscription_id} "
                f"status set to {status}"
            )

        # ---------------------------------------------------------
        # SUBSCRIPTION DELETED
        # ---------------------------------------------------------
        elif event_type == "customer.subscription.deleted":

            stripe_subscription_id = data_object["id"]

            tenant_id = _tenant_for_subscription(
                conn,
                stripe_subscription_id,
            )

            if tenant_id is not None:

                conn.execute(
                    """
                    UPDATE tenants
                    SET plan = 'free'
                    WHERE id = ?
                    """,
                    (tenant_id,),
                )

                conn.execute(
                    """
                    UPDATE subscriptions
                    SET status = 'canceled',
                        updated_at = datetime('now')
                    WHERE tenant_id = ?
                    """,
                    (tenant_id,),
                )

            outcome = (
                f"subscription {stripe_subscription_id} "
                f"canceled, tenant back on free"
            )

        # ---------------------------------------------------------
        # OTHER STRIPE EVENTS
        # ---------------------------------------------------------
        else:
            outcome = (
                f"event type {event_type} received, "
                f"nothing to do"
            )

        # Only mark the event processed after successful handling.
        _mark_processed(conn, event_id)

        conn.commit()

        return outcome

    except Exception:
        conn.rollback()
        raise