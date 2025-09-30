# app/tree_query.py — construction du TREE pour une page évènement
from __future__ import annotations
from typing import Dict, Any, List, Optional
from sqlalchemy import desc

from . import db
from .models import (
    Event,
    StockNode,
    NodeType,
    VerificationRecord,
    EventNodeStatus,
    event_stock,
)

def _norm_status(s: Optional[str]) -> str:
    if not s:
        return "PENDING"
    s = s.upper()
    if s in ("NOT_OK", "NOK", "KO", "NOT-OK", "NOTOK"):
        return "NOT_OK"
    if s == "OK":
        return "OK"
    return "PENDING"


def _latest_verifs_map(event_id: int, node_ids: List[int]) -> Dict[int, Dict[str, str]]:
    if not node_ids:
        return {}
    # Dernier enregistrement par node_id (created_at desc, id desc)
    q = (
        db.session.query(VerificationRecord)
        .filter(VerificationRecord.event_id == event_id, VerificationRecord.node_id.in_(node_ids))
        .order_by(desc(VerificationRecord.created_at), desc(VerificationRecord.id))
        .all()
    )
    seen = set()
    out: Dict[int, Dict[str, str]] = {}
    for r in q:
        if r.node_id in seen:
            continue
        seen.add(r.node_id)
        out[r.node_id] = {
            "status": _norm_status(r.status),
            "by": r.verifier_name or "",
        }
    return out


def _ens_map(event_id: int) -> Dict[int, EventNodeStatus]:
    ens_list = db.session.query(EventNodeStatus).filter_by(event_id=event_id).all()
    return {e.node_id: e for e in ens_list}


def _serialize(node: StockNode, verifs: Dict[int, Dict[str, str]], is_root: bool, ens_map: Dict[int, EventNodeStatus]) -> Dict[str, Any]:
    if node.type == NodeType.ITEM:
        last = verifs.get(node.id)
        return {
            "id": node.id,
            "name": node.name,
            "type": "ITEM",
            "quantity": node.quantity,
            "last_status": _norm_status(last["status"]) if last else "PENDING",
            "last_by": last["by"] if last else "",
            "children": [],
        }

    # GROUP
    data: Dict[str, Any] = {
        "id": node.id,
        "name": node.name,
        "type": "GROUP",
        "children": [],
        "is_event_root": bool(is_root),
    }
    if is_root:
        ens = ens_map.get(node.id)
        data["charged_vehicle"] = bool(ens.charged_vehicle) if ens else False
        data["charged_vehicle_name"] = (ens.vehicle_name or None) if ens else None

    # ordre stable
    for c in sorted(node.children, key=lambda x: (x.level, x.id)):
        data["children"].append(_serialize(c, verifs, False, ens_map))
    return data


def build_event_tree(event_id: int) -> List[Dict[str, Any]]:
    ev = db.session.get(Event, event_id)
    if not ev:
        return []

    # Racines de l'évènement (parents choisis)
    root_nodes: List[StockNode] = (
        db.session.query(StockNode)
        .join(event_stock, event_stock.c.node_id == StockNode.id)
        .filter(event_stock.c.event_id == event_id)
        .order_by(StockNode.id.asc())
        .all()
    )

    # Collecter tous les ITEM ids (pour batcher les verifs)
    item_ids: List[int] = []
    def collect_items(n: StockNode):
        if n.type == NodeType.ITEM:
            item_ids.append(n.id)
        for c in n.children:
            collect_items(c)
    for r in root_nodes:
        collect_items(r)

    verifs = _latest_verifs_map(event_id, item_ids)
    ens_map = _ens_map(event_id)

    return [_serialize(r, verifs, True, ens_map) for r in root_nodes]
