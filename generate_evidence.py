import json
import os
import time

os.environ["DATABASE_PATH"] = "data/evidence.db"
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test_secret_for_evidence"
os.environ["STRIPE_SECRET_KEY"] = "sk_test_fake_for_evidence"
os.environ["STRIPE_PRICE_ID_PRO"] = "price_fake_pro"

if os.path.exists("data/evidence.db"):
    os.remove("data/evidence.db")

from app import create_app
from app.db import get_connection
from app.stripe_client import sign_payload
from app.pricing import calculate_ai_token_cost_cents, TOKEN_PRICE_CENTS_PER_MILLION

app = create_app()
client = app.test_client()

conn = get_connection("data/evidence.db")
conn.execute("INSERT INTO tenants (id, name, plan) VALUES (1, 'Acme Corp', 'free')")
conn.execute("INSERT INTO tenants (id, name, plan) VALUES (2, 'Globex Inc', 'pro')")
conn.commit()
conn.close()


def show(title, response):
    print(f"--- {title} ---")
    print(f"status: {response.status_code}")
    print(json.dumps(response.get_json(), indent=2, sort_keys=True))
    replay_header = response.headers.get("X-Idempotent-Replay")
    if replay_header is not None:
        print(f"X-Idempotent-Replay: {replay_header}")
    print()


print("=" * 70)
print("PROOF 1: idempotent metering, same key sent twice")
print("=" * 70)
r1 = client.post("/generate", json={"tenant_id": 1, "idempotency_key": "demo-key-1", "usage_type": "api_call", "quantity": 5})
show("POST /generate, first send", r1)
r2 = client.post("/generate", json={"tenant_id": 1, "idempotency_key": "demo-key-1", "usage_type": "api_call", "quantity": 5})
show("POST /generate, identical retry", r2)
r3 = client.get("/usage?tenant_id=1")
show("GET /usage, used is 5 not 10", r3)
print(f"bodies identical on retry: {r1.get_json() == r2.get_json()}")
print()

print("=" * 70)
print("PROOF 2: quota boundary, free plan")
print("=" * 70)
r4 = client.post("/generate", json={"tenant_id": 1, "idempotency_key": "fill-995", "usage_type": "api_call", "quantity": 995})
show("POST /generate, brings tenant to exactly 1000 of 1000", r4)
r5 = client.post("/generate", json={"tenant_id": 1, "idempotency_key": "over-by-one", "usage_type": "api_call", "quantity": 1})
show("POST /generate, one more call past the limit", r5)
print()

print("=" * 70)
print("PROOF 3: quota boundary, pro plan")
print("=" * 70)
r6 = client.post("/generate", json={"tenant_id": 2, "idempotency_key": "fill-pro", "usage_type": "api_call", "quantity": 100000})
show("POST /generate, brings pro tenant to exactly 100000 of 100000", r6)
r7 = client.post("/generate", json={"tenant_id": 2, "idempotency_key": "over-pro", "usage_type": "api_call", "quantity": 1})
show("POST /generate, one more call past the pro limit", r7)
print()

print("=" * 70)
print("PROOF 4: ai token cost calculation, pinned pricing constants")
print("=" * 70)
print(f"pricing constants: {TOKEN_PRICE_CENTS_PER_MILLION}")
r8 = client.post("/generate", json={
    "tenant_id": 2,
    "idempotency_key": "tokens-demo",
    "usage_type": "ai_tokens",
    "tokens": {"input_tokens": 1000000, "cached_input_tokens": 1000000, "output_tokens": 1000000, "reasoning_tokens": 1000000},
})
show("POST /generate, 1 million tokens in each category", r8)
r9 = client.get("/usage?tenant_id=2")
show("GET /usage, cost breakdown", r9)
expected = calculate_ai_token_cost_cents(input_tokens=1000000, cached_input_tokens=1000000, output_tokens=1000000, reasoning_tokens=1000000)
reported = r9.get_json()["cost"]["ai_tokens_cost_cents"]
print(f"expected cost from pricing module: {expected} cents")
print(f"cost reported by GET /usage:       {reported} cents")
print(f"match: {expected == reported}")
print()

print("=" * 70)
print("PROOF 5: stripe checkout completed webhook, verified signature")
print("=" * 70)
event = {
    "id": "evt_checkout_demo",
    "type": "checkout.session.completed",
    "data": {"object": {"client_reference_id": "1", "customer": "cus_demo", "subscription": "sub_demo"}},
}
payload = json.dumps(event).encode()
secret = os.environ["STRIPE_WEBHOOK_SECRET"]
good_sig = sign_payload(payload, secret)
r10 = client.post("/webhooks/stripe", data=payload, headers={"Stripe-Signature": good_sig, "Content-Type": "application/json"})
show("POST /webhooks/stripe, valid signature", r10)
r11 = client.get("/usage?tenant_id=1")
print(f"tenant 1 plan after webhook: {r11.get_json()['plan']}")
print()

print("=" * 70)
print("PROOF 6: forged webhook signature rejected")
print("=" * 70)
timestamp = int(time.time())
forged_sig = f"t={timestamp},v1=" + "0" * 64
r12 = client.post("/webhooks/stripe", data=payload, headers={"Stripe-Signature": forged_sig, "Content-Type": "application/json"})
show("POST /webhooks/stripe, forged signature", r12)
print()

print("=" * 70)
print("PROOF 7: replayed webhook event processed only once")
print("=" * 70)
r13 = client.post("/webhooks/stripe", data=payload, headers={"Stripe-Signature": good_sig, "Content-Type": "application/json"})
show("POST /webhooks/stripe, same event id sent again", r13)
print()

print("=" * 70)
print("PROOF 8: checkout session request built correctly (mocked http call)")
print("=" * 70)
print("this sandbox has no outbound network access, so the actual call to")
print("api.stripe.com cannot be made from here, the http call is stubbed")
print("to prove the request shape is correct, see tests/test_checkout.py")
from app.stripe_client import create_checkout_session


class FakeResp:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


captured = {}


def fake_post(url, data=None, auth=None, timeout=None):
    captured["url"] = url
    captured["data"] = data
    captured["auth"] = auth
    return FakeResp({"id": "cs_demo_session", "url": "https://checkout.stripe.com/pay/cs_demo_session"})


session = create_checkout_session(tenant_id=1, http_post=fake_post)
print(f"request url: {captured['url']}")
print(f"request data: {json.dumps(captured['data'], indent=2, sort_keys=True)}")
print(f"returned session: {session}")

os.remove("data/evidence.db")
