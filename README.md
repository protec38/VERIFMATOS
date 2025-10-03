# PC Préparation Matériel

Application Flask pour préparer, vérifier et tracer le matériel opérationnel de la Protection Civile. L'application gère un stock hiérarchique (≤5 niveaux), suit les vérifications en temps réel, génère des exports CSV/PDF et expose une interface publique PWA pour les secouristes sur le terrain.【F:web/app/models.py†L52-L120】【F:web/app/events/views.py†L14-L61】【F:web/app/pwa/views.py†L1-L46】

## Sommaire
1. [Fonctionnalités principales](#fonctionnalités-principales)
2. [Rôles et droits](#rôles-et-droits)
3. [Architecture technique](#architecture-technique)
4. [Démarrage rapide (Docker Compose)](#démarrage-rapide-docker-compose)
5. [Développement local sans Docker](#développement-local-sans-docker)
6. [Commandes CLI utiles](#commandes-cli-utiles)
7. [Interfaces & URLs](#interfaces--urls)
8. [API JSON](#api-json)
9. [Configuration](#configuration)
10. [Sécurité & RGPD](#sécurité--rgpd)
11. [Déploiement derrière un proxy](#déploiement-derrière-un-proxy)

## Fonctionnalités principales

### Gestion du stock
- Arbre de stock illimité en largeur et limité à 5 niveaux de profondeur, avec distinction **GROUP**/**ITEM**, quantité cible, et notion d'objets uniques (ex. lots complets).【F:web/app/models.py†L74-L118】
- Gestion des dates de péremption multiples par article (lot, quantité, note) avec recalcul automatique de la prochaine date et synchronisation du champ hérité `expiry_date`.【F:web/app/models.py†L120-L157】【F:web/app/stock/views.py†L1-L122】
- Outils CRUD complets (création, édition, duplication de sous-arbre, suppression) exposés via `/stock/*` et protection de la table des péremptions si la migration n'a pas encore été appliquée.【F:web/app/stock/views.py†L94-L196】

### Préparation d'événements
- Création d'événements (nom, date, sélection de racines) avec statut **OPEN/CLOSED** et association de parents racines via la table de jonction `event_stock`.【F:web/app/models.py†L29-L71】【F:web/app/views_html.py†L47-L119】
- Liens de partage publics jetables pour les secouristes, possibilité de clôture d'événement et export des rapports CSV/PDF.【F:web/app/events/views.py†L26-L83】【F:web/app/reports/views.py†L1-L69】
- Mise à jour en temps réel des vérifications via Socket.IO (namespace `/events`) et recalcul des arbres de progression pour le tableau de bord et les pages publiques.【F:web/app/__init__.py†L18-L87】【F:web/app/events/views.py†L62-L117】

### Vérification & traçabilité
- Historique complet des vérifications avec statut (`TODO/OK/NOT_OK`), motif, quantités observées/manquantes et horodatage, pour les événements et pour la vérification périodique.【F:web/app/models.py†L159-L225】【F:web/app/verification_periodique/views.py†L1-L136】
- Module de **vérification périodique** : enregistrement des passages, rapprochement avec le stock tampon de réassort, synchronisation des dates de péremption et statistiques de progression par sac/véhicule.【F:web/app/verification_periodique/views.py†L1-L228】
- Gestion d'un stock de **réassort** (batches avec lot, péremption, quantité) pour anticiper les remplacements lors des vérifications périodiques.【F:web/app/models.py†L122-L157】

### Statistiques & exports
- Exports CSV & PDF des événements avec récapitulatif et arborescence détaillée (ReportLab). Retour JSON détaillé si le moteur PDF est absent.【F:web/app/reports/views.py†L1-L69】
- Endpoints `/stats` pour suivre la progression, les dernières vérifications et les dates de péremption agrégées (fenêtres J+30 / J+60 / expiré).【F:web/app/stats/views.py†L1-L115】
- Page **périmations** dédiée (`/peremption`) listant les lots arrivant à échéance, en fusionnant les données multi-lots et héritées.【F:web/app/peremption/views.py†L1-L124】

### Interface web & PWA
- Tableau de bord HTML sécurisé (Flask + Jinja) pour gérer événements, templates et stock, avec redirection `/ → /dashboard` et page de connexion minimaliste.【F:web/app/views_html.py†L1-L120】
- Interface publique `/public/event/<token>` pour les secouristes : saisie du binôme, cases à cocher en live et historique partagé avec l'équipe via WebSocket.【F:web/app/events/views.py†L24-L61】
- Application web progressive : manifest, service worker cache-first et icône personnalisable (`static/pc_logo.webp`).【F:web/app/pwa/views.py†L1-L46】

## Rôles et droits

| Rôle | Droits principaux |
|------|-------------------|
| `ADMIN` | Gestion complète (utilisateurs, stock, événements, réassort, exports). |
| `CHEF` | Gestion des événements et du stock, vérification périodique. |
| `VIEWER` | Lecture seule sur le stock, les événements, les rapports et les statistiques. |
| `VERIFICATIONPERIODIQUE` | Accès dédié aux modules de vérification périodique et de consultation (sans modification du stock). |

Les contrôles d'accès sont partagés entre les blueprints API et HTML afin d'assurer un comportement cohérent sur l'ensemble des interfaces.【F:web/app/models.py†L11-L47】【F:web/app/views_html.py†L21-L78】【F:web/app/verification_periodique/views.py†L18-L44】

## Architecture technique
- **Framework** : Flask 3 + SQLAlchemy + Flask-Migrate pour la persistance, Flask-Login pour l'authentification et Flask-SocketIO (eventlet) pour le temps réel.【F:web/app/__init__.py†L1-L87】
- **Base de données** : PostgreSQL 16 (via SQLAlchemy). Les migrations sont gérées par Alembic et déclenchées automatiquement au démarrage du conteneur web.【F:docker-compose.yml†L1-L33】【F:web/entrypoint.sh†L1-L67】
- **Backend** : Gunicorn (1 worker eventlet) expose l'application WSGI (`wsgi.py`) sur le port 8000 du conteneur.【F:web/Dockerfile†L1-L24】【F:web/wsgi.py†L1-L5】
- **Front** : Templates Jinja, assets statiques (`web/static`), service worker personnalisé.
- **Exports** : pandas + ReportLab pour le CSV/PDF.
- **Sécurité applicative** : limitation de débit sur la connexion, en-têtes HTTP renforcés et CSP configurable via variables d'environnement.【F:web/app/security.py†L1-L102】【F:web/app/config.py†L1-L42】

## Démarrage rapide (Docker Compose)
1. **Configurer les secrets** (facultatif mais recommandé) :
   ```bash
   export SECRET_KEY="<chaine-secrète>"
   export ADMIN_USERNAME="mon-admin"
   export ADMIN_PASSWORD="motdepasse-solide"
   ```
   Ces variables seront consommées par l'entrypoint pour créer l'administrateur initial si nécessaire.【F:web/entrypoint.sh†L68-L97】
2. **Lancer l'infrastructure** :
   ```bash
   docker compose up -d --build
   ```
   - Service web exposé sur `http://localhost:7000/` (reverse proxy possible).
   - PostgreSQL est provisionné avec un volume `pgdata` persistant.【F:docker-compose.yml†L1-L33】
3. **Vérifier l'état** :
   ```bash
   docker compose logs -f web
   ```
   L'entrypoint attend la base, initialise/upgrade les migrations Alembic puis (re)crée l'administrateur si besoin avant de démarrer Gunicorn.【F:web/entrypoint.sh†L1-L97】
4. **Connexion initiale** : se rendre sur `http://localhost:7000/` → redirection `/dashboard`, utiliser les identifiants admin définis (par défaut `admin/admin`).【F:web/app/__init__.py†L93-L115】【F:web/entrypoint.sh†L68-L97】

### Mises à jour / migrations
- Lors d'un `docker compose pull` ou `build`, l'entrypoint rejoue `flask db upgrade` si la table `alembic_version` est présente. En cas d'échec (schéma divergent), un warning est loggé mais l'application démarre pour faciliter le diagnostic.【F:web/entrypoint.sh†L25-L67】

## Développement local sans Docker
1. Créer un environnement virtuel Python 3.11 :
   ```bash
   cd web
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
   【F:web/requirements.txt†L1-L19】
2. Démarrer une base PostgreSQL (locale ou via Docker) et positionner `DATABASE_URL` vers celle-ci (ex. `postgresql+psycopg2://pcprep:pcprep@localhost:5432/pcprep`).【F:web/app/config.py†L1-L24】
3. Initialiser la base :
   ```bash
   flask --app wsgi db init      # première fois
   flask --app wsgi db migrate -m "init schema"
   flask --app wsgi db upgrade
   ```
4. Créer un compte administrateur :
   ```bash
   flask --app manage seed-admin
   ```
   (le module `manage.py` enregistre la commande CLI dans l'application).【F:web/manage.py†L1-L25】
5. Lancer le serveur de développement :
   ```bash
   FLASK_ENV=development flask --app wsgi run --debug
   ```
   Le mode développement désactive l'obligation HTTPS sur les cookies pour faciliter les tests locaux.【F:web/app/config.py†L29-L41】

## Commandes CLI utiles
- `flask --app manage seed-admin` : crée `admin/admin` si absent.【F:web/manage.py†L8-L25】
- `flask --app manage info` : affiche le nombre d'utilisateurs, d'événements et de nœuds de stock.【F:web/manage.py†L1-L25】
- `flask --app wsgi db [init|migrate|upgrade|downgrade]` : gestion des migrations Alembic.【F:web/entrypoint.sh†L25-L67】
- `flask --app wsgi shell` puis `from app.seeds_templates import seed_template_ps; seed_template_ps()` : installe le modèle de sac "MODELE SAC PS" si besoin.【F:web/app/seeds_templates.py†L1-L38】

## Interfaces & URLs
- `/dashboard` : tableau de bord, création d'événements, accès aux templates et aux racines de stock.【F:web/app/views_html.py†L47-L120】
- `/events/<id>` : suivi d'un événement, génération de lien public, fermeture, exports.【F:web/app/views_html.py†L120-L214】
- `/public/event/<token>` : interface secouriste (sans compte) en temps réel.【F:web/app/events/views.py†L24-L61】
- `/peremption` : suivi des péremptions (agrégation lots + colonnes héritées).【F:web/app/peremption/views.py†L18-L105】
- `/verification-periodique/*` : API pour les tournées périodiques (statuts, issues, réassort).【F:web/app/verification_periodique/views.py†L1-L228】
- `/healthz` : endpoint de supervision (retour JSON healthy/degraded selon la base).【F:web/app/__init__.py†L97-L117】

## API JSON
Les endpoints principaux (tous protégés par session sauf liens publics) :
- Authentification : `POST /login`, `POST /logout`, `GET /me` (Flask-Login).
- Utilisateurs admin : `GET/POST/PATCH /admin/users`, `POST /admin/users/<id>/reset_password`.
- Événements : `POST /events`, `PATCH /events/<id>/status`, `POST /events/<id>/share-link`, `GET /events/<id>/tree`, `GET /events/<id>/stats`, `GET /events/<id>/latest`.
- Liens publics : `GET /public/<token>`, `POST /public/<token>/verify`.
- Stock : `GET /stock/roots`, `GET /stock/<id>/tree`, `POST /stock`, `PATCH /stock/<id>`, `DELETE /stock/<id>`, `POST /stock/<id>/duplicate`.
- Vérifications : `POST /events/<id>/verify`, `POST /events/<id>/parent-status`, `POST /verification-periodique/<...>`.
- Rapports : `GET /reports/event/<id>/pdf` (PDF), `/events/<id>/report.csv` & `/events/<id>/report.pdf` via blueprint.

Consultez les blueprints correspondants dans `web/app/` pour les paramètres précis et les structures de réponse (JSON).【F:web/app/events/views.py†L1-L200】【F:web/app/stock/views.py†L1-L196】【F:web/app/verification_periodique/views.py†L1-L228】

## Configuration
Principales variables d'environnement supportées :

| Variable | Description | Valeur par défaut |
|----------|-------------|-------------------|
| `SECRET_KEY` | Clé Flask (sessions, CSRF). | `change-me` | 
| `DATABASE_URL` | URL SQLAlchemy/Postgres. | `postgresql+psycopg2://pcprep:pcprep@db:5432/pcprep` |
| `REDIS_URL` | File de messages Socket.IO (non utilisée par défaut). | `redis://redis:6379/0` |
| `FLASK_ENV` | `production` / `development` / `testing`. | `production` |
| `LOGIN_RATE_LIMIT_*` | Paramètres du rate limiter (tentatives, fenêtre, blocage). | `5 / 60s / 300s` |
| `CONTENT_SECURITY_POLICY` | CSP personnalisée (concaténée en une ligne). | Directives par défaut (self + CDN Socket.IO). |
| `STRICT_TRANSPORT_SECURITY` | Header HSTS (activé en HTTPS). | `max-age=31536000; includeSubDomains` |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | Identifiants seedés automatiquement au démarrage si l'utilisateur n'existe pas. | `admin` / `admin` |
| `GUNICORN_*` | Options worker/bind/app sur l'entrypoint. | cf. Dockerfile | 

Référez-vous à `web/app/config.py`, `docker-compose.yml` et `web/entrypoint.sh` pour l'ensemble des paramètres supportés.【F:web/app/config.py†L1-L42】【F:docker-compose.yml†L1-L33】【F:web/entrypoint.sh†L1-L97】

## Sécurité & RGPD
- Limitateur de tentatives de connexion (bloque 5 échecs / 5 minutes) avec en-tête `Retry-After` optionnel.【F:web/app/security.py†L1-L102】
- En-têtes de sécurité appliqués globalement : `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, CSP, HSTS en HTTPS.【F:web/app/security.py†L59-L102】
- Les noms/prénoms saisis lors des vérifications publiques sont stockés dans `VerificationRecord`. Purgez-les si nécessaire via un script SQL dédié.【F:web/app/models.py†L159-L201】
- Les liens publics deviennent non modifiables une fois l'événement `CLOSED` (statut géré côté API).【F:web/app/events/views.py†L117-L200】
- Changez le mot de passe administrateur par défaut immédiatement et utilisez HTTPS en production.

## Déploiement derrière un proxy
- Le service web écoute sur `0.0.0.0:8000` dans le conteneur, exposé sur le port `7000` par défaut. Placez Nginx/Traefik en frontal et activez l'upgrade WebSocket (`Connection: Upgrade`).【F:docker-compose.yml†L1-L24】【F:web/Dockerfile†L1-L24】
- Gérez TLS via le proxy (Let’s Encrypt, etc.) et assurez-vous de propager `X-Forwarded-For` pour le limiteur de connexion.【F:web/app/security.py†L1-L58】
- Configurez les en-têtes CSP/HSTS personnalisés via les variables d'environnement si nécessaire.【F:web/app/config.py†L15-L42】

---

Pour toute modification fonctionnelle, pensez à exécuter `flask --app wsgi db migrate` puis `flask --app wsgi db upgrade` et à documenter les nouveaux endpoints dans cette page.
