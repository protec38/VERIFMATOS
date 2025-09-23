from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from flask_socketio import SocketIO

# Instances d'extensions (créées une seule fois ici)
db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()

# SocketIO : eventlet en prod avec Gunicorn (-k eventlet)
# Si tu as Redis dans docker-compose, on active la MQ pour le multi-process
socketio = SocketIO(
    cors_allowed_origins="*",
    async_mode="eventlet",
    message_queue="redis://redis:6379/0",
    manage_session=False,
)
