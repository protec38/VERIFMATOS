# app/__init__.py — FINAL
from __future__ import annotations
from datetime import datetime
from flask import Flask, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from flask_socketio import SocketIO
from .config import get_config

# Extensions globales
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
# instance par défaut; si REDIS_URL est défini on reconfigurera plus bas
socketio = SocketIO(message_queue=None, async_mode="eventlet", cors_allowed_origins="*")

def create_app() -> Flask:
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(get_config())

    # Init extensions
    db.init_app(app)
    migrate.init_app(app, db)

    login_manager.init_app(app)
    login_manager.login_view = "pages.login"

    # Importer les modèles pour migrations & user_loader
    from . import models  # noqa: F401
    from .models import User  # nécessaire pour user_loader

    # >>>>>>> IMPORTANT : user_loader pour Flask-Login <<<<<<<
    @login_manager.user_loader
    def load_user(user_id: str):
        """Recharge l'utilisateur depuis l'ID stocké en session."""
        try:
            # Flask-Login stocke des strings; on convertit prudemment
            uid = int(user_id)
        except Exception:
            return None
        try:
            return db.session.get(User, uid)
        except Exception:
            return None

    # Socket.IO (option Redis)
    redis_url = app.config.get("REDIS_URL")
    if redis_url:
        try:
            global socketio
            socketio = SocketIO(async_mode="eventlet", message_queue=redis_url, cors_allowed_origins="*")
            socketio.init_app(app)
        except Exception as e:
            app.logger.warning(f"SocketIO: Redis MQ désactivé (préflight KO: {e}). Démarrage sans MQ.")
            socketio.init_app(app)
    else:
        socketio.init_app(app)

    # Jinja globals — injecte now() ET current_user (LocalProxy)
    @app.context_processor
    def inject_globals():
        return {
            "now": datetime.utcnow,
            "current_user": current_user,
        }

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

    # Root/health
    @app.get("/")
    def index():
        return redirect(url_for("pages.dashboard"))

    @app.get("/health")
    def health():
        return {"status": "healthy"}

    # Socket handlers (optionnel)
    try:
        from .sockets import register_socketio_handlers
        register_socketio_handlers(socketio)
    except Exception:
        pass

    # CLI seeds (optionnel)
    try:
        from .seeds_templates import register_cli as register_seed_cli
        register_seed_cli(app)
    except Exception:
        pass

    return app
