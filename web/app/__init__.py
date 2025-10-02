# app/__init__.py
from __future__ import annotations

import importlib
from flask import Flask, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_socketio import SocketIO

from .config import get_config

# -----------------
# Extensions (déclarées au niveau module)
# -----------------
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()  # ne rien passer au ctor

# Socket.IO en local (AUCUN Redis) — instance non liée, on fera init_app(app) après
socketio = SocketIO(
    async_mode="eventlet",
    cors_allowed_origins="*",
    message_queue=None,  # Redis désactivé
)


def _register_bp_if_any(app: Flask, dotted_module: str, candidates: tuple[str, ...] = ("bp", "bp_events", "bp_public")) -> bool:
    """
    Importe un module et enregistre le premier Blueprint trouvé parmi `candidates`.
    Retourne True si un blueprint a été enregistré, False sinon.
    """
    try:
        mod = importlib.import_module(dotted_module)
    except Exception:
        return False

    for name in candidates:
        bp = getattr(mod, name, None)
        if bp is not None:
            app.register_blueprint(bp)
            return True
    return False


def create_app() -> Flask:
    app = Flask(__name__)
    cfg = get_config()
    app.config.from_object(cfg)

    # Init extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    try:
        login_manager.session_protection = "strong"
    except Exception:
        pass

    # Lier Socket.IO à l'app (pas de Redis)
    try:
        socketio.init_app(app)
    except Exception:
        # On ne casse pas l'app si SocketIO échoue
        pass

    # -----------------
    # Blueprints (robuste : on tolère les absents, et plusieurs noms d'attribut)
    # -----------------
    _register_bp_if_any(app, "app.auth.views")
    _register_bp_if_any(app, "app.admin.views")
    _register_bp_if_any(app, "app.stock.views")

    # Verify contient aussi les routes publiques /public/event/<token>/...
    _register_bp_if_any(app, "app.verify.views")

    # Events API (POST /events, GET /events/<id>/tree, etc.)
    _register_bp_if_any(app, "app.events.views", candidates=("bp", "bp_events", "bp_public"))

    # Optionnels
    _register_bp_if_any(app, "app.reports.views")
    _register_bp_if_any(app, "app.stats.views")
    _register_bp_if_any(app, "app.pwa.views")

    # Péremption (nouveau)
    _register_bp_if_any(app, "app.peremption.views", candidates=("bp_peremption", "bp"))

    # Pages HTML (public + dashboard)
    _register_bp_if_any(app, "app.views_html")

    # Root → redirige vers dashboard (évite la page blanche)
    @app.get("/")
    def _root_redirect():
        return redirect(url_for("pages.dashboard"))

    # Healthcheck
    @app.get("/healthz")
    def healthz():
        try:
            db.session.execute("SELECT 1")
            db_ok = True
        except Exception:
            db_ok = False
        return {"status": "healthy" if db_ok else "degraded"}

    # Socket.IO handlers (si présents)
    try:
        from .sockets import register_socketio_handlers
        register_socketio_handlers(socketio)
    except Exception:
        pass

    # Flask-Login user loader (placé ici pour éviter les imports circulaires)
    @login_manager.user_loader
    def load_user(user_id: str):
        from .models import User  # import tardif : db déjà initialisé
        try:
            return db.session.get(User, int(user_id))
        except Exception:
            return None

    return app


# ⚠️ Pas de création d'instance globale ici (pas de `app = create_app()`)
# Lancer via wsgi.py ou gunicorn : `from app import create_app; app = create_app()`
