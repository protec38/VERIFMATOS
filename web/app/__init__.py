# app/__init__.py — FINAL (fallback Redis + user_loader + Jinja globals + preflight Redis)
from __future__ import annotations
import os
from datetime import datetime
from flask import Flask, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_socketio import SocketIO
from .config import get_config

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
# Instance SocketIO; on activera Redis MQ seulement si OK
socketio = SocketIO(async_mode="eventlet", cors_allowed_origins="*")

def create_app() -> Flask:
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(get_config())

    # Extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = "pages.login"

    # Flask-Login: user_loader
    @login_manager.user_loader
    def load_user(user_id: str):
        try:
            from .models import User
            return db.session.get(User, int(user_id))
        except Exception:
            return None

    # Import models pour Alembic
    from . import models  # noqa: F401

    # ---- Socket.IO: activer Redis MQ seulement si le client Python est installé ET que la connexion réussit ----
    redis_url = app.config.get("REDIS_URL")
    disable_mq = os.getenv("DISABLE_REDIS_MQ", "").lower() in ("1", "true", "yes")
    use_queue = False
    if redis_url and not disable_mq:
        try:
            import redis  # client Python
            # preflight de connectivité (évite le thread pubsub en échec)
            r = redis.from_url(redis_url, socket_connect_timeout=1.0, socket_timeout=1.0, decode_responses=True)
            r.ping()
            socketio.init_app(app, message_queue=redis_url)
            use_queue = True
            app.logger.info("SocketIO: Redis MQ activé (%s).", redis_url)
        except Exception as e:
            socketio.init_app(app)  # fallback sans MQ
            app.logger.warning("SocketIO: Redis MQ désactivé (préflight KO: %s). Démarrage sans MQ.", e)
    else:
        socketio.init_app(app)
        if disable_mq:
            app.logger.info("SocketIO: MQ explicitement désactivée (DISABLE_REDIS_MQ=1).")
        else:
            app.logger.info("SocketIO: démarrage sans message queue (REDIS_URL vide).")

    # Jinja globals — injecte 'now' et 'current_user'
    from flask_login import current_user as login_current_user
    @app.context_processor
    def inject_globals():
        return {"now": datetime.utcnow, "current_user": login_current_user}

    # Blueprints API
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

    # Pages HTML
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

    # CLI seeds optionnels
    try:
        from .seeds_templates import register_cli as register_seed_cli
        register_seed_cli(app)
    except Exception:
        pass

    return app
