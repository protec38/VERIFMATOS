import os
import secrets
from datetime import datetime
from flask import Flask
from .extensions import db, migrate, socketio, login_manager, init_extensions

DEFAULT_SECRET = "change-me-in-prod"

def create_app() -> Flask:
    app = Flask(__name__, instance_relative_config=False)

    # ---- Config de base ----
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", DEFAULT_SECRET)

    # Database (Postgres via DATABASE_URL)
    db_url = os.environ.get("DATABASE_URL", "sqlite:///app.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Redis pour Socket.IO / tâches
    app.config["REDIS_URL"] = os.environ.get("REDIS_URL", "redis://:pc_redis_pass@redis:6379/0")
    app.config["SOCKETIO_MESSAGE_QUEUE"] = os.environ.get(
        "SOCKETIO_MESSAGE_QUEUE",
        app.config["REDIS_URL"],
    )

    # ---- Initialisation des extensions ----
    init_extensions(app)

    # ---- Blueprints ----
    from .blueprints.auth.routes import bp as auth_bp
    from .blueprints.core.routes import bp as core_bp
    from .blueprints.events.routes import bp as events_bp
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(core_bp)
    app.register_blueprint(events_bp, url_prefix="/events")

    # ---- Création des tables + seed admin (1 seule fois) ----
    with app.app_context():
        db.create_all()
        _seed_admin_once()

    return app


def _seed_admin_once():
    """Crée le compte admin une seule fois si absent."""
    from .models import User, Role
    from werkzeug.security import generate_password_hash

    want = os.environ.get("INIT_CREATE_ADMIN", "true").lower() in ("1", "true", "yes")
    if not want:
        return

    email = os.environ.get("ADMIN_EMAIL", "admin@example.com").strip().lower()
    password = os.environ.get("ADMIN_PASSWORD", "admin")
    display_name = os.environ.get("ADMIN_DISPLAY_NAME", "Administrateur")
    role = os.environ.get("ADMIN_ROLE", Role.ADMIN)

    existing = User.query.filter_by(email=email).first()
    if existing:
        return

    admin = User(
        email=email,
        password_hash=generate_password_hash(password),
        display_name=display_name,
        role=role,
        is_active=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.session.add(admin)
    db.session.commit()
