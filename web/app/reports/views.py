# app/reports/views.py
from __future__ import annotations

from io import BytesIO
from flask import Blueprint, abort, send_file, jsonify
from flask_login import login_required, current_user

from .. import db

bp = Blueprint("reports", __name__, url_prefix="/reports")


def _can_view_reports() -> bool:
    """Autorise ADMIN, CHEF, VIEWER (comme tes autres pages chef)."""
    try:
        from ..models import Role  # import local pour éviter cycles
        return (
            current_user.is_authenticated
            and getattr(current_user, "role", None) in (Role.ADMIN, Role.CHEF, Role.VIEWER)
        )
    except Exception:
        # Si on ne peut pas importer, on restreint aux utilisateurs authentifiés
        return current_user.is_authenticated


@bp.get("/event/<int:event_id>/pdf")
@login_required
def event_pdf(event_id: int):
    """Génère le PDF de l’événement (lien: /reports/event/<id>/pdf)."""
    if not _can_view_reports():
        abort(403)

    # Récupère l'événement
    try:
        from ..models import Event
    except Exception as e:
        abort(500, description=f"Models indisponibles: {e}")

    ev = db.session.get(Event, int(event_id))
    if not ev:
        abort(404, description="Événement introuvable.")

    # Imports *dans* la fonction pour éviter les erreurs d'import au démarrage
    try:
        # Utils de construction des données
        from .utils import compute_summary, rows_for_csv
    except Exception as e:
        abort(500, description=f"Utils d'export indisponibles: {e}")

    try:
        # Générateur PDF (reportlab)
        from .pdfgen import build_pdf
    except Exception as e:
        # Erreur fréquente: reportlab non installé
        return jsonify({
            "error": "Le moteur PDF n'est pas disponible.",
            "detail": str(e),
            "hint": "Ajoute reportlab à requirements.txt (ex: reportlab==3.6.12) puis rebuild."
        }), 500

    # Données
    summary = compute_summary(ev.id)       # dict: total / ok / not_ok / todo
    csv_rows = rows_for_csv(ev.id)         # liste de lignes à plat (Parent, Item, Statut, ...)

    # Construction PDF
    try:
        pdf_bytes = build_pdf(ev, summary, csv_rows)
    except Exception as e:
        return jsonify({"error": "Échec génération PDF", "detail": str(e)}), 500

    # Retourne en inline (affichage dans le navigateur)
    filename = f"rapport_event_{ev.id}.pdf"
    return send_file(
        BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=False,
        download_name=filename,
        max_age=0,  # pas de cache
        conditional=False,
        etag=False,
    )
