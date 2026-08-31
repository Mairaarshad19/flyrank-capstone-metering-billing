import json
import os
import time

from app.stripe_client import sign_payload
from tests.helpers import ApiTestCase

WEBHOOK_SECRET = "whsec_test_secret_for_unit_tests"


class TestWebhooks(ApiTestCase):
    def setUp(self):
        super().setUp()
        os.environ["STRIPE_WEBHOOK_SECRET"] = WEBHOOK_SECRET

    def _post_event(self, event, signature=None):
        payload = json.dumps(event).encode()
        if signature is None:
            signature = sign_payload(payload, WEBHOOK_SECRET)
        return self.client.post(
            "/webhooks/stripe",
            data=payload,
            headers={"Stripe-Signature": signature, "Content-Type": "application/json"},
        )

    def test_checkout_completed_upgrades_tenant_to_pro(self):
        event = {
            "id": "evt_checkout_1",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": "1",
                    "customer": "cus_123",
                    "subscription": "sub_123",
                }
            },
        }
        response = self._post_event(event)
        self.assertEqual(response.status_code, 200)

        usage = self.client.get("/usage?tenant_id=1").get_json()
        self.assertEqual(usage["plan"], "pro")

        # Verify subscription record in DB
        from app.db import get_connection
        conn = get_connection(self.db_path)
        row = conn.execute("SELECT * FROM subscriptions WHERE tenant_id = 1").fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["stripe_customer_id"], "cus_123")
        self.assertEqual(row["stripe_subscription_id"], "sub_123")
        self.assertEqual(row["status"], "active")


    def test_forged_signature_is_rejected_with_400(self):
        event = {"id": "evt_forged_1", "type": "checkout.session.completed", "data": {"object": {"client_reference_id": "1"}}}
        payload = json.dumps(event).encode()
        timestamp = int(time.time())
        forged_signature = f"t={timestamp},v1=" + "0" * 64

        response = self.client.post(
            "/webhooks/stripe",
            data=payload,
            headers={"Stripe-Signature": forged_signature, "Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 400)

        # nothing should have changed
        usage = self.client.get("/usage?tenant_id=1").get_json()
        self.assertEqual(usage["plan"], "free")

    def test_missing_signature_header_is_rejected(self):
        event = {"id": "evt_no_sig", "type": "checkout.session.completed", "data": {"object": {"client_reference_id": "1"}}}
        response = self.client.post(
            "/webhooks/stripe",
            data=json.dumps(event).encode(),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 400)

    def test_replayed_event_is_processed_only_once(self):
        event = {
            "id": "evt_replay_1",
            "type": "checkout.session.completed",
            "data": {"object": {"client_reference_id": "2", "customer": "cus_9", "subscription": "sub_9"}},
        }
        first = self._post_event(event)
        second = self._post_event(event)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.get_json()["outcome"], "tenant 2 upgraded to pro")
        self.assertEqual(second.get_json()["outcome"], "ignored, already processed")

    def test_subscription_deleted_downgrades_tenant_to_free(self):
        checkout_event = {
            "id": "evt_checkout_2",
            "type": "checkout.session.completed",
            "data": {"object": {"client_reference_id": "1", "customer": "cus_5", "subscription": "sub_5"}},
        }
        self._post_event(checkout_event)
        usage_before = self.client.get("/usage?tenant_id=1").get_json()
        self.assertEqual(usage_before["plan"], "pro")

        deleted_event = {
            "id": "evt_deleted_1",
            "type": "customer.subscription.deleted",
            "data": {"object": {"id": "sub_5"}},
        }
        response = self._post_event(deleted_event)
        self.assertEqual(response.status_code, 200)

        usage_after = self.client.get("/usage?tenant_id=1").get_json()
        self.assertEqual(usage_after["plan"], "free")

    def test_missing_tenant_id_in_checkout_completed_returns_400(self):
        event = {
            "id": "evt_checkout_no_tenant",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    # No client_reference_id
                    # No metadata
                    "customer": "cus_123",
                    "subscription": "sub_123",
                }
            },
        }
        response = self._post_event(event)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Missing tenant_id", response.get_json()["error"])

    def test_nonexistent_tenant_id_in_checkout_completed_returns_400(self):
        event = {
            "id": "evt_checkout_nonexistent_tenant",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": "999",
                    "customer": "cus_123",
                    "subscription": "sub_123",
                }
            },
        }
        response = self._post_event(event)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Tenant 999 does not exist", response.get_json()["error"])

    def test_subscription_updated_updates_tenant_plan_and_subscription_status(self):
        checkout_event = {
            "id": "evt_checkout_sub_update",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": "1",
                    "customer": "cus_sub_update",
                    "subscription": "sub_update_123",
                }
            },
        }
        self._post_event(checkout_event)
        usage_before = self.client.get("/usage?tenant_id=1").get_json()
        self.assertEqual(usage_before["plan"], "pro")

        update_event = {
            "id": "evt_sub_updated_unpaid",
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_update_123",
                    "customer": "cus_sub_update",
                    "status": "unpaid",
                }
            },
        }
        response = self._post_event(update_event)
        self.assertEqual(response.status_code, 200)

        usage_after = self.client.get("/usage?tenant_id=1").get_json()
        self.assertEqual(usage_after["plan"], "free")

        from app.db import get_connection
        conn = get_connection(self.db_path)
        row = conn.execute("SELECT status FROM subscriptions WHERE tenant_id = 1").fetchone()
        conn.close()
        self.assertEqual(row["status"], "unpaid")

        update_event_active = {
            "id": "evt_sub_updated_active",
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_update_123",
                    "customer": "cus_sub_update",
                    "status": "active",
                }
            },
        }
        response = self._post_event(update_event_active)
        self.assertEqual(response.status_code, 200)

        usage_after_active = self.client.get("/usage?tenant_id=1").get_json()
        self.assertEqual(usage_after_active["plan"], "pro")

