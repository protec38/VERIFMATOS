# app/__init__.py — FINAL DEFINITIF (avec fallback Redis sûr)
from __future__ import annotations
from datetime import datetime
from flask import Flask, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_socketio import SocketIO
from .config import get_config

# Extensions
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
# Crée l’instance SocketIO sans MQ, on décidera au runtime si on active Redis
socketio = SocketIO(async_mode="eventlet", cors_allowed_origins="*")

def create_app() -> Flask:
    app = Flask(__name__, instance_relative_config=False)

    # Config
    app.config.from_object(get_config())

    # Init extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = "pages.login"

    # Import models to make migrations aware
    from . import models  # noqa: F401

    # Socket.IO — tente d'activer Redis MQ seulement si possible
    redis_url = app.config.get("REDIS_URL")
    if redis_url:
        try:
            import redis  # Vérifie la présence du client Python
            socketio.init_app(app, message_queue=redis_url)
            app.logger.info("SocketIO: Redis MQ activé (%s).", redis_url)
        except Exception as e:
            # Fallback: pas de MQ, évite le crash "Redis package is not installed"
            socketio.init_app(app)
            app.logger.warning("SocketIO: Redis MQ indisponible (%s). Démarrage sans MQ.", e)
    else:
        socketio.init_app(app)
        app.logger.info("SocketIO: démarrage sans message queue (REDIS_URL vide).")

    # Jinja globals
    @app.context_processor
    def inject_now():
        return {"now": datetime.utcnow}

    # Register API blueprints
    from .auth.views import bp as auth_api_bp
    app.register_blueprint(auth_api_bp)
    from .admin.views import bp as admin_api_bp
    app.register_blueprint(admin_api_bp)
    from .events.views import bp as events_api_bp
    app.register_blueprint(events_api_bp)
    from .stock.views import bp as stock_api_bp
    app.register_blueprint(stock_api_bp)
    from .verify.views import bp as verify_api_bp
    app.register_blueprint(verify_api_bp)
    from .reports.views import bp as reports_api_bp
    app.register_blueprint(reports_api_bp)
    from .stats.views import bp as stats_api_bp
    app.register_blueprint(stats_api_bp)
    from .pwa.views import bp as pwa_bp
    app.register_blueprint(pwa_bp)

    # Pages (HTML)
    from .views_html import bp as pages_bp
    app.register_blueprint(pages_bp)

    # Health / root
    @app.get("/")
    def index():
        return redirect(url_for("pages.dashboard"))

    @app.get("/health")
    def health():
        return {"status": "healthy"}

    # Socket handlers
    from .sockets import register_socketio_handlers
    register_socketio_handlers(socketio)

    # CLI (seed templates)
    try:
        from .seeds_templates import register_cli as register_seed_cli
        register_seed_cli(app)
    except Exception:
        # optional; ignore if not present
        pass

    return app
