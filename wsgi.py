
from app import create_app

# Gunicorn entrypoint: gunicorn 'wsgi:create_app()' --bind 0.0.0.0:8000
def create_app():
    return _create()

def _create():
    # Keep a separate function name so unit tests can import it without executing gunicorn-specific code.
    from app import create_app as factory
    return factory()
