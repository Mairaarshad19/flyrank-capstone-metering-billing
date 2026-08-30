# Build log

Honest record of how this was built, kept as I went rather than written after the fact from memory.

## Where AI helped

I used Claude for most of the first pass of this codebase: the Flask route structure, the SQLite schema, the idempotency transaction pattern, the Stripe signature verification function, and the test suite. I gave it the capstone brief and asked it to work through the phases in order rather than dump the whole thing at once, which matched how the brief itself is structured.

## What it got wrong, and what I changed

The first version of `app/pricing.py` had a `plan_limit` function that indexed straight into `PLAN_LIMITS[plan][usage_type]`, but `usage_type` in the rest of the code is `"api_call"` or `"ai_tokens"`, while the pricing dictionary keys are `"api_calls"` and `"ai_tokens"`. That mismatch caused a `KeyError` the first time `POST /generate` was actually exercised end to end, not caught by writing the function in isolation, only by running it. I added a small mapping table, `_USAGE_TYPE_TO_LIMIT_KEY`, so the function accepts either spelling and translates it before the lookup. This is the kind of bug that a unit test on `pricing.py` alone would not have caught, since the function would happily return a value for a key that actually exists in the dictionary, the bug only shows up when you call it with the string the rest of the app actually uses. That is exactly the sort of thing the capstone brief means by boundary honesty, a bug that only shows up under real conditions, not under an isolated test of the function in question.

I also had to decide, and this was not obvious from the brief, exactly which status code goes with which plan when a request is blocked. I chose 402 for free plan tenants and 429 for pro plan tenants, reasoning that a free tenant genuinely cannot proceed without paying, which is what 402 means, while a pro tenant can simply wait for the next billing cycle, which is what 429 is for. This is documented in the README and is a decision I own, not something the AI picked without me checking it against the glossary in the brief.

## What I can explain

I can walk through any part of this codebase. A few specific things worth calling out because they were not obvious to me at first:

The idempotency guarantee does not rely on application level checking and hoping nothing races. `usage_events` has a real unique constraint on `(tenant_id, idempotency_key)` at the database level, and the whole read and write happens inside one `BEGIN IMMEDIATE` transaction in `meter_service.record_usage`. Even if two requests with the same key landed at the same instant, SQLite serializes the writers, so only one of them can actually insert the row.

The webhook signature check in `app/stripe_client.py` is not using the Stripe SDK, it is a plain HMAC-SHA256 implementation that follows the same algorithm Stripe documents: take the timestamp and the raw payload, join them with a dot, HMAC it with the webhook secret, and compare hex digests using a constant time comparison so an attacker cannot use timing to guess the signature one byte at a time. I chose not to pull in the Stripe python package because this sandbox has no network access to install it, and doing the verification by hand also made it something I could actually explain rather than trust a library to get right.

## What was not run for real

The actual network call to Stripe to create a checkout session was never made from this environment, because this environment cannot reach the internet. I know this because I tried it and got a connection error, not because I assumed it. Everything downstream of that, the webhook handling, the signature verification, the plan sync, was tested for real using signed payloads constructed the same way Stripe constructs them. The README says this plainly rather than implying the whole Stripe flow was exercised end to end against the live test API, because it was not.

## Time spent

Roughly the estimate in the brief, spread across the phases, design and schema first, then the metering and quota logic, then Stripe, then pulling the documentation together at the end.
