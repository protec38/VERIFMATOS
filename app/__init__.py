import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from dotenv import load_dotenv

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()

def create_app():
    load_dotenv()
    app = Flask(__name__, static_folder='static', template_folder='templates')
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'change-this-secret')

    db_url = os.getenv('DATABASE_URL', 'sqlite:///pc38.db')
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'

    from .models import User, ensure_default_admin  # noqa
    from .auth import auth_bp  # noqa
    from .inventory import inventory_bp  # noqa
    from .events import events_bp  # noqa

    app.register_blueprint(auth_bp)
    app.register_blueprint(inventory_bp, url_prefix='/inventory')
    app.register_blueprint(events_bp, url_prefix='/events')

    @app.cli.command("init-admin")
    def init_admin():
        ensure_default_admin()

    @app.route('/')
    def index():
        from flask import render_template, redirect, url_for
        from flask_login import current_user
        if current_user.is_authenticated:
            return render_template('dashboard.html')
        return redirect(url_for('auth.login'))

    with app.app_context():
        db.create_all()
        ensure_default_admin()

    return app
