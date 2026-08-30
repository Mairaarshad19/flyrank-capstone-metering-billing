# All money is handled as integer cents. Never floats. Never anywhere in this file.

PLAN_LIMITS = {
    "free": {
        "api_calls": 1000,
        "ai_tokens": 100000,
    },
    "pro": {
        "api_calls": 100000,
        "ai_tokens": 5000000,
    },
}

# Prices are cents per one million tokens, pinned here so EVIDENCE.md can point
# straight at these numbers and GET /usage must match what falls out of them.
TOKEN_PRICE_CENTS_PER_MILLION = {
    "input": 300,          # $3.00 per million input tokens
    "cached_input": 75,    # cached input tokens are cheaper than fresh input
    "output": 1500,        # $15.00 per million output tokens
    # reasoning tokens are not a separate category, they are billed at the
    # output rate, per the pricing rule this capstone has to encode correctly
}


def calculate_ai_token_cost_cents(input_tokens=0, cached_input_tokens=0, output_tokens=0, reasoning_tokens=0):
    """Turns a token breakdown into a cost in integer cents.

    Token categories cannot simply be added together before pricing, because
    they price differently. Reasoning tokens are folded into the output
    bucket before pricing, since they are billed at the output rate.
    """
    input_cost = (input_tokens * TOKEN_PRICE_CENTS_PER_MILLION["input"]) // 1_000_000
    cached_cost = (cached_input_tokens * TOKEN_PRICE_CENTS_PER_MILLION["cached_input"]) // 1_000_000
    billable_output_tokens = output_tokens + reasoning_tokens
    output_cost = (billable_output_tokens * TOKEN_PRICE_CENTS_PER_MILLION["output"]) // 1_000_000
    return input_cost + cached_cost + output_cost


def plan_limit(plan, usage_type):
    return PLAN_LIMITS[plan][usage_type]
