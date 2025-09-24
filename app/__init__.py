# app/__init__.py
import os
from flask import Flask
from flask_login import current_user
from .extensions import db, login_manager, socketio
from .blueprints.core import core_bp
from .blueprints.auth import auth_bp
from .blueprints.events import events_bp
from .blueprints.inventory import inventory_bp
from .models import User

def create_app():
    app = Flask(
        __name__,
        template_folder="templates",      # app/templates
        static_folder="static",           # app/static
        static_url_path="/static"         # URL sera /static/...
    )

    # --------------------
    # Configuration
    # --------------------
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev_secret")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "DATABASE_URL", "postgresql://postgres:postgres@db:5432/postgres"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["REDIS_URL"] = os.getenv("REDIS_URL", "redis://redis:6379/0")

    # --------------------
    # Extensions
    # --------------------
    db.init_app(app)
    login_manager.init_app(app)
    socketio.init_app(app, message_queue=app.config["REDIS_URL"])

    # --------------------
    # Blueprints
    # --------------------
    app.register_blueprint(core_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(events_bp, url_prefix="/events")
    app.register_blueprint(inventory_bp, url_prefix="/inventory")

    # --------------------
    # Flask-Login
    # --------------------
    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # --------------------
    # Création compte admin
    # --------------------
    with app.app_context():
        db.create_all()
        admin_email = "admin@local"
        if not User.query.filter_by(email=admin_email).first():
            admin = User(email=admin_email, username="admin")
            admin.set_password("admin")
            admin.is_admin = True
            db.session.add(admin)
            db.session.commit()
            print("✅ Compte admin créé: admin@local / admin")

    return app
