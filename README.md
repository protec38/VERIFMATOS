# PC38 Inventaire — Flask + Docker

Application web pour gérer l'inventaire des missions de secours (Protection Civile de l'Isère).

## Fonctionnalités clés
- Comptes **admin**, **chef de poste**, **secouriste**.
- **Admin** : gestion des utilisateurs, du stock (objets parents et enfants).
- **Chef de poste** : création d'un **évènement**, sélection d'objets **parents** (ex: Sac PS), génération d'un **lien** de vérification.
- **Secouriste** (sans compte) : accès via **lien**, saisie Nom/Prénom, coche des éléments **enfants** vérifiés.
- **Mise à jour AJAX** en temps réel (polling) : le chef/admin voient qui a vérifié quoi et quand, et marquent les **objets parents** comme **chargés**.
- UI responsive moderne avec couleurs PC.

## Démarrage rapide (Docker prod)
1. Copiez `.env.example` en `.env` et ajustez si besoin.
2. `docker compose up --build`
3. Ouvrez http://localhost:8000
4. Connectez-vous : `admin / admin` (à changer en production).

## Données
- **Objets parents** : conteneurs (ex. *Sac Premiers Secours*).
- **Objets enfants** : éléments à l'intérieur (garrots, compresses…). Associez-les à un parent.
- **Codes uniques** possibles pour les pièces uniques.

## Sécurité
- Le mot de passe admin par défaut est `admin` (**à modifier** via la page utilisateurs).

## Structure
- `app/models.py` : modèles SQLAlchemy
- `app/events.py` : routes évènements + APIs AJAX
- `app/inventory.py` : gestion du stock
- `app/auth.py` : auth & admin utilisateurs
- `app/templates/` : pages HTML Jinja2
- `app/static/` : CSS & JS
- `Dockerfile`, `docker-compose.yml`
- `wsgi.py` (Gunicorn)

## TODO possibles
- Nginx en frontal si nécessaire.
- Exports PDF/CSV des vérifications.
- Permissions plus fines, suppression/édition d'items et d'évènements.
- WebSockets (Flask-SocketIO) pour du temps réel sans polling.
