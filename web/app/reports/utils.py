# app/reports/utils.py — utilitaires pour exporter les données d'un événement
from __future__ import annotations
from typing import List, Dict, Any, Tuple
from datetime import datetime
from .. import db
from ..models import (
    Event, EventStatus, VerificationRecord, ItemStatus,
    EventNodeStatus, StockNode, NodeType, event_stock
)

def _collect_tree(root: StockNode) -> Dict[str, Any]:
    return {
        "id": root.id,
        "name": root.name,
        "type": root.type.name,
        "level": root.level,
        "quantity": root.quantity,
        "children": [_collect_tree(c) for c in sorted(root.children, key=lambda x: (x.level, x.id))]
    }

def build_event_tree(event_id: int) -> List[Dict[str, Any]]:
    rows = db.session.execute(event_stock.select().where(event_stock.c.event_id == event_id)).fetchall()
    root_ids = [r.node_id for r in rows]
    if not root_ids:
        return []
    roots = StockNode.query.filter(StockNode.id.in_(root_ids)).order_by(StockNode.id).all()
    return [_collect_tree(r) for r in roots]

def flatten_items(tree: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    items = []
    def rec(n):
        if n["type"] == "ITEM":
            items.append(n)
        for c in n.get("children", []):
            rec(c)
    for r in tree:
        rec(r)
    return items

def latest_verifications(event_id: int) -> Dict[int, Dict[str, Any]]:
    """Retourne la dernière vérification par item (node_id) pour l'événement."""
    rows = (VerificationRecord.query
            .filter_by(event_id=event_id)
            .order_by(VerificationRecord.node_id, VerificationRecord.created_at.desc())
           ).all()
    latest = {}
    for r in rows:
        if r.node_id not in latest:
            latest[r.node_id] = {
                "status": r.status.name,
                "verifier_name": r.verifier_name,
                "comment": r.comment,
                "created_at": r.created_at
            }
    return latest

def parent_statuses(event_id: int) -> Dict[int, Dict[str, Any]]:
    rows = EventNodeStatus.query.filter_by(event_id=event_id).all()
    return {r.node_id: {"charged_vehicle": r.charged_vehicle, "comment": r.comment, "updated_at": r.updated_at} for r in rows}

def compute_summary(event_id: int) -> Dict[str, Any]:
    tree = build_event_tree(event_id)
    items = flatten_items(tree)
    latest = latest_verifications(event_id)
    total = len(items)
    ok = sum(1 for it in items if latest.get(it["id"], {}).get("status") == "OK")
    not_ok = sum(1 for it in items if latest.get(it["id"], {}).get("status") == "NOT_OK")
    todo = total - ok - not_ok
    return {"total": total, "ok": ok, "not_ok": not_ok, "todo": todo}

def rows_for_csv(event_id: int) -> List[List[str]]:
    tree = build_event_tree(event_id)
    latest = latest_verifications(event_id)
    rows = [["Parent", "Sous-parent", "Nom de l'item", "Qté", "Statut", "Vérifié par", "Commentaire", "Date vérif."]]
    def rec(n, parents):
        new_parents = parents + [n["name"]] if n["type"] == "GROUP" else parents
        if n["type"] == "ITEM":
            info = latest.get(n["id"], {})
            status = info.get("status", "TODO")
            who = info.get("verifier_name", "")
            com = info.get("comment", "")
            when = info.get("created_at").isoformat() if info.get("created_at") else ""
            row = [parents[0] if len(parents)>0 else "",
                   parents[1] if len(parents)>1 else "",
                   n["name"], str(n.get("quantity") or 0),
                   status, who, com, when]
            rows.append(row)
        for c in n.get("children", []):
            rec(c, new_parents)
    for r in tree:
        rec(r, [])
    return rows
