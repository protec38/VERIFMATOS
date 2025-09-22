import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from dotenv import load_dotenv

# ---------------------------------------------------------------------
# Chargement variables d'environnement (.env)
# ---------------------------------------------------------------------
load_dotenv()

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login"

def create_app():
    app = Flask(__name__)

    # -----------------------------------------------------------------
    # Configuration
    # -----------------------------------------------------------------
    app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "rtyhqertgrterg")

    # Exemple: postgres://user:pass@db:5432/appdb
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
        "DATABASE_URL",
        "sqlite:///app.db"  # fallback local
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Sessions plus fiables
    app.config.setdefault('SESSION_COOKIE_SAMESITE', 'Lax')
    # ⚠️ si tu déploies en HTTPS (cloud), active la ligne suivante :
    # app.config['SESSION_COOKIE_SECURE'] = True

    # -----------------------------------------------------------------
    # Extensions
    # -----------------------------------------------------------------
    db.init_app(app)
    login_manager.init_app(app)

    # -----------------------------------------------------------------
    # Blueprints
    # -----------------------------------------------------------------
    from .auth import auth_bp
    from .events import events_bp
    from .stock import stock_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(events_bp, url_prefix="/events")
    app.register_blueprint(stock_bp, url_prefix="/stock")

    # -----------------------------------------------------------------
    # Création des tables
    # -----------------------------------------------------------------
    with app.app_context():
        db.create_all()

    return app
