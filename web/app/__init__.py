# app/__init__.py
from __future__ import annotations
from datetime import datetime
import logging
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
login_manager.login_view = "pages.login"
# Protection de session optionnelle
login_manager.session_protection = "strong"

# Socket.IO (par défaut sans Redis, un seul worker/process)
socketio = SocketIO(
    async_mode="eventlet",
    cors_allowed_origins="*",
    message_queue=None,
)

def create_app():
    app = Flask(__name__)
    cfg = get_config()
    app.config.from_object(cfg)

    # Init extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    # Blueprints
    from .pages.views import bp as pages_bp
    app.register_blueprint(pages_bp)

    from .auth.views import bp as auth_bp
    app.register_blueprint(auth_bp)

    from .events.views import bp_events, bp_public
    app.register_blueprint(bp_events)
    app.register_blueprint(bp_public)

    # Filtres Jinja utiles
    @app.template_filter("ts_human")
    def ts_human(ts):
        try:
            if not ts:
                return "—"
            if isinstance(ts, (int, float)):
                return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
            return ts.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return str(ts)

    # Healthcheck simple
    @app.get("/healthz")
    def healthz():
        try:
            db.session.execute("SELECT 1")
            db_ok = True
        except Exception:
            db_ok = False
        return {"status": "healthy" if db_ok else "degraded"}

    # >>> IMPORTANT : pas de reconfiguration Redis <<<
    # Même si REDIS_URL existe dans l'env, on NE re-crée PAS un SocketIO avec message_queue.
    # On reste strictement en message_queue=None (in-process).

    # Socket handlers (join_event, etc.)
    from .sockets import register_socketio_handlers
    register_socketio_handlers(socketio)

    # CLI (seed templates) — optionnel
    try:
        from .seeds_templates import register_cli as register_seed_cli
        register_seed_cli(app)
    except Exception:
        pass

    return app
