# PC Isère — Inventaire (single-folder, one Dockerfile)

- **Un seul Dockerfile** à la racine (build React + FastAPI).
- FastAPI sert `/api` + frontend statique sur **port 7000**.

## Démarrage
```bash
docker compose up --build
```
- http://localhost:7000
- Admin par défaut : `admin@pcisere.fr` / `admin`

## Structure
- `app/` — code FastAPI
- `frontend/` — code React (buildé dans l'image via Dockerfile unique)
- `requirements.txt` — dépendances Python
- `Dockerfile` — unique, multi-stage
- `docker-compose.yml` — `db` + `app`


## Fonctionnalités ajoutées (Complete)
- CRUD utilisateurs & objets (édition/suppression).
- Gestion des recettes de KIT (lecture/écriture).
- Détail/MàJ/Suppression d’événement, affectation du chef via API.
- Lien secouristes copié automatiquement depuis l’écran Chef.
