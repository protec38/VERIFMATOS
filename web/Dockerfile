# Dockerfile — build context expected: ./web
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install requirements first for better layer caching
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy application (everything from ./web)
COPY . /app

# Add entrypoint
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000
ENV GUNICORN_WORKERS=1 \
    GUNICORN_BIND=0.0.0.0:8000 \
    GUNICORN_APP=wsgi:app \
    DB_WAIT_TIMEOUT=90

ENTRYPOINT ["/app/entrypoint.sh"]
