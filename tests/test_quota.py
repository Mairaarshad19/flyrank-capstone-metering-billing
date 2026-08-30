from tests.helpers import ApiTestCase


class TestQuota(ApiTestCase):
    def test_free_plan_exact_boundary_is_allowed(self):
        response = self.client.post(
            "/generate",
            json={"tenant_id": 1, "idempotency_key": "exact-1000", "usage_type": "api_call", "quantity": 1000},
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["recorded"])
        self.assertEqual(body["period_used"], 1000)
        self.assertEqual(body["period_limit"], 1000)

    def test_free_plan_one_over_boundary_returns_402(self):
        self.client.post(
            "/generate",
            json={"tenant_id": 1, "idempotency_key": "fill-999", "usage_type": "api_call", "quantity": 999},
        )
        response = self.client.post(
            "/generate",
            json={"tenant_id": 1, "idempotency_key": "one-more", "usage_type": "api_call", "quantity": 2},
        )
        self.assertEqual(response.status_code, 402)
        body = response.get_json()
        self.assertFalse(body["recorded"])
        self.assertIn("upgrade", body["reason"])

    def test_pro_plan_over_boundary_returns_429(self):
        self.client.post(
            "/generate",
            json={"tenant_id": 2, "idempotency_key": "fill-pro", "usage_type": "api_call", "quantity": 100000},
        )
        response = self.client.post(
            "/generate",
            json={"tenant_id": 2, "idempotency_key": "one-more-pro", "usage_type": "api_call", "quantity": 1},
        )
        self.assertEqual(response.status_code, 429)
        body = response.get_json()
        self.assertFalse(body["recorded"])
        self.assertIn("resets next month", body["reason"])

    def test_ai_token_quota_uses_total_of_all_categories(self):
        response = self.client.post(
            "/generate",
            json={
                "tenant_id": 1,
                "idempotency_key": "tokens-1",
                "usage_type": "ai_tokens",
                "tokens": {
                    "input_tokens": 40000,
                    "cached_input_tokens": 20000,
                    "output_tokens": 30000,
                    "reasoning_tokens": 10000,
                },
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["period_used"], 100000)
        self.assertEqual(body["period_limit"], 100000)
