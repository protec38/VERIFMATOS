# ./app/wsgi.py
from app import create_app
app = create_app()  # expose un objet WSGI nommé "app"
