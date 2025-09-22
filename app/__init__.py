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
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "pc38-secret")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///app.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    login_manager.init_app(app)

    from .models import User, ROLE_ADMIN

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return User.query.get(int(user_id))
        except Exception:
            return None

    from .auth import auth_bp
    from .events import events_bp
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(events_bp, url_prefix="/events")

    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("events.list_events"))
        return redirect(url_for("auth.login"))

    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username="admin").first():
            from werkzeug.security import generate_password_hash
            admin = User(username="admin", password_hash=generate_password_hash("admin"), role=ROLE_ADMIN)
            db.session.add(admin)
            db.session.commit()
    return app
