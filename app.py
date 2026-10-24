import os
from pathlib import Path
from dotenv import load_dotenv

# Load the local .env before importing configuration and route modules when launched by run.bat.
# Imports from the test suite intentionally do not load the user's private .env.
# Existing process-level variables take precedence; secrets are never logged or returned.
if __name__ == "__main__":
    load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

from flask import Flask
from config import SECRET_KEY, PORT, HOST
from database import init_db
from routes.dashboard import dashboard_bp
from routes.experiments import experiments_bp
from routes.chat import chat_bp
from routes.storefront import storefront_bp
from routes.youtube_auth import youtube_auth_bp
from routes.content_studio import content_studio_bp
from routes.products import products_bp
from routes.affiliates import affiliates_bp
from routes.portfolio import portfolio_bp

def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = SECRET_KEY

    # Ensure database is initialised
    init_db()

    # Register modular Blueprints
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(experiments_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(storefront_bp)
    app.register_blueprint(youtube_auth_bp)
    app.register_blueprint(content_studio_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(affiliates_bp)
    app.register_blueprint(portfolio_bp)

    return app

app = create_app()

if __name__ == "__main__":
    print(f"[*] Starting MINT Autonomous Digital Venture Engine on http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=True)
