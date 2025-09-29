from __future__ import annotations

import os
from datetime import timedelta, datetime, timezone

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_socketio import SocketIO
from sqlalchemy import text

# Instances globales (importées ailleurs via: from . import db, login_manager, socketio)
db = SQLAlchemy()
login_manager = LoginManager()
socketio = SocketIO(async_mode="eventlet", cors_allowed_origins="*")  # sans Redis


def _ensure_users_schema() -> None:
    """
    Auto-réparation idempotente de la table users pour éviter les erreurs
    de NOT NULL sur created_at et garantir les defaults.
    """
    try:
        # Ajouter les colonnes si absentes
        db.session.execute(text(
            "ALTER TABLE IF EXISTS users "
            "ADD COLUMN IF NOT EXISTS active BOOLEAN"
        ))
        db.session.execute(text(
            "ALTER TABLE IF EXISTS users "
            "ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ"
        ))

        # Définir / forcer les DEFAULT
        db.session.execute(text(
            "ALTER TABLE IF EXISTS users "
            "ALTER COLUMN active SET DEFAULT TRUE"
        ))
        db.session.execute(text(
            "ALTER TABLE IF EXISTS users "
            "ALTER COLUMN created_at SET DEFAULT NOW()"
        ))

        # Renseigner les valeurs NULL existantes
        db.session.execute(text(
            "UPDATE users SET active = TRUE WHERE active IS NULL"
        ))
        db.session.execute(text(
            "UPDATE users SET created_at = NOW() WHERE created_at IS NULL"
        ))

        # Reposer NOT NULL proprement
        db.session.execute(text(
            "ALTER TABLE IF EXISTS users "
            "ALTER COLUMN active SET NOT NULL"
        ))
        db.session.execute(text(
            "ALTER TABLE IF EXISTS users "
            "ALTER COLUMN created_at SET NOT NULL"
        ))

        db.session.commit()
    except Exception:
        db.session.rollback()
        # on ne bloque pas le boot si la réparation échoue ; les logs Docker montreront l'erreur


# -----------------------------------------------------------------------------
# Factory
# -----------------------------------------------------------------------------
def create_app() -> Flask:
    app = Flask(__name__)

    # ----------------- Config -----------------
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-me")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg2://pcprep:pcprep@db:5432/pcprep",
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["REMEMBER_COOKIE_DURATION"] = timedelta(days=14)

    # ----------------- Init libs -----------------
    db.init_app(app)
    login_manager.init_app(app)
    socketio.init_app(app)

    # ----------------- User loader (Flask-Login) -----------------
    from .models import User  # import local pour éviter cycles

    @login_manager.user_loader
    def load_user(user_id: str):
        if not user_id:
            return None
        return db.session.get(User, int(user_id))

    login_manager.login_view = "pages.login"

    # ----------------- Auto-réparation schéma users -----------------
    with app.app_context():
        _ensure_users_schema()

    # ----------------- Blueprints -----------------
    from .stock.views import bp as stock_api_bp
    from .events.views import bp as events_api_bp
    from .verify.views import bp as verify_api_bp
    from .views_html import bp as pages_bp

    # Optionnels si présents
    try:
        from .reports.views import bp as reports_api_bp
        app.register_blueprint(reports_api_bp)
    except Exception:
        pass
    try:
        from .stats.views import bp as stats_api_bp
        app.register_blueprint(stats_api_bp)
    except Exception:
        pass

    app.register_blueprint(stock_api_bp)   # routes /stock...
    app.register_blueprint(events_api_bp)  # routes /events...
    app.register_blueprint(verify_api_bp)  # routes /public/event...
    app.register_blueprint(pages_bp)       # pages HTML (/dashboard, /admin, ...)

    # ----------------- Seeding admin (idempotent) -----------------
    with app.app_context():
        try:
            from .models import Role

            admin = User.query.filter_by(username="admin").first()
            if not admin:
                admin = User(username="admin", role=Role.ADMIN)
                admin.set_password("admin")
                # évite de dépendre du DEFAULT si le SGBD est tatillon
                admin.created_at = datetime.now(timezone.utc)
                admin.is_active = True
                db.session.add(admin)
                db.session.commit()
                print("Admin created: admin/admin")
            else:
                print("Admin already exists: admin")
        except Exception as e:
            db.session.rollback()
            print("Seeding admin failed:", e)

    return app
