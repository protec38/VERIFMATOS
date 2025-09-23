
from flask import Flask, jsonify, render_template, redirect, url_for
from flask_login import current_user
from .extensions import db, migrate, login_manager, csrf, socketio
from .config import ProdConfig

def create_app():
    app = Flask(__name__)
    app.config.from_object(ProdConfig())

    # Init extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    socketio.init_app(app, message_queue=app.config.get("SOCKETIO_MESSAGE_QUEUE"))

    # Import models after db init
    from .models import User  # noqa

    # Flask-Login
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    login_manager.login_view = "pages.login"

    # Blueprints (API)
    from app.blueprints import register_blueprints
    register_blueprints(app)

    # UI routes (Jinja)
    from .pages import bp as pages_bp
    app.register_blueprint(pages_bp)

    # Health
    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok"), 200

    return app
