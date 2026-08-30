from tests.helpers import ApiTestCase


class TestIdempotency(ApiTestCase):
    def test_same_key_sent_twice_records_one_event(self):
        payload = {"tenant_id": 1, "idempotency_key": "key-1", "usage_type": "api_call", "quantity": 3}

        first = self.client.post("/generate", json=payload)
        second = self.client.post("/generate", json=payload)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.get_json(), second.get_json())
        self.assertEqual(first.headers.get("X-Idempotent-Replay"), "false")
        self.assertEqual(second.headers.get("X-Idempotent-Replay"), "true")

        usage = self.client.get("/usage?tenant_id=1").get_json()
        self.assertEqual(usage["api_calls"]["used"], 3)

    def test_different_keys_record_separate_events(self):
        self.client.post("/generate", json={"tenant_id": 1, "idempotency_key": "a", "usage_type": "api_call", "quantity": 3})
        self.client.post("/generate", json={"tenant_id": 1, "idempotency_key": "b", "usage_type": "api_call", "quantity": 4})

        usage = self.client.get("/usage?tenant_id=1").get_json()
        self.assertEqual(usage["api_calls"]["used"], 7)

    def test_replayed_key_after_quota_would_change_still_mirrors_original(self):
        # first call succeeds while under quota
        first = self.client.post(
            "/generate",
            json={"tenant_id": 1, "idempotency_key": "boundary-key", "usage_type": "api_call", "quantity": 1000},
        )
        self.assertEqual(first.status_code, 200)

        # sending the exact same request again must return the exact same
        # answer, not a fresh 402, because it is a true replay
        second = self.client.post(
            "/generate",
            json={"tenant_id": 1, "idempotency_key": "boundary-key", "usage_type": "api_call", "quantity": 1000},
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.get_json(), second.get_json())

    def test_missing_fields_return_400_not_500(self):
        response = self.client.post("/generate", json={"tenant_id": 1})
        self.assertEqual(response.status_code, 400)

    def test_unknown_tenant_returns_404_not_500(self):
        response = self.client.post(
            "/generate",
            json={"tenant_id": 999, "idempotency_key": "x", "usage_type": "api_call", "quantity": 1},
        )
        self.assertEqual(response.status_code, 404)
