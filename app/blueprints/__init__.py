
from flask import Blueprint
from .auth.routes import bp as auth_bp
from .inventory.routes import bp as inventory_bp
from .events.routes import bp as events_bp
from .admin.routes import bp as admin_bp
from .public.routes import bp as public_bp

def register_blueprints(app):
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(inventory_bp, url_prefix='/inventory')
    app.register_blueprint(events_bp, url_prefix='/events')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(public_bp, url_prefix='/p')
