# app/tree_query.py
from __future__ import annotations
from typing import Dict, List, Any, Tuple
from sqlalchemy import select, desc

from . import db
from .models import (
    Event,
    EventStatus,
    NodeType,
    StockNode,
    VerificationRecord,
    EventNodeStatus,
    event_stock,
)


def _latest_verifications_map(event_id: int, node_ids: List[int]) -> Dict[int, Tuple[str, str]]:
    """
    Retourne, pour chaque node_id ITEM, un tuple (status, verifier_name)
    correspondant au dernier enregistrement (created_at DESC).
    """
    if not node_ids:
        return {}

    q = (
        db.session.query(VerificationRecord)
        .filter(VerificationRecord.event_id == event_id, VerificationRecord.node_id.in_(node_ids))
        .order_by(VerificationRecord.node_id.asc(), VerificationRecord.created_at.desc())
    )
    out: Dict[int, Tuple[str, str]] = {}
    # on garde le premier par node_id (puisque triés par created_at DESC)
    for rec in q:
        if rec.node_id not in out:
            out[rec.node_id] = (rec.status or "PENDING", rec.verifier_name or "")
    return out


def _event_parent_status_map(event_id: int, node_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    """
    Pour les GROUP uniquement: récupère charged_vehicle + vehicle_name.
    """
    if not node_ids:
        return {}
    q = (
        db.session.query(EventNodeStatus)
        .filter(EventNodeStatus.event_id == event_id, EventNodeStatus.node_id.in_(node_ids))
    )
    out: Dict[int, Dict[str, Any]] = {}
    for ens in q:
        out[ens.node_id] = {
            "charged_vehicle": bool(ens.charged_vehicle),
            "vehicle_name": ens.vehicle_name or "",
        }
    return out


def _collect_subtree_ids(root: StockNode) -> List[int]:
    ids: List[int] = []

    def rec(n: StockNode) -> None:
        ids.append(n.id)
        for c in (n.children or []):
            rec(c)

    rec(root)
    return ids


def _serialize_node(
    node: StockNode,
    latest_map: Dict[int, Tuple[str, str]],
    parent_status_map: Dict[int, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Transforme un StockNode en dict JSON-serializable pour le front.
    """
    if node.type == NodeType.ITEM:
        last_status, last_by = latest_map.get(node.id, ("PENDING", ""))
        return {
            "id": node.id,
            "name": node.name,
            "type": "ITEM",
            "level": node.level,
            "quantity": node.quantity if node.quantity is not None else 1,
            "last_status": last_status,   # "OK" / "NOT_OK" / "PENDING"
            "last_by": last_by,
            "children": [],               # pour homogénéité
        }

    # GROUP
    st = parent_status_map.get(node.id, {})
    return {
        "id": node.id,
        "name": node.name,
        "type": "GROUP",
        "level": node.level,
        "quantity": None,
        "charged_vehicle": bool(st.get("charged_vehicle", False)),
        "vehicle_name": st.get("vehicle_name", "") or "",
        "children": [],  # rempli après
    }


def _build_tree_for_root(event_id: int, root: StockNode) -> Dict[str, Any]:
    """
    Construit le dict complet pour ce root (avec ses enfants) en minimisant les requêtes.
    """
    # 1) collecter tous les ids du sous-arbre pour charger verifs & status en 2 requêtes
    all_ids = _collect_subtree_ids(root)
    latest_map = _latest_verifications_map(event_id, all_ids)
    parent_status_map = _event_parent_status_map(event_id, all_ids)

    # 2) sérialiser récursivement
    def rec(n: StockNode) -> Dict[str, Any]:
        payload = _serialize_node(n, latest_map, parent_status_map)
        if n.type == NodeType.GROUP:
            payload["children"] = [rec(c) for c in sorted(n.children or [], key=lambda x: (x.type.value, x.name.lower()))]
        return payload

    return rec(root)


def build_event_tree(event_id: int) -> List[Dict[str, Any]]:
    """
    Retourne la forêt (liste de racines) attachée à l'évènement,
    chaque nœud entièrement sérialisé pour le front.

    Format d’un nœud:
      - commun: {id, name, type:"GROUP"|"ITEM", level, quantity}
      - GROUP: {charged_vehicle:bool, vehicle_name:str, children:[...]}
      - ITEM : {last_status:"OK"|"NOT_OK"|"PENDING", last_by:str, children:[]}
    """
    ev: Event | None = db.session.get(Event, event_id)
    if not ev:
        return []

    # récupérer les parents racine associés à l'évènement
    roots_q = (
        db.session.query(StockNode)
        .join(event_stock, event_stock.c.node_id == StockNode.id)
        .filter(event_stock.c.event_id == event_id)
        .order_by(StockNode.name.asc())
    )
    roots = roots_q.all()

    # construire pour chaque root
    tree: List[Dict[str, Any]] = []
    for root in roots:
        tree.append(_build_tree_for_root(event_id, root))

    return tree
