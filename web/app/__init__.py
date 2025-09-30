# app/__init__.py
from __future__ import annotations

import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager

# Flask-SocketIO est optionnel ; on l'initialise SANS Redis par défaut
try:
    from flask_socketio import SocketIO  # type: ignore
except Exception:  # pragma: no cover
    SocketIO = None  # type: ignore

# --- singletons ---
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()

# On crée l'instance SocketIO maintenant pour que "from app import socketio" fonctionne
socketio = SocketIO(logger=False, engineio_logger=False, cors_allowed_origins="*") if SocketIO else None


def _bool_env(name: str, default: bool = False) -> bool:
    val = os.getenv(name, "").strip().lower()
    if not val:
        return default
    return val in ("1", "true", "yes", "on", "y")


def create_app(config_object: str | None = None) -> Flask:
    """
    Fabrique l'app Flask.
    - Redis est **désactivé par défaut** (message_queue=None).
    - Pour l'activer explicitement : définir SOCKETIO_MESSAGE_QUEUE=redis://host:6379/0
    - Pour désactiver totalement SocketIO : DISABLE_SOCKETS=1
    """
    app = Flask(__name__)

    # ---- configuration ----
    if config_object:
        app.config.from_object(config_object)

    # Valeurs par défaut si non définies ailleurs
    app.config.setdefault("SECRET_KEY", os.getenv("SECRET_KEY", "change-me"))
    app.config.setdefault("SQLALCHEMY_DATABASE_URI", os.getenv("DATABASE_URL", "sqlite:///app.db"))
    app.config.setdefault("SQLALCHEMY_TRACK_MODIFICATIONS", False)

    # ---- init extensions ----
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    # (pas de login_view ici pour éviter de casser si ton endpoint est différent)

    # ---- SocketIO (sans Redis par défaut) ----
    global socketio
    if SocketIO:
        disable_sockets = _bool_env("DISABLE_SOCKETS", False)
        mq_raw = (os.getenv("SOCKETIO_MESSAGE_QUEUE") or "").strip()
        # On n'utilise Redis QUE si tu l'as demandé ET pas désactivé
        use_queue = (not disable_sockets) and mq_raw and mq_raw.lower() not in ("none", "disabled", "off", "0")
        async_mode = os.getenv("SOCKETIO_ASYNC_MODE", "eventlet")  # compatible avec ton worker gunicorn eventlet

        socketio.init_app(
            app,
            cors_allowed_origins="*",
            async_mode=async_mode,
            message_queue=(mq_raw if use_queue else None),  # <- pas de Redis si non demandé
        )
    else:
        socketio = None  # si le paquet n'est pas installé

    # ---- blueprints ----
    # Import tardif pour éviter les boucles d'import
    try:
        from .events.views import bp_events, bp_public  # type: ignore
        app.register_blueprint(bp_events)
        app.register_blueprint(bp_public)
    except Exception:
        pass

    # Enregistre tes autres blueprints si présents, sans casser si absents
    for modpath, attr in (
        (".auth.views", "bp"),
        (".verify.views", "bp"),
        (".ui.views", "bp"),
    ):
        try:
            module = __import__(f"{__name__}{modpath}", fromlist=[attr])
            app.register_blueprint(getattr(module, attr))
        except Exception:
            continue

    return app


# Crée une app globale pour que "gunicorn app:app" fonctionne
app = create_app()
