import os
from flask import Flask, redirect, url_for
from flask_login import LoginManager, current_user
from . import db as _db
from .models import User
from werkzeug.middleware.proxy_fix import ProxyFix

db = _db
login_manager = LoginManager()
login_manager.login_view = "events.list_events"

def create_app():
    app = Flask(__name__, static_folder="static", template_folder="templates")

    # ---- Config minimale sûre
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg2://postgres:postgres@db:5432/opscheck"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # ---- Proxies (Docker/Traefik/Render/etc.)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_host=1)

    # ---- Init extensions
    db.init_app(app)
    login_manager.init_app(app)

    # ---- Blueprints
    from .events import events_bp
    app.register_blueprint(events_bp, url_prefix="/events")

    # ---- Index
    @app.route("/")
    def index():
        # simple redirection vers la liste des évènements
        return redirect(url_for("events.list_events"))

    # ---- DB + seed
    with app.app_context():
        db.create_all()
        # créer un admin par défaut si aucun utilisateur n’existe
        if User.query.count() == 0:
            admin = User(username="admin", role="admin")
            admin.set_password("admin")
            db.session.add(admin)
            db.session.commit()

    return app
