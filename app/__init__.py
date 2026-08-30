import os

from flask import Flask

from app.db import init_db


def create_app(db_path=None):
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path or os.environ.get("DATABASE_PATH", "data/billing.db")

    # make sure the schema exists before the first request ever hits the app
    init_db(app.config["DB_PATH"]).close()

    from app.routes.generate import generate_bp
    from app.routes.usage import usage_bp
    from app.routes.checkout import checkout_bp
    from app.routes.webhooks import webhooks_bp

    app.register_blueprint(generate_bp)
    app.register_blueprint(usage_bp)
    app.register_blueprint(checkout_bp)
    app.register_blueprint(webhooks_bp)

    return app
