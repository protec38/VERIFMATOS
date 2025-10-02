# app/tree_query.py — construction du TREE pour une page évènement
from __future__ import annotations
from typing import Dict, Any, List, Optional
from datetime import date
import json

from . import db
from .models import (
    Event,
    StockNode,
    NodeType,
    VerificationRecord,   # historise OK / NOT_OK / TODO
    EventNodeStatus,      # infos “groupe chargé”, commentaires, etc.
    StockItemExpiry,      # ⬅️ nouvelles lignes d'expiration
    event_stock,          # table d’association (event_id, node_id)
)

# --------- helpers ---------
def _norm_status(s: Optional[str]) -> str:
    if s is None:
        return "TODO"
    # Enum -> .name
    if hasattr(s, "name"):
        try:
            return str(s.name).upper()
        except Exception:
            pass
    if isinstance(s, bool):
        return "OK" if s else "NOT_OK"
    return str(s).upper()

def _latest_verifs_map(event_id: int, item_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    """
    Renvoie {node_id: {"status": "OK|NOT_OK|TODO", "by": str, "at": iso, "comment": str,
                       "issue_code": str, "observed_qty": int|None, "missing_qty": int|None}}
    """
    if not item_ids:
        return {}
    q = (
        VerificationRecord.query
        .filter(VerificationRecord.event_id == event_id)
        .filter(VerificationRecord.node_id.in_(item_ids))
        .order_by(VerificationRecord.node_id.asc(), VerificationRecord.created_at.desc())
    )
    out: Dict[int, Dict[str, Any]] = {}
    for r in q:
        nid = int(r.node_id)
        if nid in out:
            continue  # déjà le plus récent
        out[nid] = {
            "status": _norm_status(getattr(r, "status", None)),
            "by": getattr(r, "verifier_name", None),
            "at": (getattr(r, "updated_at", None) or getattr(r, "created_at", None)),
            "comment": getattr(r, "comment", None),
            "issue_code": _norm_status(getattr(r, "issue_code", None)),
            "observed_qty": getattr(r, "observed_qty", None),
            "missing_qty": getattr(r, "missing_qty", None),
        }
        if out[nid]["at"]:
            out[nid]["at"] = out[nid]["at"].isoformat()
    return out

def _ens_map(event_id: int) -> Dict[int, EventNodeStatus]:
    rows = EventNodeStatus.query.filter_by(event_id=event_id).all()
    return {int(r.node_id): r for r in rows}

def _expiries_for_items(item_ids: List[int]) -> Dict[int, List[StockItemExpiry]]:
    """Batch: récupère toutes les lignes d'expiration pour les items donnés."""
    if not item_ids:
        return {}
    rows = (
        StockItemExpiry.query
        .filter(StockItemExpiry.node_id.in_(item_ids))
        .order_by(StockItemExpiry.node_id.asc(), StockItemExpiry.expiry_date.asc(), StockItemExpiry.id.asc())
        .all()
    )
    out: Dict[int, List[StockItemExpiry]] = {}
    for e in rows:
        out.setdefault(int(e.node_id), []).append(e)
    return out

# --------- arbre ---------
def _serialize(node: StockNode,
               latest: Dict[int, Dict[str, Any]],
               is_root: bool,
               ens_map: Dict[int, EventNodeStatus],
               exp_map: Dict[int, List[StockItemExpiry]]) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "id": node.id,
        "name": node.name,
        "type": node.type.name if hasattr(node.type, "name") else str(node.type),
    }

    if node.type == NodeType.ITEM:
        info = latest.get(int(node.id), {})
        # Nouvelles expirations multiples
        exps = exp_map.get(int(node.id), [])
        expiries_payload: List[Dict[str, Any]] = [
            {
                "date": e.expiry_date.isoformat(),
                "quantity": e.quantity,
                "lot": e.lot,
                "note": e.note,
                "id": e.id,
            }
            for e in exps
        ]

        # Par compatibilité avec l'ancien front : on garde expiry_date = la plus proche
        legacy_expiry = None
        if expiries_payload:
            legacy_expiry = expiries_payload[0]["date"]
        elif node.expiry_date:
            legacy_expiry = node.expiry_date.isoformat()

        base.update({
            "last_status": info.get("status", "TODO"),
            "last_by": info.get("by"),
            "last_at": info.get("at"),
            "comment": info.get("comment"),
            "issue_code": info.get("issue_code"),
            "observed_qty": info.get("observed_qty"),
            "missing_qty": info.get("missing_qty"),
            "quantity": node.quantity,          # quantité cible (si définie)
            "expiry_date": legacy_expiry,       # compatibilité
            "expiries": expiries_payload,       # ⬅️ liste complète des dates
        })
        base["children"] = []
        return base

    # GROUP
    children = []
    # relation ORM “children” ou requête fallback
    if hasattr(node, "children"):
        for c in node.children:
            children.append(_serialize(c, latest, False, ens_map, exp_map))
    else:
        childs = StockNode.query.filter_by(parent_id=node.id).all()
        for c in childs:
            children.append(_serialize(c, latest, False, ens_map, exp_map))

    base["children"] = children
    base["is_event_root"] = bool(is_root)

    ens = ens_map.get(int(node.id))
    if ens:
        base["charged_vehicle"] = getattr(ens, "charged_vehicle", None)
        vehicle_name = getattr(ens, "charged_vehicle_name", None) if hasattr(ens, "charged_vehicle_name") else None
        operator_name = None
        raw_comment = getattr(ens, "comment", None)
        if raw_comment:
            try:
                data = json.loads(raw_comment)
                vehicle_name = data.get("vehicle_name") or vehicle_name
                operator_name = data.get("operator_name") or data.get("operator")
            except Exception:
                pass
            base["comment"] = raw_comment
        if vehicle_name is not None:
            base["charged_vehicle_name"] = vehicle_name
        if operator_name is not None:
            base["charged_vehicle_operator"] = operator_name

    return base

