import os

from dotenv import load_dotenv

load_dotenv()

from app.db import init_db

db_path = os.environ.get("DATABASE_PATH", "data/billing.db")
conn = init_db(db_path)

conn.execute("DELETE FROM usage_events")
conn.execute("DELETE FROM idempotency_responses")
conn.execute("DELETE FROM subscriptions")
conn.execute("DELETE FROM processed_stripe_events")
conn.execute("DELETE FROM usage_rollups")
conn.execute("DELETE FROM tenants")

conn.execute("INSERT INTO tenants (id, name, plan) VALUES (1, 'Acme Corp', 'free')")
conn.execute("INSERT INTO tenants (id, name, plan) VALUES (2, 'Globex Inc', 'pro')")

conn.commit()
conn.close()

print(f"seeded {db_path} with two tenants, tenant 1 is Acme Corp on the free plan, tenant 2 is Globex Inc on the pro plan")
