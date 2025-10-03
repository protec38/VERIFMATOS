# app/stats/views.py — Endpoints de statistiques d'événement + péremptions
from __future__ import annotations
from datetime import date
from typing import Dict, Any, List, Optional

from flask import Blueprint, jsonify
from flask_login import login_required, current_user

from .. import db
from ..models import Role, StockNode, StockItemExpiry, NodeType
from ..reports.utils import compute_summary, build_event_tree, latest_verifications

from sqlalchemy.exc import ProgrammingError, OperationalError

bp = Blueprint("stats", __name__)

# -------------------------------------------------
# Droits
# -------------------------------------------------
def require_view() -> bool:
    return current_user.is_authenticated and current_user.role in (
        Role.ADMIN,
        Role.CHEF,
        Role.VIEWER,
        getattr(Role, "VERIFICATIONPERIODIQUE", Role.VIEWER),
    )

# -------------------------------------------------
# Statistiques d'un événement (existant)
# -------------------------------------------------
@bp.get("/events/<int:event_id>/stats")
@login_required
def event_stats(event_id: int):
    if not require_view():
        return jsonify(error="Forbidden"), 403
    summary = compute_summary(event_id)
    return jsonify(summary)

@bp.get("/events/<int:event_id>/tree")
@login_required
def event_tree(event_id: int):
    if not require_view():
        return jsonify(error="Forbidden"), 403
    tree = build_event_tree(event_id)
    return jsonify(tree)

@bp.get("/events/<int:event_id>/latest")
@login_required
def event_latest(event_id: int):
    if not require_view():
        return jsonify(error="Forbidden"), 403
    data = latest_verifications(event_id)
    # jsonify friendly
    out = {
        nid: {
            "status": v["status"],
            "verifier_name": v["verifier_name"],
            "comment": v["comment"],
            "created_at": v["created_at"].isoformat() if v.get("created_at") else None,
        }
        for nid, v in data.items()
    }
    return jsonify(out)

# -------------------------------------------------
# Péremptions (NOUVEAU)
# -------------------------------------------------
def _classify_expiry(d: date | None, today: date) -> str:
    if not d:
        return "no_date"
    delta = (d - today).days
    if delta < 0:
        return "expired"
    if delta <= 30:
        return "j30"
    if delta <= 60:
        return "j60"
    return "later"

def _serialize_item(n: StockNode) -> Dict[str, Any]:
    return {
        "id": n.id,
        "name": n.name,
        "quantity": n.quantity or 0,
        "expiry_date": n.expiry_date.isoformat() if getattr(n, "expiry_date", None) else None,
        "level": n.level,
        "parent_id": n.parent_id,
    }


def _expiries_by_item() -> Dict[int, List[StockItemExpiry]]:
    try:
        rows: List[StockItemExpiry] = (
            StockItemExpiry.query
            .order_by(
                StockItemExpiry.node_id.asc(),
                StockItemExpiry.expiry_date.asc(),
                StockItemExpiry.id.asc(),
            )
            .all()
        )
    except (ProgrammingError, OperationalError):
        StockItemExpiry.query.session.rollback()
        return {}
    except Exception:
        StockItemExpiry.query.session.rollback()
        return {}

    mapping: Dict[int, List[StockItemExpiry]] = {}
    for row in rows:
        mapping.setdefault(row.node_id, []).append(row)
    return mapping

@bp.get("/stock/expiry")
@login_required
def stock_expiry_list():
    """
    Retourne la liste des items (ITEM) avec date de péremption, groupés par catégorie :
      - expired (date passée)
      - j30 (<= 30 jours)
      - j60 (<= 60 jours)
      - later (> 60 jours)
      - no_date (sans date)
    """
    if not require_view():
        return jsonify(error="Forbidden"), 403

    today = date.today()

    # NOTE: .expiry_date est nullable et uniquement pertinent pour ITEM
    q = (
        db.session.query(StockNode)
        .filter(StockNode.type == NodeType.ITEM)
        # garder même ceux sans date (pour "no_date")
    )

    expiries_map = _expiries_by_item()

    buckets: Dict[str, List[Dict[str, Any]]] = {"expired": [], "j30": [], "j60": [], "later": [], "no_date": []}
    for n in q.all():
        entries = []
        closest: Optional[date] = None
        for entry in expiries_map.get(n.id, []):
            delta = (entry.expiry_date - today).days
            entries.append(
                {
                    "id": entry.id,
                    "expiry_date": entry.expiry_date.isoformat(),
                    "quantity": entry.quantity,
                    "lot": entry.lot,
                    "note": entry.note,
                    "days_left": delta,
                    "status": _classify_expiry(entry.expiry_date, today),
                }
            )
            if closest is None or entry.expiry_date < closest:
                closest = entry.expiry_date

        fallback_date = getattr(n, "expiry_date", None)
        effective_date = closest or fallback_date
        cat = _classify_expiry(effective_date, today)
        payload = _serialize_item(n)
        payload["expiry_date"] = effective_date.isoformat() if effective_date else None
        if entries:
            payload["expiries"] = entries
            payload["next_expiry"] = entries[0]
        buckets[cat].append(payload)

    # Tri par date (quand présente), puis par nom
    def sort_key(it: Dict[str, Any]):
        d = it.get("expiry_date")
        return (d is None, d or "", it.get("name","").lower())

    for k in buckets:
        buckets[k].sort(key=sort_key)

    return jsonify({"today": today.isoformat(), **buckets})

@bp.get("/stock/expiry/counts")
@login_required
def stock_expiry_counts():
    """Compteurs par catégorie (pour bulles d'alerte dans le menu / badges)."""
    if not require_view():
        return jsonify(error="Forbidden"), 403

    today = date.today()
    q = (
        db.session.query(StockNode)
        .filter(StockNode.type == NodeType.ITEM)
    )

    expiries_map = _expiries_by_item()

    counts = {"expired": 0, "j30": 0, "j60": 0, "later": 0, "no_date": 0}
    for n in q.all():
        closest: Optional[date] = None
        for entry in expiries_map.get(n.id, []):
            if closest is None or entry.expiry_date < closest:
                closest = entry.expiry_date
        fallback_date = getattr(n, "expiry_date", None)
        effective_date = closest or fallback_date
        cat = _classify_expiry(effective_date, today)
        counts[cat] += 1

    return jsonify({"today": today.isoformat(), **counts})
