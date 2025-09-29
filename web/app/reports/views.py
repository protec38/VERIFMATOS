# app/reports/views.py
from __future__ import annotations
from io import StringIO
import csv
from flask import Blueprint, make_response, render_template_string, abort

from .. import db
from ..models import Event
from .utils import compute_summary, rows_for_csv

bp = Blueprint("reports", __name__, url_prefix="/reports")


@bp.get("/event/<int:event_id>/csv")
def event_csv(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    rows = rows_for_csv(event_id)

    si = StringIO()
    if rows:
        fieldnames = list(rows[0].keys())
    else:
        fieldnames = ["Root", "Chemin", "Élément", "Qté", "Statut", "Vérifié par", "Date vérif", "Parent chargé", "Véhicule"]

    writer = csv.DictWriter(si, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow(r)

    resp = make_response(si.getvalue())
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    safe = f"{ev.name}".replace("/", "_").replace("\\", "_")
    resp.headers["Content-Disposition"] = f'attachment; filename="event_{ev.id}_{safe}.csv"'
    return resp


@bp.get("/event/<int:event_id>/pdf")
def event_pdf(event_id: int):
    """
    Génère une page HTML « prête à imprimer » (Ctrl/Cmd+P -> Enregistrer en PDF).
    Pas de dépendance wkhtmltopdf nécessaire.
    """
    ev = db.session.get(Event, event_id) or abort(404)
    data = compute_summary(event_id)

    html = render_template_string(
        """
<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <title>Export — {{ data.event.name }}</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    :root{
      --text:#1d2736; --muted:#6b7a8c; --border:#e2e8f0;
      --ok:#12b886; --bad:#e03131; --wait:#3b5bdb;
    }
    *{box-sizing:border-box}
    body{font-family:Segoe UI,Roboto,Arial,sans-serif;margin:0;padding:24px;color:var(--text)}
    h1{margin:0 0
