import os
from flask import Flask
from .extensions import db, login_manager, csrf, socketio

def create_app():
    app = Flask(__name__)

    # ---------- Config ----------
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://postgres:postgres@db:5432/appdb",
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # ---------- Init extensions ----------
    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)

    # Flask-Login
    login_manager.login_view = "auth.login"

    from .models import User  # noqa

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # SocketIO doit être initialisé APRÈS la config
    # (l'instance est créée dans extensions.py)
    socketio.init_app(app)

    # ---------- Blueprints ----------
    from .blueprints.auth.routes import bp as auth_bp
    from .blueprints.events.routes import bp as events_bp
    from .blueprints.core.routes import bp as core_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(events_bp, url_prefix="/events")
    app.register_blueprint(core_bp)

    return app
