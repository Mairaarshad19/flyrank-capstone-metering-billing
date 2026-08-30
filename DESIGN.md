Design Document, Usage Metering and Billing Engine

Problem

Every tenant on this platform can call one billable endpoint that either logs an API call or logs AI token usage. The service needs to record that usage exactly once even if the caller retries the request, needs to stop a tenant once they cross their plan limit, needs to turn raw usage into a dollar figure using real token pricing rules, and needs to keep a tenant's plan in sync with Stripe without trusting the client to tell us what they paid for.

Data model

tenants: id, name, plan, created_at. Plan is either free or pro.

usage_events: id, tenant_id, usage_type, quantity, idempotency_key, input_tokens, cached_input_tokens, output_tokens, reasoning_tokens, created_at. There is a unique constraint on tenant_id plus idempotency_key so the same key can never produce two rows for the same tenant.

idempotency_responses: tenant_id, idempotency_key, status_code, response_body, created_at. Stores the exact response that was returned the first time a key was used, so a retry gets the identical answer instead of being recomputed.

subscriptions: id, tenant_id, stripe_customer_id, stripe_subscription_id, status, updated_at. Mirrors what Stripe told us through a verified webhook.

processed_stripe_events: stripe_event_id, created_at. One row per Stripe event id we have already applied, used to drop replays.

usage_rollups: tenant_id, period, api_calls_used, ai_tokens_used, ai_tokens_cost_cents, computed_at. A cache table that the background rollup job writes to, separate from the live numbers that GET /usage computes on demand.

API surface

POST /generate, the one dummy billable endpoint. Body carries tenant_id, idempotency_key, usage_type, and either quantity for api_call or a token breakdown for ai_tokens. Returns 200 with the usage event and current totals, 429 when a paid plan has used up its monthly allowance, or 402 when a free plan would need to upgrade to continue.

GET /usage, query param tenant_id, returns used and limit for both usage types plus the computed AI token cost in cents for the current period.

POST /checkout, body carries tenant_id, creates a Stripe test mode checkout session for the Pro plan and returns the session url.

POST /webhooks/stripe, receives raw Stripe events, verifies the signature, ignores anything already processed, and updates the tenant's plan and subscription row.

Idempotency strategy

Every write to usage_events happens inside a single database transaction that first tries to insert into idempotency_responses. Because tenant_id plus idempotency_key is a unique key, a concurrent or repeated request with the same key will fail that insert, and the handler falls back to reading and returning the response that was already stored, without touching usage_events a second time. This is enforced by the database, not just by application logic, so a race condition cannot slip through.

Non goal

This capstone does not implement overage billing, invoices, proration, or a reconciliation job against Stripe. Those are listed as stretch goals and are intentionally left out so the core stays small and correct.
