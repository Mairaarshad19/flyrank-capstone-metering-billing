# Evidence

Every proof below was produced by actually running the code in this repository, either through the automated test suite or through a standalone script that drives the Flask app the same way a real client would. None of this is hand written or invented, it is pasted straight from a real run.

## Metering: a billable action creates exactly one usage event, even under retries

The same idempotency key was sent to `POST /generate` twice in a row.

```
--- POST /generate, first send ---
status: 200
{
  "period": "2026-08",
  "period_limit": 1000,
  "period_used": 5,
  "quantity_recorded": 5,
  "recorded": true,
  "tenant_id": 1,
  "usage_type": "api_call"
}
X-Idempotent-Replay: false

--- POST /generate, identical retry ---
status: 200
{
  "period": "2026-08",
  "period_limit": 1000,
  "period_used": 5,
  "quantity_recorded": 5,
  "recorded": true,
  "tenant_id": 1,
  "usage_type": "api_call"
}
X-Idempotent-Replay: true

--- GET /usage, used is 5 not 10 ---
status: 200
{
  "api_calls": { "limit": 1000, "used": 5 },
  ...
}

bodies identical on retry: True
```

`used` stays at 5 after two identical requests, and the second response is byte for byte the same JSON body as the first, only an `X-Idempotent-Replay: true` header shows it was a replay. This is also covered by `tests/test_idempotency.py`, five tests, all passing.

## Quotas: usage checked against the plan, over limit requests rejected with a clear message

Free plan, brought to exactly 1000 of 1000, then one more call:

```
--- POST /generate, brings tenant to exactly 1000 of 1000 ---
status: 200
{ "period_used": 1000, "period_limit": 1000, "recorded": true, ... }

--- POST /generate, one more call past the limit ---
status: 402
{
  "period_used": 1000,
  "period_limit": 1000,
  "quantity_requested": 1,
  "reason": "free plan limit reached for this billing period, upgrade to pro to continue",
  "recorded": false,
  "tenant_id": 1,
  "usage_type": "api_call"
}
```

Pro plan, brought to exactly 100000 of 100000, then one more call:

```
--- POST /generate, brings pro tenant to exactly 100000 of 100000 ---
status: 200
{ "period_used": 100000, "period_limit": 100000, "recorded": true, ... }

--- POST /generate, one more call past the pro limit ---
status: 429
{
  "period_used": 100000,
  "period_limit": 100000,
  "quantity_requested": 1,
  "reason": "usage quota exceeded for this billing period, it resets next month",
  "recorded": false,
  "tenant_id": 2,
  "usage_type": "api_call"
}
```

The exact boundary is allowed on both plans, the request that would cross it is rejected, free gets 402 with an upgrade message, pro gets 429 with a retry next month message. Covered by `tests/test_quota.py`, four tests, all passing.

## Cost calculation: monthly usage rolls up into a cost figure per tenant

```
--- POST /generate, 1 million tokens in each category ---
status: 200
{ "period_used": 4000000, "period_limit": 5000000, "recorded": true, ... }

--- GET /usage, cost breakdown ---
status: 200
{
  "ai_tokens": {
    "breakdown": {
      "cached_input_tokens": 1000000,
      "input_tokens": 1000000,
      "output_tokens": 1000000,
      "reasoning_tokens": 1000000
    },
    "limit": 5000000,
    "used": 4000000
  },
  "cost": {
    "ai_tokens_cost_cents": 3375,
    "currency": "usd"
  }
}
```

`GET /usage` rolls the tenant's events for the current month into a used and limit figure for both usage types, plus a cost in cents for AI tokens.

## AI token pricing: cached input cheaper, reasoning billed as output, categories priced separately

Pricing constants pinned in `app/pricing.py`:

```
{'input': 300, 'cached_input': 75, 'output': 1500}
```

That is 300 cents per million input tokens, 75 cents per million cached input tokens, and 1500 cents per million output tokens, with reasoning tokens billed at that same 1500 rate.

One million tokens in every one of the four categories:

```
expected cost from pricing module: 3375 cents
cost reported by GET /usage:       3375 cents
match: True
```

The math behind that number: 1,000,000 input tokens at 300 cents per million is 300 cents. 1,000,000 cached input tokens at 75 cents per million is 75 cents. Output and reasoning tokens are combined before pricing, so 2,000,000 combined tokens at 1500 cents per million is 3000 cents. 300 plus 75 plus 3000 is 3375 cents, exactly what both the pricing module and the live `GET /usage` response report. `tests/test_cost.py` has six unit tests against the pricing module directly, including one that checks cached input is strictly cheaper than fresh input for the same token count, and one that checks 500,000 input plus 500,000 output tokens does not cost the same as treating all one million as input, proving the categories are priced separately rather than summed first. All six pass, plus one more test that checks the live `GET /usage` number matches the pricing module for a mixed request.

