from __future__ import annotations

import os
from datetime import timedelta

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_socketio import SocketIO
from sqlalchemy import text

# Instances globales (importées ailleurs via: from . import db, login_manager, socketio)
db = SQLAlchemy()
login_manager = LoginManager()
socketio = SocketIO(async_mode="eventlet", cors_allowed_origins="*")  # sans Redis

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
    from .models import User  # import ici pour éviter cycles

    @login_manager.user_loader
    def load_user(user_id: str):
        if not user_id:
            return None
        return db.session.get(User, int(user_id))

    login_manager.login_view = "pages.login"

    # ----------------- Auto-réparation schéma users -----------------
    # Ajoute 'active' (BOOL) et 'created_at' si absents (idempotent, safe en prod)
    with app.app_context():
        try:
            db.session.execute(
                text(
                    "ALTER TABLE IF EXISTS users "
                    "ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE"
                )
            )
            db.session.execute(
                text(
                    "ALTER TABLE IF EXISTS users "
                    "ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
                )
            )
            db.session.commit()
        except Exception:
            db.session.rollback()

    # ----------------- Blueprints -----------------
    # (ordre important si des endpoints se référencent)
    from .stock.views import bp as stock_api_bp
    from .events.views import bp as events_api_bp
    from .verify.views import bp as verify_api_bp
    from .views_html import bp as pages_bp
    # Optionnels si présents dans ton code:
    try:
        from .reports.views import bp as reports_api_bp
        app.register_blueprint(reports_api_bp)
    except Exception:
        # pas bloquant si module absent
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
                # .is_active setter existe, mais inutile de passer explicitement
                db.session.add(admin)
                db.session.commit()
                print("Admin created: admin/admin")
            else:
                print("Admin already exists: admin")
        except Exception as e:
            db.session.rollback()
            print("Seeding admin failed:", e)

    return app
