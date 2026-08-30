# Usage Metering and Billing Engine

A small backend service that answers the three questions every SaaS billing system has to answer: how much has this tenant used, how much should they pay, and have they hit their plan limit. Built for the FlyRank internship backend track capstone.

## What it does

Tenants belong to a plan, either free or pro. Every tenant can call one billable endpoint, `POST /generate`, which either logs an API call or logs AI token usage. The service:

- records usage exactly once per idempotency key, so a retried request never double counts
- checks the request against the tenant's plan limit before allowing it, and returns 402 or 429 with a clear reason when it is blocked
- turns AI token usage into a cost in cents using pricing rules where cached input tokens are cheaper and reasoning tokens are billed at the output rate
- lets a tenant upgrade to pro through a Stripe test mode checkout, and keeps the tenant's plan in sync through signature verified, deduplicated webhooks

## Architecture

```
Client
  |
  |  POST /generate  (tenant_id, idempotency_key, usage_type, quantity or tokens)
  v
generate route
  |
  v
meter_service.record_usage
  |-- idempotency_responses has this key already? --> return the stored response, nothing else happens
  |-- otherwise: look up tenant, sum this period's usage, add the new request
  |-- total within the plan limit?   yes -> insert into usage_events, return 200
  |                                  no, plan is free  -> return 402, "upgrade to pro to continue"
  |                                  no, plan is pro   -> return 429, "resets next month"
  |-- store the response in idempotency_responses under this tenant and key

Client
  |
  |  GET /usage?tenant_id=1
  v
usage_service.get_usage_summary
  |-- sums usage_events for the current month
  |-- runs the ai token totals through pricing.calculate_ai_token_cost_cents
  |-- returns used, limit and cost for both api_calls and ai_tokens

Client
  |
  |  POST /checkout  (tenant_id)
  v
stripe_client.create_checkout_session --> Stripe test mode --> checkout url

Stripe
  |
  |  POST /webhooks/stripe  (signed event)
  v
webhooks route
  |-- verify_webhook_signature, HMAC-SHA256 over timestamp.payload, bad signature -> 400
  |-- webhook_service.apply_event
        |-- event id already in processed_stripe_events? --> ignore, return 200
        |-- checkout.session.completed        --> tenant plan set to pro, subscription row created
        |-- customer.subscription.updated     --> tenant plan follows the new status
        |-- customer.subscription.deleted     --> tenant plan set back to free
        |-- mark the event id as processed
```

A background job, `app/jobs/rollup_job.py`, walks every tenant and writes a cached usage rollup into `usage_rollups`. It is meant to run on a schedule rather than inside a request, retries up to three times per tenant, and logs an error if a tenant's rollup keeps failing. `GET /usage` never reads from this cache, it always computes the live number, the cache exists for a dashboard or export job that does not need to recompute the aggregate on every read.

## Data model

Six tables, all in `migrations/001_init.sql`: `tenants`, `usage_events`, `idempotency_responses`, `subscriptions`, `processed_stripe_events`, `usage_rollups`. Every usage row, every subscription row and every rollup row carries a `tenant_id`, and every query in the service layer filters by it, so one tenant never sees another tenant's numbers.

## Plans

| Plan | API calls per month | AI tokens per month |
|------|---------------------|----------------------|
| Free | 1,000 | 100,000 |
| Pro  | 100,000 | 5,000,000 |

These live in `app/pricing.py` as `PLAN_LIMITS`. At exactly the limit a request is still allowed, the request that would push the tenant over the limit is the one that gets rejected.

## Status codes

A blocked request on the free plan returns 402, because a free tenant genuinely cannot do more without upgrading. A blocked request on the pro plan returns 429, because a pro tenant can simply wait for the next billing period. Both responses include a `reason` field explaining why.

## AI token pricing

Prices are pinned in `app/pricing.py` as cents per one million tokens, and all math is done with integer division, cents are never represented as floats anywhere in this codebase.

| Token category | Price per million tokens |
|-----------------|---------------------------|
| input | 300 cents |
| cached input | 75 cents |
| output | 1500 cents |
| reasoning | billed at the output rate, 1500 cents |

Reasoning tokens are folded into the output bucket before pricing rather than kept as their own category, and the three priced categories, input, cached input and output, are never simply added together before pricing, each is priced on its own and the results are summed. `EVIDENCE.md` has a worked example: one million tokens in every category comes out to exactly 3375 cents, and `tests/test_cost.py` checks this same number.

## Running it

Requires Python 3.10 or newer. No Docker and no Postgres needed, this project uses SQLite, which the capstone brief lists as an accepted free alternative to Postgres via Docker.

```
pip install -r requirements.txt
cp .env.example .env
python seed.py
python run.py
```

The server listens on port 5000. `seed.py` creates two tenants: tenant 1, Acme Corp, on the free plan, and tenant 2, Globex Inc, on the pro plan. Run it again any time to reset the database back to that starting point.

To run the background rollup job by hand:

```
python -m app.jobs.rollup_job
```

To run the tests:

```
python -m unittest discover -s tests -v
```

All 22 tests pass on a clean checkout, see `EVIDENCE.md` for the full output.

Everything pasted into `EVIDENCE.md` was produced by `generate_evidence.py`, which drives the app through the same test client the tests use and prints real request and response bodies. Run `python generate_evidence.py` yourself to reproduce it.

## Trying the endpoints

```
curl -X POST http://localhost:5000/generate \
  -H "Content-Type: application/json" \
  -d '{"tenant_id": 1, "idempotency_key": "some-unique-key", "usage_type": "api_call", "quantity": 1}'

curl "http://localhost:5000/usage?tenant_id=1"

curl -X POST http://localhost:5000/checkout \
  -H "Content-Type: application/json" \
  -d '{"tenant_id": 1}'
```

To test webhooks locally with a real Stripe test account, install the Stripe CLI, then:

```
stripe listen --forward-to localhost:5000/webhooks/stripe
stripe trigger checkout.session.completed
```

The CLI prints the `whsec_` value to put in `.env` as `STRIPE_WEBHOOK_SECRET` the first time you run `stripe listen`.

## Limitations, stated honestly

This was built and tested in a sandboxed environment with no outbound network access, so the Stripe API itself was never actually reached from here. Everything that can be verified without a network call has been verified for real: webhook signature verification is pure HMAC-SHA256 and was tested against real signed payloads, event deduplication was tested by sending the same event id twice, and the plan upgrade and downgrade logic was tested end to end through the webhook handler. What was not run for real is the actual `POST` to `api.stripe.com/v1/checkout/sessions`, since that needs network access and a real Stripe test secret key. The request that gets sent is exercised through a stubbed HTTP call in `tests/test_checkout.py`, which confirms the correct mode, price id and tenant reference are sent. Anyone running this project with a real `STRIPE_SECRET_KEY` and `STRIPE_PRICE_ID_PRO` gets the identical code path, `create_checkout_session` does not know or care whether the http call is real or stubbed.

Also out of scope for this core build, matching what the capstone brief calls stretch goals: overage billing, invoices, proration, and a nightly reconciliation job against Stripe.

## Required files

`README.md` (this file), `capstone.yaml`, `EVIDENCE.md`, `BUILDLOG.md`, `.env.example`, `DESIGN.md`.
