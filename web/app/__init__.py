# app/__init__.py
from __future__ import annotations

import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager

# Flask-SocketIO est optionnel : on l'initialise sans Redis par défaut
try:
    from flask_socketio import SocketIO
except Exception:  # pragma: no cover
    SocketIO = None  # type: ignore

# ----- extensions singletons -----
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()

# On crée toujours un objet socketio, mais il n'utilisera Redis que si demandé
socketio = SocketIO(logger=False, engineio_logger=False, cors_allowed_origins="*") if SocketIO else None


def create_app(config_object: str | None = None) -> Flask:
    """
    Application factory.
    - Redis est désactivé par défaut (message_queue=None).
    - Pour l'activer, définis explicitement SOCKETIO_MESSAGE_QUEUE (ex: redis://redis:6379/0).
    - Tu peux aussi forcer la désactivation via DISABLE_SOCKETS=1.
    """
    app = Flask(__name__)

    # ---------- configuration ----------
    # Charge d'abord depuis une classe config si fournie
    if config_object:
        app.config.from_object(config_object)

    # Variables d'environnement usuelles (s'il n'y a pas déjà une config)
    app.config.setdefault("SECRET_KEY", os.getenv("SECRET_KEY", "change-me"))
    app.config.setdefault("SQLALCHEMY_DATABASE_URI",
                          os.getenv("DATABASE_URL", "sqlite:///app.db"))
    app.config.setdefault("SQLALCHEMY_TRACK_MODIFICATIONS", False)

    # ---------- init extensions ----------
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    # ----- SocketIO (sans Redis par défaut) -----
    global socketio
    if SocketIO:
        # On ne lit Redis QUE si l'admin l'a explicitement demandé.
        # Cas désactivé si :
        #  - DISABLE_SOCKETS=1
        #  - ou SOCKETIO_MESSAGE_QUEUE absent/vidé/"none"/"disabled"/"off"
        disable_sockets = os.getenv("DISABLE_SOCKETS", "").strip() in ("1", "true", "yes")
        mq_raw = os.getenv("SOCKETIO_MESSAGE_QUEUE", "").strip()
        use_queue = (not disable_sockets) and mq_raw and mq_raw.lower() not in ("none", "disabled", "off", "0")

        # Mode async : eventlet si dispo (tu utilises déjà le worker eventlet), sinon threading
        async_mode = os.getenv("SOCKETIO_ASYNC_MODE", "eventlet")

        socketio.init_app(
            app,
            cors_allowed_origins="*",
            async_mode=async_mode,
            message_queue=(mq_raw if use_queue else None),  # <- pas de Redis par défaut
        )
    else:
        socketio = None  # sécurité si le paquet n'est pas installé

    # ---------- enregistrement des blueprints ----------
    # NOTE : on importe ici pour éviter toute boucle d'import
    from .events.views import bp_events, bp_public  # tes endpoints events + public
    app.register_blueprint(bp_events)
    app.register_blueprint(bp_public)

    # Si tu as d'autres blueprints (auth, ui, etc.), garde-les :
    try:
        from .auth.views import bp as bp_auth  # facultatif si présent chez toi
        app.register_blueprint(bp_auth)
    except Exception:
        pass

    try:
        from .verify.views import bp as bp_verify  # facultatif si présent chez toi
        app.register_blueprint(bp_verify)
    except Exception:
        pass

    return app


# Optionnel : support d'une app globale si ton Procfile/Gunicorn l'exige
# (Si tu lances gunicorn "app:app", ceci garantit que 'app' existe)
if os.getenv("CREATE_GLOBAL_FLASK_APP", "1") == "1":
    app = create_app()
