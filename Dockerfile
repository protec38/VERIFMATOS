FROM python:3.11-slim

# OS deps utiles
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential bash curl netcat-traditional \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Requirements
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Code + scripts
COPY . /app
# Rendez le script exécutable
RUN chmod +x /app/docker/wait-for-services.sh

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# On laisse docker-compose fournir la commande (section command:)
