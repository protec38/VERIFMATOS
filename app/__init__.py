import os
from flask import Flask, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

load_dotenv()

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login"

def create_app():
    app = Flask(__name__)

    # Config
    app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "pc38-super-secret-change-me")
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL", "sqlite:///app.db")
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config.setdefault('SESSION_COOKIE_SAMESITE', 'Lax')
    # app.config['SESSION_COOKIE_SECURE'] = True  # active en prod HTTPS

    # Extensions
    db.init_app(app)
    login_manager.init_app(app)

    # Import modèles ici pour que user_loader fonctionne
    from .models import User, ROLE_ADMIN

    # Flask-Login: fonction pour charger un user depuis son id
    @login_manager.user_loader
    def load_user(user_id: str):
        try:
            return User.query.get(int(user_id))
        except Exception:
            return None

    # Blueprints
    from .auth import auth_bp
    from .events import events_bp
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(events_bp, url_prefix="/events")

    # Route racine
    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("events.list_events"))
        return redirect(url_for("auth.login"))

    @app.route("/healthz")
    def healthz():
        return "ok", 200

    # Init DB + admin par défaut
    with app.app_context():
        db.create_all()
        # Crée un admin par défaut si absent (username=admin / password=admin)
        admin = User.query.filter_by(username="admin").first()
        if not admin:
            admin = User(
                username="admin",
                password_hash=generate_password_hash("admin"),
                role=ROLE_ADMIN
            )
            db.session.add(admin)
            db.session.commit()

    return app
