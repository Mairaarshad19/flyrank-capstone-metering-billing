import unittest

from app.pricing import calculate_ai_token_cost_cents, TOKEN_PRICE_CENTS_PER_MILLION
from tests.helpers import ApiTestCase


class TestCostCalculationUnit(unittest.TestCase):
    def test_zero_tokens_cost_zero(self):
        self.assertEqual(calculate_ai_token_cost_cents(), 0)

    def test_input_tokens_priced_at_input_rate(self):
        cost = calculate_ai_token_cost_cents(input_tokens=1_000_000)
        self.assertEqual(cost, TOKEN_PRICE_CENTS_PER_MILLION["input"])

    def test_cached_input_tokens_are_cheaper_than_fresh_input(self):
        fresh = calculate_ai_token_cost_cents(input_tokens=1_000_000)
        cached = calculate_ai_token_cost_cents(cached_input_tokens=1_000_000)
        self.assertLess(cached, fresh)

    def test_reasoning_tokens_are_billed_at_the_output_rate(self):
        reasoning_cost = calculate_ai_token_cost_cents(reasoning_tokens=1_000_000)
        output_cost = calculate_ai_token_cost_cents(output_tokens=1_000_000)
        self.assertEqual(reasoning_cost, output_cost)

    def test_categories_are_not_simply_summed_before_pricing(self):
        # 500k input plus 500k output must not equal treating all 1,000,000
        # as input tokens, because the two categories price differently
        mixed = calculate_ai_token_cost_cents(input_tokens=500_000, output_tokens=500_000)
        all_as_input = calculate_ai_token_cost_cents(input_tokens=1_000_000)
        self.assertNotEqual(mixed, all_as_input)

    def test_known_totals_match_the_pinned_pricing_constants(self):
        cost = calculate_ai_token_cost_cents(
            input_tokens=1_000_000,
            cached_input_tokens=1_000_000,
            output_tokens=1_000_000,
            reasoning_tokens=1_000_000,
        )
        expected = (
            TOKEN_PRICE_CENTS_PER_MILLION["input"]
            + TOKEN_PRICE_CENTS_PER_MILLION["cached_input"]
            + 2 * TOKEN_PRICE_CENTS_PER_MILLION["output"]
        )
        self.assertEqual(cost, expected)
        self.assertEqual(cost, 3375)


class TestCostViaUsageEndpoint(ApiTestCase):
    def test_usage_endpoint_cost_matches_pricing_module(self):
        self.client.post(
            "/generate",
            json={
                "tenant_id": 2,
                "idempotency_key": "cost-check",
                "usage_type": "ai_tokens",
                "tokens": {
                    "input_tokens": 200_000,
                    "cached_input_tokens": 100_000,
                    "output_tokens": 50_000,
                    "reasoning_tokens": 25_000,
                },
            },
        )
        usage = self.client.get("/usage?tenant_id=2").get_json()

        expected = calculate_ai_token_cost_cents(
            input_tokens=200_000, cached_input_tokens=100_000, output_tokens=50_000, reasoning_tokens=25_000
        )
        self.assertEqual(usage["cost"]["ai_tokens_cost_cents"], expected)
