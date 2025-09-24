import os
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from flask_login import LoginManager

# DB
db = SQLAlchemy()

# Socket.IO (utilise Redis si dispo)
_socketio_redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
socketio = SocketIO(
    async_mode="eventlet",
    cors_allowed_origins="*",
    message_queue=_socketio_redis_url,
)

# Auth
login_manager = LoginManager()
login_manager.login_view = "auth.login"           # endpoint de ta page login
login_manager.login_message_category = "warning"
