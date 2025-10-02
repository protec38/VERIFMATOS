# app/peremption/views.py
from __future__ import annotations
from datetime import date, timedelta
from typing import Dict, Any, List, Optional

from flask import Blueprint, render_template, request, jsonify, abort
from flask_login import login_required, current_user

from sqlalchemy.exc import ProgrammingError, OperationalError

# ⚠️ IMPORTANT : pas d'import de "db" depuis app/__init__.py pour éviter le circular import
from ..models import StockNode, StockItemExpiry, NodeType, Role

bp_peremption = Blueprint("peremption", __name__)

# ---------------- Helpers accès ----------------
def _can_view() -> bool:
    return current_user.is_authenticated and current_user.role in (Role.ADMIN, Role.CHEF, Role.VIEWER)

# ---------------- Helpers data ----------------
def _build_path(n: StockNode) -> str:
    """Chemin lisible: Racine › Sous-groupe › ... (sans l'item lui-même)."""
    parts: List[str] = []
    cur: Optional[StockNode] = n
    while cur and cur.parent is not None:
        cur = cur.parent
        if cur:
            parts.append(cur.name)
        else:
            break
    parts.reverse()
    return " › ".join(parts) if parts else "—"

def _row(
    n: StockNode,
    today: date,
    expiry: Optional[date],
    *,
    lot: Optional[str] = None,
    lot_quantity: Optional[int] = None,
    note: Optional[str] = None,
    entry_id: Optional[int] = None,
    source: str = "legacy",
) -> Dict[str, Any]:
    exp = expiry
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
        "id": entry_id or n.id,
        "item_id": n.id,
        "name": n.name,
        "quantity": n.quantity,
        "expiry_date": exp.isoformat() if exp else None,
        "days_left": days_left,
        "status": status,  # EXPIRED / SOON / OK
        "path": _build_path(n),
        "lot": lot,
        "lot_quantity": lot_quantity,
        "note": note,
        "source": source,
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

    items: List[Dict[str, Any]] = []

    # On tente d'utiliser la table des lots multiples si disponible
    item_ids_with_lots: set[int] = set()
    try:
        rows: List[StockItemExpiry] = (
            StockItemExpiry.query
            .join(StockNode, StockNode.id == StockItemExpiry.node_id)
            .filter(StockNode.type == NodeType.ITEM)
            .filter(StockItemExpiry.expiry_date <= limit)
            .order_by(
                StockItemExpiry.expiry_date.asc(),
                StockNode.name.asc(),
                StockItemExpiry.id.asc(),
            )
            .all()
        )
        for row in rows:
            item = row.item
            if not item:
                continue
            item_ids_with_lots.add(item.id)
            items.append(
                _row(
                    item,
                    today,
                    row.expiry_date,
                    lot=row.lot,
                    lot_quantity=row.quantity,
                    note=row.note,
                    entry_id=row.id,
                    source="lot",
                )
            )
    except (ProgrammingError, OperationalError):
        # Table absente → rollback et fallback legacy
        StockItemExpiry.query.session.rollback()
    except Exception:
        # Autre erreur → rollback et on retombe sur le legacy
        StockItemExpiry.query.session.rollback()

    # Fallback : anciennes données (colonne unique sur StockNode)
    legacy_q = (
        StockNode.query
        .filter(StockNode.type == NodeType.ITEM)
        .filter(StockNode.expiry_date.isnot(None))
        .filter(StockNode.expiry_date <= limit)
        .order_by(StockNode.expiry_date.asc(), StockNode.name.asc())
    )
    for node in legacy_q.all():
        if node.id in item_ids_with_lots:
            continue
        items.append(_row(node, today, node.expiry_date, source="legacy"))

    items.sort(key=lambda it: (
        it.get("expiry_date") is None,
        it.get("expiry_date") or "",
        (it.get("path") or "") + " " + (it.get("name") or "")
    ))

    return jsonify({
        "count": len(items),
        "items": items,
        "today": today.isoformat(),
        "window_days": days
    })
