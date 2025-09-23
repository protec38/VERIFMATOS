import os
from flask import Flask
from .extensions import db, login_manager, csrf, socketio
from .config import Config
from .models import Settings
from .startup import bootstrap_once

def create_app():
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config.from_object(Config())

    # init extensions
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    # socket.io with Redis message queue
    socketio.init_app(app, message_queue=app.config.get("REDIS_URL"), cors_allowed_origins="*")

    # blueprints
    from .blueprints.core.routes import bp as core_bp
    from .blueprints.auth.routes import bp as auth_bp
    from .blueprints.inventory.routes import bp as inventory_bp
    from .blueprints.events.routes import bp as events_bp
    from .blueprints.admin.routes import bp as admin_bp

    app.register_blueprint(core_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(inventory_bp, url_prefix="/inventory")
    app.register_blueprint(events_bp, url_prefix="/events")
    app.register_blueprint(admin_bp, url_prefix="/admin")

    # CLI health route
    @app.get("/health")
    def health():
        return {"ok": True}

    # DB create + bootstrap only once
    with app.app_context():
        db.create_all()
        bootstrap_once()

    return app

from . import login_loader  # noqa: F401

from . import socket_handlers  # noqa: F401
