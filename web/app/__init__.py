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
login_manager = LoginManager(
    login_view="auth.login",
    session_protection="strong"
)

# Socket.IO in-process (pas de Redis ici)
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

    # Blueprints API
    from .auth.views import bp as auth_api_bp
    app.register_blueprint(auth_api_bp)

    from .admin.views import bp as admin_api_bp
    app.register_blueprint(admin_api_bp)

    from .stock.views import bp as stock_api_bp
    app.register_blueprint(stock_api_bp)

    from .verify.views import bp as verify_api_bp
    app.register_blueprint(verify_api_bp)

    # Reports / Stats / PWA si présents
    try:
        from .reports.views import bp as reports_api_bp
        app.register_blueprint(reports_api_bp)
    except Exception:
        pass

    try:
        from .stats.views import bp as stats_api_bp
        app.register_blueprint(stats_api_bp)
    except Exception:
        pass

    try:
        from .pwa.views import bp as pwa_bp
        app.register_blueprint(pwa_bp)
    except Exception:
        pass

    # Pages HTML (public + dashboard)
    from .views_html import bp as pages_bp
    app.register_blueprint(pages_bp)

    # Healthcheck simple
    @app.get("/healthz")
    def healthz():
        try:
            db.session.execute("SELECT 1")
            db_ok = True
        except Exception:
            db_ok = False
        return {"status": "healthy" if db_ok else "degraded"}

    # Handlers Socket.IO
    try:
        from .sockets import register_socketio_handlers
        register_socketio_handlers(socketio)
    except Exception:
        pass

    return app

# Instance pour wsgi
app = create_app()
