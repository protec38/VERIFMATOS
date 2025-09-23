import os
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_socketio import SocketIO
from flask_login import LoginManager

# Instances d’extensions (sans lier à l’app ici)
db = SQLAlchemy()
migrate = Migrate()
socketio = SocketIO(cors_allowed_origins="*")  # message_queue injectée à l’init
login_manager = LoginManager()
login_manager.login_view = "auth.login"


def init_extensions(app):
    """Initialise toutes les extensions sur l'application Flask."""
    db.init_app(app)
    migrate.init_app(app, db)

    # Active le backend Redis pour Socket.IO si configuré
    socketio.init_app(
        app,
        message_queue=app.config.get("SOCKETIO_MESSAGE_QUEUE"),
        async_mode="eventlet",
    )

    login_manager.init_app(app)
