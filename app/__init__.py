import os
from flask import Flask, redirect, url_for, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login"

def create_app():
    app = Flask(__name__)

    # ---------- Config ----------
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret")
    # Postgres via docker-compose
    db_user = os.getenv("POSTGRES_USER", "postgres")
    db_pass = os.getenv("POSTGRES_PASSWORD", "postgres")
    db_name = os.getenv("POSTGRES_DB", "appdb")
    db_host = os.getenv("POSTGRES_HOST", "db")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"postgresql://{db_user}:{db_pass}@{db_host}:5432/{db_name}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # ---------- Init ext ----------
    db.init_app(app)
    login_manager.init_app(app)

    # ---------- Models import / create tables ----------
    from .models import User, ROLE_ADMIN  # noqa: F401

    with app.app_context():
        db.create_all()
        # bootstrap admin s’il n’existe pas
        if not User.query.filter_by(username="admin").first():
            u = User(username="admin", role=ROLE_ADMIN)
            u.set_password("admin")
            db.session.add(u)
            db.session.commit()

    # ---------- Blueprints ----------
    from .auth import auth_bp
    from .events import events_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(events_bp, url_prefix="/events")

    # ---------- Routes racine ----------
    @app.route("/")
    def index():
        # renvoyer vers la liste d’événements si connecté, sinon login
        try:
            if current_user.is_authenticated:
                return redirect(url_for("events.list_events"))
        except Exception:
            pass
        return redirect(url_for("auth.login"))

    # “healthy” simple pour wait-for
    @app.route("/healthz")
    def healthz():
        return {"ok": True}

    return app
