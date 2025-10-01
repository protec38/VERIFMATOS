# app/__init__.py
from __future__ import annotations
from datetime import datetime

from flask import Flask
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

# IMPORTANT: ne pas passer login_view au constructeur
login_manager = LoginManager()

# Socket.IO en local (AUCUN Redis)
socketio = SocketIO(
    async_mode="eventlet",
    cors_allowed_origins="*",
    message_queue=None,  # <= Redis désactivé
)


def create_app():
    app = Flask(__name__)
    cfg = get_config()
    app.config.from_object(cfg)

    # Init extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    # Définir les propriétés du login_manager APRÈS la création
    # (si l’endpoint n’existe pas, ça ne plante pas ici)
    login_manager.login_view = "auth.login"
    try:
        # Optionnel / rétro-compat: certaines versions ignorent cette prop
        login_manager.session_protection = "strong"
    except Exception:
        pass

    # -----------------
    # Blueprints API
    # -----------------
    try:
        from .auth.views import bp as auth_api_bp
        app.register_blueprint(auth_api_bp)
    except Exception:
        pass

    try:
        from .admin.views import bp as admin_api_bp
        app.register_blueprint(admin_api_bp)
    except Exception:
        pass

    try:
        from .stock.views import bp as stock_api_bp
        app.register_blueprint(stock_api_bp)
    except Exception:
        pass

    try:
        from .verify.views import bp as verify_api_bp
        app.register_blueprint(verify_api_bp)
    except Exception:
        pass

    # Modules optionnels
    for mod in ("reports", "stats", "pwa"):
        try:
            module = __import__(f"{__name__}.{mod}.views", fromlist=["bp"])
            app.register_blueprint(getattr(module, "bp"))
        except Exception:
            pass

    # -----------------
    # Pages HTML (public + dashboard)
    # -----------------
    # Ton projet d’avant utilise le blueprint déclaré dans views_html.py
    try:
        from .views_html import bp as pages_bp
        app.register_blueprint(pages_bp)
    except Exception:
        pass

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

# Flask-Login user loader (si ton models.User existe)
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
