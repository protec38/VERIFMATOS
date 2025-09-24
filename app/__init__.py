import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_socketio import SocketIO
import redis

# Extensions
db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
socketio = SocketIO(message_queue="redis://redis:6379", cors_allowed_origins="*")

# Redis client (pour cache / pubsub si besoin)
redis_client = redis.Redis(host="redis", port=6379, decode_responses=True)


def create_app():
    app = Flask(
        __name__,
        static_folder="static",   # ton dossier CSS
        template_folder="templates"
    )

    # Configuration
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev_secret_key")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL", "postgresql://postgres:postgres@db:5432/postgres"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Init extensions
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    socketio.init_app(app, message_queue="redis://redis:6379", cors_allowed_origins="*")

    # Import modèles pour éviter les erreurs circulaires
    from app.models import User

    # Définir la fonction user_loader pour Flask-Login
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Création auto d’un compte admin au premier démarrage
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(email="admin@local").first():
            admin = User(email="admin@local", username="admin", is_admin=True)
            admin.set_password("admin")
            db.session.add(admin)
            db.session.commit()
            print("✅ Compte admin créé: admin@local / admin")

    # Blueprints
    from .blueprints.core import core_bp
    from .blueprints.auth import auth_bp
    from .blueprints.events import events_bp
    from .blueprints.inventory import inventory_bp

    app.register_blueprint(core_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(events_bp, url_prefix="/events")
    app.register_blueprint(inventory_bp, url_prefix="/inventory")

    # Page par défaut (redirige vers /auth/login si pas connecté)
    login_manager.login_view = "auth.login"

    return app
