import os
from flask import Flask, render_template, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user
from dotenv import load_dotenv

db = SQLAlchemy()
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
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'

    from .models import ensure_default_admin
    from .auth import auth_bp
    from .inventory import inventory_bp
    from .events import events_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(inventory_bp, url_prefix='/inventory')
    app.register_blueprint(events_bp, url_prefix='/events')

    @app.route('/')
    def index():
        if current_user.is_authenticated:
            return render_template('dashboard.html')
        return redirect(url_for('auth.login'))

    with app.app_context():
        from . import models  # ensure tables are loaded
        db.create_all()
        ensure_default_admin()

    return app
