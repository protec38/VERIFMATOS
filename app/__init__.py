import os
from flask import Flask
from flask_login import current_user
from werkzeug.security import generate_password_hash

from .extensions import db, socketio, login_manager
from .models import User, Role


def create_app():
    app = Flask(__name__)

    # --------------------
    # Configuration
    # --------------------
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev_secret_key")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@db:5432/postgres",
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["REDIS_URL"] = os.getenv("REDIS_URL", "redis://redis:6379/0")

    # --------------------
    # Initialiser extensions
    # --------------------
    db.init_app(app)
    socketio.init_app(app, cors_allowed_origins="*")
    login_manager.init_app(app)

    # === Flask-Login: user_loader obligatoire ===
    @login_manager.user_loader
    def load_user(user_id: str):
        try:
            return User.query.get(int(user_id))
        except Exception:
            return None

    # (optionnel) rendre current_user dispo partout dans Jinja
    @app.context_processor
    def inject_current_user():
        return {"current_user": current_user}

    # --------------------
    # Enregistrer les blueprints
    # --------------------
    from .blueprints.core.routes import bp as core_bp
    from .blueprints.auth.routes import bp as auth_bp
    from .blueprints.events.routes import bp as events_bp
    # from .blueprints.inventory.routes import bp as inventory_bp  # si/qd présent

    app.register_blueprint(core_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(events_bp, url_prefix="/events")
    # app.register_blueprint(inventory_bp, url_prefix="/inventory")

    # --------------------
    # Création auto du compte admin au démarrage (une seule fois)
    # --------------------
    with app.app_context():
        db.create_all()

        if not User.query.filter_by(email="admin@local").first():
            admin_user = User(
                email="admin@local",
                password_hash=generate_password_hash("admin"),
                display_name="Administrateur",
                role=Role.ADMIN,
                is_active=True,
            )
            db.session.add(admin_user)
            db.session.commit()
            print("✅ Compte admin créé: admin@local / admin")

    return app
