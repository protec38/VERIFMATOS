import os
from flask import Flask
from app.extensions import db, login_manager
from app.models import User


def create_app() -> Flask:
    app = Flask(__name__)

    # -----------------------------
    # Configuration application
    # -----------------------------
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "DATABASE_URL", "postgresql://admin:admin@db:5432/secouristes"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # -----------------------------
    # Init extensions
    # -----------------------------
    db.init_app(app)
    login_manager.init_app(app)

    # Flask-Login: fonction de chargement utilisateur
    @login_manager.user_loader
    def load_user(user_id: str):
        try:
            return User.query.get(int(user_id))
        except Exception:
            return None

    # -----------------------------
    # Blueprints
    # -----------------------------
    # Assure-toi d’avoir un blueprint d’auth avec endpoint "auth.login"
    # Exemple: app/blueprints/auth/routes.py avec:
    #   bp = Blueprint("auth", __name__)
    #   @bp.route("/login", methods=["GET","POST"]) ...
    from app.blueprints.auth.routes import bp as auth_bp  # noqa: E402
    app.register_blueprint(auth_bp, url_prefix="/auth")

    # Route de test
    @app.get("/")
    def index():
        return "✅ Application Secouristes OK !"

    # -----------------------------
    # Création auto des tables
    # (tu as demandé sans migrations)
    # -----------------------------
    with app.app_context():
        db.create_all()

    return app