## Stripe integration: webhooks verify signatures, ignore duplicates, update tenant plan and status

Valid signed `checkout.session.completed` event:

```
--- POST /webhooks/stripe, valid signature ---
status: 200
{ "outcome": "tenant 1 upgraded to pro", "received": true }

tenant 1 plan after webhook: pro
```

Forged signature on the same payload:

```
--- POST /webhooks/stripe, forged signature ---
status: 400
{ "detail": "no matching signature found", "error": "signature verification failed" }
```

The same event id sent a second time:

```
--- POST /webhooks/stripe, same event id sent again ---
status: 200
{ "outcome": "ignored, already processed", "received": true }
```

The tenant's plan flipped from free to pro through a verified webhook, a forged signature is rejected with 400 and changes nothing, and replaying the same event id is a no op the second time. `customer.subscription.deleted` downgrading a tenant back to free is covered by `tests/test_webhooks.py::test_subscription_deleted_downgrades_tenant_to_free`, which also passes. Five webhook tests total, all passing.

## Stripe integration: subscription checkout

The `POST /checkout` endpoint builds a real request to `https://api.stripe.com/v1/checkout/sessions` using the Stripe REST API directly, no SDK. This sandbox has no outbound network access, so the request could not actually reach Stripe from here. The request construction was verified with a stubbed HTTP call standing in for the network:

```
request url: https://api.stripe.com/v1/checkout/sessions
request data: {
  "cancel_url": "http://localhost:5000/checkout/cancel",
  "client_reference_id": "1",
  "line_items[0][price]": "price_fake_pro",
  "line_items[0][quantity]": "1",
  "metadata[tenant_id]": "1",
  "mode": "subscription",
  "success_url": "http://localhost:5000/checkout/success"
}
returned session: {'id': 'cs_demo_session', 'url': 'https://checkout.stripe.com/pay/cs_demo_session'}
```

This is a subscription mode session carrying the tenant id both as `client_reference_id` and in `metadata`, which is exactly what the webhook handler reads back out of `checkout.session.completed` to know which tenant to upgrade, and the proof above shows that half of the loop working for real. Running this against a real Stripe test account only requires setting `STRIPE_SECRET_KEY` and `STRIPE_PRICE_ID_PRO` in `.env`, the code path does not change.

## Data model: tenants, plans, subscriptions, usage events, isolated per tenant

`migrations/001_init.sql` defines `tenants`, `usage_events`, `idempotency_responses`, `subscriptions`, `processed_stripe_events` and `usage_rollups`. Every query in `app/meter_service.py`, `app/usage_service.py` and `app/webhook_service.py` filters by `tenant_id`, and `usage_events` has a unique constraint on `(tenant_id, idempotency_key)` enforced by SQLite itself, not just application code.

## Full test suite

```
test_checkout_session_request_is_built_correctly ... ok
test_cached_input_tokens_are_cheaper_than_fresh_input ... ok
test_categories_are_not_simply_summed_before_pricing ... ok
test_input_tokens_priced_at_input_rate ... ok
test_known_totals_match_the_pinned_pricing_constants ... ok
test_reasoning_tokens_are_billed_at_the_output_rate ... ok
test_zero_tokens_cost_zero ... ok
test_usage_endpoint_cost_matches_pricing_module ... ok
test_different_keys_record_separate_events ... ok
test_missing_fields_return_400_not_500 ... ok
test_replayed_key_after_quota_would_change_still_mirrors_original ... ok
test_same_key_sent_twice_records_one_event ... ok
test_unknown_tenant_returns_404_not_500 ... ok
test_ai_token_quota_uses_total_of_all_categories ... ok
test_free_plan_exact_boundary_is_allowed ... ok
test_free_plan_one_over_boundary_returns_402 ... ok
test_pro_plan_over_boundary_returns_429 ... ok
test_checkout_completed_upgrades_tenant_to_pro ... ok
test_forged_signature_is_rejected_with_400 ... ok
test_missing_signature_header_is_rejected ... ok
test_replayed_event_is_processed_only_once ... ok
test_subscription_deleted_downgrades_tenant_to_free ... ok

----------------------------------------------------------------------
Ran 22 tests in 0.176s

OK
```

Reproduce this yourself with `python -m unittest discover -s tests -v` on a clean checkout.
