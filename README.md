# PC Isère — Inventaire & Missions (Partie racine)

Cette archive contient les fichiers **racine** du projet : `docker-compose.yml`, `Dockerfile`, `requirements.txt`, `wsgi.py`, `.env.example`, `.dockerignore`.

> ⚠️ Le dossier `app/` (code Python) sera fourni dans les parties suivantes.

## Démarrage

1. Duplique `.env.example` en `.env` et adapte si besoin :
   ```bash
   cp .env.example .env
   ```

2. Construis et démarre :
   ```bash
   docker compose up --build
   ```

3. Accède à l'app :
   - http://localhost:8000 (redirige vers /auth/login une fois l'app fournie)
   - Admin par défaut : **admin / admin** (créé à l'init, dans la partie backend).

## Notes

- `DATABASE_URL` dans `.env` est déjà configurée pour pointer vers le service `db` du `docker-compose`.
- Le `Dockerfile` utilise Gunicorn en production.
- `wsgi.py` est le point d'entrée (Gunicorn lit `wsgi:app`).

Une fois que tu auras ajouté le dossier `app/` (parties suivantes), redémarre les conteneurs.
