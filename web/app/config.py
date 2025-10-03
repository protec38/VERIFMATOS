# app/config.py — Configurations (prod/dev/test)
import os

class BaseConfig:
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg2://pcprep:pcprep@db:5432/pcprep"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = True
    REMEMBER_COOKIE_HTTPONLY = True
    PREFERRED_URL_SCHEME = "https"
    REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    _DEFAULT_CSP_DIRECTIVES = [
        "default-src 'self'",
        "img-src 'self' data:",
        "style-src 'self' 'unsafe-inline'",
        "script-src 'self' 'unsafe-inline' https://cdn.socket.io",
        "connect-src 'self' ws: wss:",
        "font-src 'self' data:",
        "manifest-src 'self'",
        "frame-ancestors 'none'",
    ]
    CONTENT_SECURITY_POLICY = os.environ.get(
        "CONTENT_SECURITY_POLICY",
        "; ".join(_DEFAULT_CSP_DIRECTIVES),
    )
    STRICT_TRANSPORT_SECURITY = os.environ.get(
        "STRICT_TRANSPORT_SECURITY",
        "max-age=31536000; includeSubDomains"
    )
    LOGIN_RATE_LIMIT_ATTEMPTS = int(os.environ.get("LOGIN_RATE_LIMIT_ATTEMPTS", 5))
    LOGIN_RATE_LIMIT_WINDOW = int(os.environ.get("LOGIN_RATE_LIMIT_WINDOW", 60))
    LOGIN_RATE_LIMIT_BLOCK = int(os.environ.get("LOGIN_RATE_LIMIT_BLOCK", 300))

class ProductionConfig(BaseConfig):
    ENV = "production"
    DEBUG = False
    TESTING = False

class DevelopmentConfig(BaseConfig):
    ENV = "development"
    DEBUG = True
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    PREFERRED_URL_SCHEME = "http"

class TestingConfig(BaseConfig):
    ENV = "testing"
    TESTING = True
    DEBUG = True
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"

def get_config():
    env = os.environ.get("FLASK_ENV", "production").lower()
    if env == "development":
        return DevelopmentConfig
    if env == "testing":
        return TestingConfig
    return ProductionConfig
