import os
import time
from flask import Flask
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from werkzeug.security import generate_password_hash

from .extensions import db, migrate, socketio, login_manager
from .models import User, Role, Settings

def _wait_engine_connect(max_attempts=60, delay=2):
    """Attendre que la DB accepte les connexions."""
    for _ in range(max_attempts):
        try:
            with db.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except OperationalError:
            time.sleep(delay)
    raise RuntimeError("Database not reachable after retries")

def _seed_admin_once():
    """
    Crée un compte admin 1 seule fois en lisant les variables d'environnement.
    Protégé par Settings.initial_seed_done.
    """
    settings = Settings.get()  # crée la ligne si absente
    if settings.initial_seed_done:
        return

    should_create = os.getenv("INIT_CREATE_ADMIN", "true").lower() in ("1", "true", "yes", "on")
    if not should_create:
        settings.initial_seed_done = True
        db.session.add(settings)
        db.session.commit()
        return

    admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com").strip()
    admin_password = os.getenv("ADMIN_PASSWORD", "admin")
    admin_display = os.getenv("ADMIN_DISPLAY_NAME", "Administrateur").strip()
    admin_role = os.getenv("ADMIN_ROLE", Role.ADMIN).strip().lower()

    # Sanity: fallback sur Role.ADMIN si role invalide
    valid_roles = {Role.ADMIN, Role.CHEF, Role.SECOURISTE, Role.VIEWER}
    if admin_role not in valid_roles:
        admin_role = Role.ADMIN

    if not User.query.filter_by(email=admin_email).first():
        admin = User(
            email=admin_email,
            password_hash=generate_password_hash(admin_password),
            display_name=admin_display,
            role=admin_role,
            is_active=True,
        )
        db.session.add(admin)

    settings.initial_seed_done = True
    db.session.add(settings)
    db.session.commit()

def create_app():
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.getenv("SECRET_KEY", "dev-secret-key"),
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", "sqlite:////app/db.sqlite3"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SOCKETIO_MESSAGE_QUEUE=os.getenv("SOCKETIO_MESSAGE_QUEUE"),
        SESSION_COOKIE_SECURE=False,
        SESSION_COOKIE_SAMESITE="Lax",
    )

    # Extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    socketio.init_app(app, message_queue=app.config["SOCKETIO_MESSAGE_QUEUE"], async_mode="eventlet")

    # Blueprints
    from .blueprints.core.routes import bp as core_bp
    from .blueprints.auth.routes import bp as auth_bp
    from .blueprints.inventory.routes import bp as inv_bp
    from .blueprints.events.routes import bp as events_bp
    app.register_blueprint(core_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(inv_bp, url_prefix="/inventory")
    app.register_blueprint(events_bp, url_prefix="/events")

    with app.app_context():
        # Attendre la DB (utile même si compose attend déjà)
        _wait_engine_connect()
        # Créer schéma si absent
        db.create_all()
        # Semer l’admin une seule fois
        _seed_admin_once()

    return app
