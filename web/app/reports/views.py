# app/reports/views.py — endpoints d'export CSV/PDF
from __future__ import annotations
from io import BytesIO
import csv
from flask import Blueprint, jsonify, send_file
from flask_login import login_required, current_user
from .. import db
from ..models import Event, Role
from .utils import compute_summary, rows_for_csv
from .pdfgen import build_pdf

bp = Blueprint("reports", __name__)

def require_manager():
    return current_user.is_authenticated and current_user.role in (Role.ADMIN, Role.CHEF)

@bp.get("/events/<int:event_id>/report.csv")
@login_required
def export_csv(event_id: int):
    if not require_manager():
        return jsonify(error="Forbidden"), 403
    ev = db.session.get(Event, event_id)
    if not ev:
        return jsonify(error="Not found"), 404
    rows = rows_for_csv(event_id)
    buf = BytesIO()
    writer = csv.writer(buf, delimiter=";")
    for r in rows:
        writer.writerow(r)
    buf.seek(0)
    return send_file(buf, mimetype="text/csv",
                     as_attachment=True, download_name=f"rapport_event_{event_id}.csv")

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
    return send_file(BytesIO(pdf_bytes), mimetype="application/pdf",
                     as_attachment=True, download_name=f"rapport_event_{event_id}.pdf")
