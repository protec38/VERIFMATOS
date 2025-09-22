import os
from flask import Flask, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user
from dotenv import load_dotenv

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
    # Si tu es en HTTPS :
    # app.config['SESSION_COOKIE_SECURE'] = True

    # Extensions
    db.init_app(app)
    login_manager.init_app(app)

    # Blueprints
    from .auth import auth_bp
    from .events import events_bp
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(events_bp, url_prefix="/events")

    # Route racine → redirige selon l’état de connexion
    @app.route("/")
    def index():
        # si connecté → liste des évènements
        if current_user.is_authenticated:
            return redirect(url_for("events.list_events"))
        # sinon → page de login
        return redirect(url_for("auth.login"))

    # Optionnel : route de santé
    @app.route("/healthz")
    def healthz():
        return "ok", 200

    # Création des tables
    with app.app_context():
        db.create_all()

    return app
