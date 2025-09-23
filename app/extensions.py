from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

db = SQLAlchemy()
login_manager = LoginManager()

# Optionnel: configuration de la vue de login (utilisée par @login_required)
login_manager.login_view = "auth.login"
login_manager.login_message_category = "warning"
