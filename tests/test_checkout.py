import os
import unittest
from unittest.mock import patch

from app.stripe_client import create_checkout_session


class FakeResponse:
    def __init__(self, json_body, status_code=200):
        self._json_body = json_body
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"stripe returned {self.status_code}")

    def json(self):
        return self._json_body


class TestCheckoutSessionCreation(unittest.TestCase):
    """The sandbox this capstone was built in has no outbound network access,
    so the real Stripe API cannot be reached from here. This test stubs the
    http call instead, to prove the request is built correctly: the right
    price id, the right mode, and the tenant id carried through so the
    webhook can later map the session back to a tenant. Anyone running this
    with a real Stripe test secret key gets the same code path for real."""

    def setUp(self):
        os.environ["STRIPE_SECRET_KEY"] = "sk_test_fake"
        os.environ["STRIPE_PRICE_ID_PRO"] = "price_fake_pro"
        os.environ["STRIPE_SUCCESS_URL"] = "http://localhost:5000/checkout/success"
        os.environ["STRIPE_CANCEL_URL"] = "http://localhost:5000/checkout/cancel"

    def test_checkout_session_request_is_built_correctly(self):
        captured = {}

        def fake_post(url, data=None, auth=None, timeout=None):
            captured["url"] = url
            captured["data"] = data
            captured["auth"] = auth
            return FakeResponse({"id": "cs_test_123", "url": "https://checkout.stripe.com/pay/cs_test_123"})

        result = create_checkout_session(tenant_id=1, http_post=fake_post)

        self.assertEqual(result["id"], "cs_test_123")
        self.assertEqual(captured["url"], "https://api.stripe.com/v1/checkout/sessions")
        self.assertEqual(captured["data"]["mode"], "subscription")
        self.assertEqual(captured["data"]["client_reference_id"], "1")
        self.assertEqual(captured["data"]["metadata[tenant_id]"], "1")
        self.assertEqual(captured["data"]["line_items[0][price]"], "price_fake_pro")
        self.assertEqual(captured["auth"], ("sk_test_fake", ""))


from tests.helpers import ApiTestCase

class TestCheckoutRoute(ApiTestCase):
    def setUp(self):
        super().setUp()
        os.environ["STRIPE_SECRET_KEY"] = "sk_test_fake"
        os.environ["STRIPE_PRICE_ID_PRO"] = "price_fake_pro"

    @patch("app.routes.checkout.create_checkout_session")
    def test_checkout_route_success(self, mock_create):
        mock_create.return_value = {
            "id": "cs_test_route_123",
            "url": "https://checkout.stripe.com/pay/cs_test_route_123"
        }

        response = self.client.post("/checkout", json={"tenant_id": 1})
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["session_id"], "cs_test_route_123")
        self.assertEqual(body["checkout_url"], "https://checkout.stripe.com/pay/cs_test_route_123")
        mock_create.assert_called_once_with(1)

    def test_checkout_route_missing_tenant_id(self):
        response = self.client.post("/checkout", json={})
        self.assertEqual(response.status_code, 400)
        self.assertIn("tenant_id is required", response.get_json()["error"])

