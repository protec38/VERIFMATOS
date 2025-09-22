# PC38 Inventaire — V3 (Flask + Docker)

**Ce que fait cette version :**
- Admin gère utilisateurs + stock.
- Chef crée évènements et suit en direct.
- Secouristes via lien public, cochent/décochent les items.
- Stock parents/enfants avec quantité attendue.
- Live AJAX (~2s), parents validés si tous enfants OK, bouton Chargé.
- Exports CSV et PDF, journal d'activité.

## Démarrage
1. `cp .env.example .env`
2. `docker compose up --build`
3. http://localhost:8000 (admin/admin)
