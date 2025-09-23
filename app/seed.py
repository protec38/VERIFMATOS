
# Seed utilities (will be wired after models are added in Cat. 3)
from werkzeug.security import generate_password_hash

def ensure_admin(email: str = "admin@example.com", password: str = "admin"):
    """Call this after models are available and the app context is set.
    Example:
        >>> from app import create_app
        >>> app = create_app()
        >>> with app.app_context():
        ...     from app.models import User  # will exist after Cat. 3
        ...     ensure_admin()
    """
    try:
        from app.extensions import db
        from app.models import User  # type: ignore
    except Exception as e:
        print("Models not available yet. Run this after Category 3.")
        return

    user = User.query.filter_by(email=email).first()
    if user:
        print("Admin already exists:", email)
        return

    user = User(
        email=email,
        password_hash=generate_password_hash(password),
        display_name="Admin",
        role="admin",
        is_active=True
    )
    db.session.add(user)
    db.session.commit()
    print("Created admin:", email)
