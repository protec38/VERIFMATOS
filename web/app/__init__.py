# app/__init__.py
from __future__ import annotations
from datetime import datetime

from flask import Flask, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_socketio import SocketIO

from .config import get_config

# -----------------
# Extensions
# -----------------
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()  # ne pas passer d'arguments au ctor

# Socket.IO en local (AUCUN Redis)
socketio = SocketIO(
    async_mode="eventlet",
    cors_allowed_origins="*",
    message_queue=None,  # Redis désactivé
)


def create_app():
    app = Flask(__name__)
    cfg = get_config()
    app.config.from_object(cfg)

    # Init extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    # Propriétés LoginManager APRES init_app
    login_manager.login_view = "auth.login"
    try:
        login_manager.session_protection = "strong"
    except Exception:
        pass

    # -----------------
    # Blueprints API — enregistrés explicitement (PAS de try/except silencieux)
    # -----------------
    # Auth
    from .auth.views import bp as auth_api_bp
    app.register_blueprint(auth_api_bp)

    # Admin
    from .admin.views import bp as admin_api_bp
    app.register_blueprint(admin_api_bp)

    # Stock
    from .stock.views import bp as stock_api_bp
    app.register_blueprint(stock_api_bp)

    # Verify (contient aussi les routes publiques /public/event/<token>/...)
    from .verify.views import bp as verify_api_bp
    app.register_blueprint(verify_api_bp)

    # Events API (POST /events, GET /events/<id>/tree, etc.)
    from .events.views import bp as events_api_bp
    app.register_blueprint(events_api_bp)

    # Modules optionnels (si absents, commenter ces 3 lignes par module)
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

    # -----------------
    # Pages HTML (public + dashboard)
    # -----------------
    from .views_html import bp as pages_bp
    app.register_blueprint(pages_bp)

    # -----------------
    # Root → redirige vers dashboard
    # -----------------
    @app.get("/")
    def _root_redirect():
        return redirect(url_for("pages.dashboard"))

    # -----------------
    # Healthcheck simple
    # -----------------
    @app.get("/healthz")
    def healthz():
        try:
            db.session.execute("SELECT 1")
            db_ok = True
        except Exception:
            db_ok = False
        return {"status": "healthy" if db_ok else "degraded"}

    # -----------------
    # Socket.IO handlers (optionnel)
    # -----------------
    try:
        from .sockets import register_socketio_handlers
        register_socketio_handlers(socketio)
    except Exception:
        pass

    return app


# Instance globale pour wsgi/gunicorn (wsgi:app)
app = create_app()

# Flask-Login user loader
try:
    from .models import User  # type: ignore

    @login_manager.user_loader
    def load_user(user_id: str):
        try:
            return db.session.get(User, int(user_id))
        except Exception:
            return None
except Exception:
    pass
