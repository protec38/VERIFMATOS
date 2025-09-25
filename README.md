# PC Préparation Matériel — Flask + Docker

Application web pour la **préparation et la vérification** de matériel (Protection Civile).
- Rôles : **ADMIN**, **CHEF**, **VIEWER** (lecture seule).
- Événements : **OPEN** / **CLOSED** ; lien **public** pour secouristes (sans compte).
- Stock hiérarchique (≤5 niveaux) : **GROUP** (parents/sous-parents) & **ITEM** (enfants avec quantité).
- Vérification en **temps réel** (WebSockets) + export **CSV/PDF** + **PWA** (mode hors-ligne léger).

## Démarrage

```bash
# 1) Décompressez *toutes* les archives lot1..lot12 dans le même dossier pour fusionner /web/
docker compose up -d --build

# 2) Base de données (migrations)
docker compose exec web flask db init      # (la 1ère fois)
docker compose exec web flask db migrate -m "init schema"
docker compose exec web flask db upgrade

# 3) Créez l'admin
docker compose exec web flask seed-admin

# (optionnel) Seed modèle "MODELE SAC PS"
docker compose exec web flask seed-template-ps
```

Accès: `http://<votre-host>:8000/` → redirection vers `/dashboard`.
- Compte initial: **admin / admin** (changez-le immédiatement).

## Utilisation rapide

- **Dashboard** `/dashboard` : créez un événement (ADMIN|CHEF), liste des événements, liens **Ouvrir / CSV / PDF**.
- **Page événement** `/events/<id>` : arbre hiérarchique, progression, **générer lien** public, **clôturer**.
- **Page publique secouristes** `/public/event/<token>` : nom & prénom + cases à cocher (live update).

## API principales (JSON)

- Auth: `POST /login`, `POST /logout`, `GET /me`
- Admin users: `GET/POST/PATCH /admin/users`, `POST /admin/users/<id>/reset_password`
- Events: `POST /events`, `PATCH /events/<id>/status`, `POST /events/<id>/share-link`, `GET /public/<token>`
- Stocks: `GET /stock/roots`, `GET /stock/<id>/tree`, `POST /stock`, `PATCH /stock/<id>`, `DELETE /stock/<id>`, `POST /stock/<id>/duplicate`
- Vérif: `POST /events/<id>/verify`, `POST /events/<id>/parent-status`, `POST /public/<token>/verify`
- Rapports: `GET /events/<id>/report.csv`, `GET /events/<id>/report.pdf`
- Stats: `GET /events/<id>/stats`, `GET /events/<id>/latest`

## Variables d’environnement

- `SECRET_KEY` (obligatoire en prod)
- `DATABASE_URL` (par défaut `postgresql+psycopg2://pcprep:pcprep@db:5432/pcprep`)
- `REDIS_URL` (par défaut `redis://redis:6379/0`)

## Sécurité / RGPD

- Les noms/prénoms saisis sont stockés dans `VerificationRecord`. Sur demande, vous pouvez purger via un script SQL.
- Les liens publics ne permettent pas de modifier si l’événement est **CLOSED**.
- Changez **immédiatement** le mot de passe admin par défaut.

## PWA

- `GET /manifest.webmanifest`
- `GET /sw.js` (service worker, cache-first de base)
- L’icône est `static/pc_logo.webp` (remplacez par votre logo si besoin).

## Déploiement derrière reverse proxy

- `web` écoute sur `:8000`. Reverse proxy (Nginx, Traefik) → proxy pass vers `http://web:8000`.
- Activez le **WebSocket** (upgrade HTTP) sur le proxy.
- TLS/HTTPS gérés par votre proxy (Let’s Encrypt, etc.).
