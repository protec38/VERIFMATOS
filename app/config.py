
import os

class BaseConfig:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev_secret_change_me")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "sqlite:///local.db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    WTF_CSRF_TIME_LIMIT = None  # long-lived sessions
    SOCKETIO_MESSAGE_QUEUE = os.getenv("SOCKETIO_MESSAGE_QUEUE")  # e.g. redis://redis:6379/0

class ProdConfig(BaseConfig):
    SESSION_COOKIE_SECURE = True
    PREFERRED_URL_SCHEME = "https"

class DevConfig(BaseConfig):
    DEBUG = True
    SESSION_COOKIE_SECURE = False
    PREFERRED_URL_SCHEME = "http"