def build_event_tree(event_id: int) -> List[Dict[str, Any]]:
    # Récupère les racines attachées à l’événement
    rows = db.session.execute(
        event_stock.select().where(event_stock.c.event_id == event_id)
    ).fetchall()
    root_ids = [r.node_id for r in rows]
    root_nodes: List[StockNode] = []
    if root_ids:
        root_nodes = StockNode.query.filter(StockNode.id.in_(root_ids)).all()

    # Récupère tous les ITEM ids pour batcher verifs + expirations
    item_ids: List[int] = []
    def collect_items(n: StockNode):
        if n.type == NodeType.ITEM:
            item_ids.append(int(n.id))
        else:
            if hasattr(n, "children") and n.children:
                for c in n.children:
                    collect_items(c)
            else:
                for c in StockNode.query.filter_by(parent_id=n.id).all():
                    collect_items(c)
    for r in root_nodes:
        collect_items(r)

    latest = _latest_verifs_map(event_id, item_ids)
    ens_map = _ens_map(event_id)
    exp_map = _expiries_for_items(item_ids)

    return [_serialize(r, latest, True, ens_map, exp_map) for r in root_nodes]

# --------- stats (optionnelles) ----------
def tree_stats(tree: List[Dict[str, Any]]) -> Dict[str, int]:
    """Calcule un petit récapitulatif OK / NOT_OK / TODO."""
    items: List[Dict[str, Any]] = []

    def collect(n: Dict[str, Any]):
        if (n.get("type") or "").upper() == "ITEM":
            items.append(n)
        for c in n.get("children") or []:
            collect(c)

    for r in tree:
        collect(r)

    def status_of(n: Dict[str, Any]) -> str:
        s = (n.get("last_status") or "TODO").upper()
        return "OK" if s == "OK" else ("NOT_OK" if s == "NOT_OK" else "TODO")

    total = len(items)
    ok = sum(1 for it in items if status_of(it) == "OK")
    not_ok = sum(1 for it in items if status_of(it) == "NOT_OK")
    todo = total - ok - not_ok
    return {"total": total, "ok": ok, "not_ok": not_ok, "todo": todo}
