# app/__init__.py — Socket.IO SANS Redis + user_loader Flask-Login
from __future__ import annotations
from datetime import datetime
from flask import Flask, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_socketio import SocketIO
from .config import get_config

# Extensions
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
# Pas de message_queue (pas de Redis)
socketio = SocketIO(async_mode="eventlet", cors_allowed_origins="*")

def create_app() -> Flask:
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(get_config())

    # Init extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = "pages.login"

    # Import models pour migrations / user_loader
    from . import models  # noqa: F401
    from .models import User  # pour le loader

    # ---- Flask-Login: user_loader OBLIGATOIRE ----
    @login_manager.user_loader
    def load_user(user_id: str):
      try:
          # Flask 3.x / SQLAlchemy 2.x : db.session.get(Model, pk)
          return db.session.get(User, int(user_id))
      except Exception:
          return None

    # Socket.IO : SANS Redis (inter-process MQ désactivée)
    socketio.init_app(app, message_queue=None)

    # Jinja globals (now())
    @app.context_processor
    def inject_now():
        return {"now": datetime.utcnow}

    # Blueprints API
    from .auth.views import bp as auth_api_bp
    app.register_blueprint(auth_api_bp)
    from .admin.views import bp as admin_api_bp
    app.register_blueprint(admin_api_bp)
    from .events.views import bp as events_api_bp
    app.register_blueprint(events_api_bp)
    from .stock.views import bp as stock_api_bp
    app.register_blueprint(stock_api_bp)
    from .verify.views import bp as verify_api_bp
    app.register_blueprint(verify_api_bp)
    from .reports.views import bp as reports_api_bp
    app.register_blueprint(reports_api_bp)
    from .stats.views import bp as stats_api_bp
    app.register_blueprint(stats_api_bp)
    from .pwa.views import bp as pwa_bp
    app.register_blueprint(pwa_bp)

    # Pages HTML
    from .views_html import bp as pages_bp
    app.register_blueprint(pages_bp)

    # Health / root
    @app.get("/")
    def index():
        return redirect(url_for("pages.dashboard"))

    @app.get("/health")
    def health():
        return {"status": "healthy"}

    # Socket handlers
    from .sockets import register_socketio_handlers
    register_socketio_handlers(socketio)

    # CLI seed (optionnel)
    try:
        from .seeds_templates import register_cli as register_seed_cli
        register_seed_cli(app)
    except Exception:
        pass

    return app
