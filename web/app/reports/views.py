# app/reports/views.py
from __future__ import annotations
from io import StringIO
import csv
from typing import Any, Dict, List, Tuple

from flask import Blueprint, Response, abort, make_response, render_template_string
from flask_login import login_required, current_user

from .. import db
from ..models import Event, Role, NodeType
from ..tree_query import build_event_tree

bp = Blueprint("reports", __name__, url_prefix="/reports")


# ---------------- Permissions helpers ----------------
def _can_view_reports() -> bool:
    return current_user.is_authenticated and current_user.role in (Role.ADMIN, Role.CHEF)

def _get_event_or_404(event_id: int) -> Event:
    ev = db.session.get(Event, event_id)
    if not ev:
        abort(404)
    if not _can_view_reports():
        abort(403)
    return ev


# ---------------- Tree helpers ----------------
def _flatten_tree(roots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    def rec(n: Dict[str, Any], path: List[str]):
        cur_path = path + [n["name"]]
        if n.get("type") == "ITEM":
            rows.append({
                "path": " / ".join(cur_path[:-1]),
                "parent_name": cur_path[-2] if len(cur_path) >= 2 else "",
                "name": n["name"],
                "quantity": n.get("quantity", 1),
                "status": n.get("last_status", "PENDING"),
                "by": n.get("last_by", ""),
            })
        else:
            for c in n.get("children", []) or []:
                rec(c, cur_path)

    for r in roots:
        rec(r, [])
    return rows


def _summarize_tree(roots: List[Dict[str, Any]]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "total_items": 0,
        "ok": 0,
        "not_ok": 0,
        "pending": 0,
        "parents": [],
    }

    def stats_for_group(g: Dict[str, Any]) -> Tuple[int, int, int, int]:
        total = ok = not_ok = pending = 0

        def rec(n: Dict[str, Any]):
            nonlocal total, ok, not_ok, pending
            if n.get("type") == "ITEM":
                total += 1
                st = (n.get("last_status") or "PENDING").upper()
                if st == "OK":
                    ok += 1
                elif st == "NOT_OK":
                    not_ok += 1
                else:
                    pending += 1
            for c in n.get("children", []) or []:
                rec(c)

        rec(g)
        return total, ok, not_ok, pending

    for r in roots:
        t, o, b, p = stats_for_group(r)
        summary["total_items"] += t
        summary["ok"] += o
        summary["not_ok"] += b
        summary["pending"] += p
        summary["parents"].append({
            "name": r["name"],
            "charged_vehicle": bool(r.get("charged_vehicle")),
            "vehicle_name": r.get("vehicle_name") or "",
            "total": t, "ok": o, "not_ok": b, "pending": p,
        })

    return summary


# ---------------- Views ----------------
@bp.get("/event/<int:event_id>/json")
@login_required
def report_event_json(event_id: int):
    ev = _get_event_or_404(event_id)
    tree = build_event_tree(ev.id)
    summary = _summarize_tree(tree)
    return {
        "event": {"id": ev.id, "name": ev.name, "date": str(ev.date) if ev.date else None, "status": ev.status},
        "summary": summary,
        "roots": tree,
    }


@bp.get("/event/<int:event_id>/csv")
@login_required
def report_event_csv(event_id: int):
    ev = _get_event_or_404(event_id)
    tree = build_event_tree(ev.id)
    rows = _flatten_tree(tree)

    si = StringIO()
    writer = csv.writer(si, delimiter=";")
    writer.writerow(["Evenement", "Date", "Parent", "Chemin", "Item", "Quantité", "Statut", "Par"])
    for r in rows:
        writer.writerow([
            ev.name,
            ev.date.isoformat() if ev.date else "",
            r["parent_name"],
            r["path"],
            r["name"],
            r["quantity"],
            r["status"],
            r["by"],
        ])
    out = make_response(si.getvalue())
    out.headers["Content-Type"] = "text/csv; charset=utf-8"
    out.headers["Content-Disposition"] = f'attachment; filename="event_{ev.id}_export.csv"'
    return out


@bp.get("/event/<int:event_id>/pdf")
@login_required
def report_event_pdf(event_id: int):
    ev = _get_event_or_404(event_id)
    tree = build_event_tree(ev.id)
    summary = _summarize_tree(tree)
    flat = _flatten_tree(tree)

    html = render_template_string(
        """
<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <title>Rapport — {{ ev.name }}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root{
      --ok:#12b886; --bad:#ff6b6b; --wait:#74849a;
      --text:#111; --muted:#444; --border:#ccc;
    }
    *{box-sizing:border-box}
    body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:var(--text);margin:20px}
    h1{margin:0 0 6px 0} h2{margin:18px 0 8px 0}
    .muted{color:var(--muted)}
    .badge{display:inline-block;border:1px solid var(--border);border-radius:999px;padding:2px 8px;font-size:12px}
    .chips{display:flex;gap:8px;flex-wrap:wrap}
    .chip{border:1px solid var(--border);border-radius:999px;padding:4px 8px;font-weight:600;font-size:12px}
    .ok{color:#0a503f;border-color:#9fdcc9;background:#e9fbf5}
    .bad{color:#7b1024;border-color:#f6b3bf;background:#fff0f3}
    .wait{color:#2a3c58;border-color:#c7d2e4;background:#f1f4fa}
    .table{width:100%;border-collapse:collapse;margin-top:10px}
    .table th,.table td{border:1px solid var(--border);padding:6px}
    .table th{text-align:left;background:#f7f7f7}
    .parents{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px;margin:10px 0}
    .card{border:1px solid var(--border);border-radius:10px;padding:10px}
    .small{font-size:12px}
    @media print {
      .no-print{display:none !important}
      body{margin:0}
    }
  </style>
</head>
<body>
  <div class="no-print" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
    <div>
      <h1>Rapport — {{ ev.name }}</h1>
      <div class="muted small">
        Date : {{ ev.date or "—" }} • Statut : <span class="badge">{{ ev.status }}</span>
      </div>
    </div>
    <button onclick="window.print()" class="no-print" style="padding:8px 12px;border-radius:8px;border:1px solid #bbb;background:#fff;cursor:pointer">
      Imprimer / PDF
    </button>
  </div>

  <div class="chips">
    <span class="chip ok">OK : {{ summary.ok }}</span>
    <span class="chip bad">Non conformes : {{ summary.not_ok }}</span>
    <span class="chip wait">En attente : {{ summary.pending }}</span>
    <span class="chip">Total items : {{ summary.total_items }}</span>
  </div>

  <h2>Parents</h2>
  <div class="parents">
    {% for p in summary.parents %}
      <div class="card">
        <div style="font-weight:700">{{ p.name }}</div>
        <div class="small muted" style="margin:4px 0">
          Chargé : {{ "oui" if p.charged_vehicle else "non" }}
          {% if p.vehicle_name %} • Véhicule : 🚐 {{ p.vehicle_name }}{% endif %}
        </div>
        <div class="chips" style="margin-top:6px">
          <span class="chip ok">OK {{ p.ok }}</span>
          <span class="chip bad">NC {{ p.not_ok }}</span>
          <span class="chip wait">Attente {{ p.pending }}</span>
          <span class="chip">Total {{ p.total }}</span>
        </div>
      </div>
    {% endfor %}
  </div>

  <h2>Détail des items</h2>
  <table class="table">
    <thead>
      <tr>
        <th>Parent</th>
        <th>Chemin</th>
        <th>Item</th>
        <th>Qté</th>
        <th>Statut</th>
        <th>Par</th>
      </tr>
    </thead>
    <tbody>
      {% for r in flat %}
        <tr>
          <td>{{ r.parent_name }}</td>
          <td class="small">{{ r.path }}</td>
          <td>{{ r.name }}</td>
          <td>{{ r.quantity }}</td>
          <td>
            {% if r.status == "OK" %}✅ OK{% elif r.status == "NOT_OK" %}❌ Non conforme{% else %}⏳ En attente{% endif %}
          </td>
          <td>{{ r.by }}</td>
        </tr>
      {% endfor %}
    </tbody>
  </table>
</body>
</html>
        """,
        ev=ev,
        summary=summary,
        flat=flat,
    )
    resp = make_response(html)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp
