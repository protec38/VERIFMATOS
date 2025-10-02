# wsgi.py — point d'entrée WSGI pour gunicorn
from app import create_app

# L'objet 'app' est importé par gunicorn (cmd dans Dockerfile)
app = create_app()
