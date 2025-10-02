# app/peremption/views.py
from __future__ import annotations
from datetime import date, timedelta
from typing import Dict, Any, List, Optional

from flask import Blueprint, render_template, request, jsonify, abort
from flask_login import login_required, current_user

from .. import db
from ..models import StockNode, NodeType, Role

bp_peremption = Blueprint("peremption", __name__)

# ---------------- Helpers accès ----------------
def _can_view() -> bool:
    return current_user.is_authenticated and current_user.role in (Role.ADMIN, Role.CHEF, Role.VIEWER)

# ---------------- Helpers data ----------------
def _build_path(n: StockNode) -> str:
    """Remonte les parents pour afficher un chemin joli: Racine › Sous-groupe › ..."""
    parts: List[str] = []
    cur: Optional[StockNode] = n
    # on veut le chemin sans l'item lui-même (juste les groupes parents)
    while cur and cur.parent is not None:
        cur = cur.parent
        if cur:
            parts.append(cur.name)
        else:
            break
    parts.reverse()
    return " › ".join(parts) if parts else "—"

def _row(n: StockNode, today: date) -> Dict[str, Any]:
    exp = n.expiry_date  # peut être None
    days_left: Optional[int] = None
    if exp is not None:
        days_left = (exp - today).days
    status = "OK"
    if days_left is not None:
        if days_left < 0:
            status = "EXPIRED"
        elif days_left <= 30:
            status = "SOON"
        else:
            status = "OK"
    return {
        "id": n.id,
        "name": n.name,
        "quantity": n.quantity,
        "expiry_date": exp.isoformat() if exp else None,
        "days_left": days_left,
        "status": status,  # EXPIRED / SOON / OK
        "path": _build_path(n),
    }

# ---------------- Routes ----------------
@bp_peremption.get("/peremption")
@login_required
def peremption_page():
    if not _can_view():
        abort(403)
    # La page s'alimente via /api/peremption côté JS
    return render_template("peremption.html")

@bp_peremption.get("/api/peremption")
@login_required
def peremption_api():
    if not _can_view():
        abort(403)

    try:
        days = int(request.args.get("days", "30"))
        if days < 0:
            days = 0
    except Exception:
        days = 30

    today = date.today()
    limit = today + timedelta(days=days)

    # Tous les items (ITEM) avec une date de péremption <= limit
    q = (
        StockNode.query
        .filter(StockNode.type == NodeType.ITEM)
        .filter(StockNode.expiry_date.isnot(None))
        .filter(StockNode.expiry_date <= limit)
        .order_by(StockNode.expiry_date.asc(), StockNode.name.asc())
    )

    items: List[Dict[str, Any]] = [_row(n, today) for n in q.all()]

    # Optionnel: on peut aussi renvoyer le nombre total d'items concernés
    return jsonify({
        "count": len(items),
        "items": items,
        "today": today.isoformat(),
        "window_days": days
    })
