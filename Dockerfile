FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

# Installer dépendances système utiles
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev && rm -rf /var/lib/apt/lists/*

# Installer les dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier tout le projet
COPY . .

EXPOSE 8000

# Lancer Gunicorn
CMD ["sh", "-c", "flask db upgrade || true && python seed.py && gunicorn -w 1 -k eventlet -b 0.0.0.0:8000 wsgi:app"]
