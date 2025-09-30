# app/reports/views.py — endpoints d'export CSV/PDF
from __future__ import annotations
from io import BytesIO, StringIO
import csv
from flask import Blueprint, jsonify, send_file, Response
from flask_login import login_required, current_user
from .. import db
from ..models import Event, Role
from .utils import compute_summary, rows_for_csv
from .pdfgen import build_pdf

bp = Blueprint("reports", __name__)

def require_manager() -> bool:
    return current_user.is_authenticated and current_user.role in (Role.ADMIN, Role.CHEF)

# ------------------------------------------------------------------
# Export CSV par événement
# ------------------------------------------------------------------
@bp.get("/events/<int:event_id>/report.csv")
@login_required
def export_csv(event_id: int):
    if not require_manager():
        return jsonify(error="Forbidden"), 403

    ev = db.session.get(Event, event_id)
    if not ev:
        return jsonify(error="Not found"), 404

    data = rows_for_csv(event_id)  # première ligne = headers
    # Génération en mémoire
    sio = StringIO(newline="")
    writer = csv.writer(sio, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    for row in data:
        writer.writerow(row)
    payload = sio.getvalue().encode("utf-8-sig")  # BOM pour Excel FR

    return Response(
        payload,
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="rapport_event_{event_id}.csv"'
        },
    )

# ------------------------------------------------------------------
# Export PDF par événement
# ------------------------------------------------------------------
@bp.get("/events/<int:event_id>/report.pdf")
@login_required
def export_pdf(event_id: int):
    if not require_manager():
        return jsonify(error="Forbidden"), 403

    ev = db.session.get(Event, event_id)
    if not ev:
        return jsonify(error="Not found"), 404

    summary = compute_summary(event_id)
    rows = rows_for_csv(event_id)
    pdf_bytes = build_pdf(ev, summary, rows)

    return send_file(
        BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"rapport_event_{event_id}.pdf",
    )
