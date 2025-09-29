# app/tree_query.py — construction d'un arbre JSON pour un évènement
from __future__ import annotations
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict

from sqlalchemy import func, and_, select
from sqlalchemy.orm import aliased

from . import db
from .models import (
    StockNode, NodeType,
    VerificationRecord, EventNodeStatus,
    event_stock,
)

def _node_to_dict_basic(n: StockNode) -> Dict[str, Any]:
    """Projection minimale commune aux GROUP/ITEM attendue par les templates."""
    t = (n.type.name if hasattr(n.type, "name") else str(n.type)).upper()
    return {
        "id": n.id,
        "name": n.name,
        "type": "GROUP" if "GROUP" in t else "ITEM",
        # quantité seulement utile pour ITEM ; on met tout de même pour simplifier côté JS
        "quantity": getattr(n, "quantity", None),
        # champs que les templates lisent éventuellement
        "children": [],
    }

def _fetch_event_roots(event_id: int) -> List[int]:
    q = db.session.execute(
        select(event_stock.c.node_id).where(event_stock.c.event_id == event_id)
    )
    return [row[0] for row in q.all()]

def _fetch_all_nodes_index() -> Tuple[Dict[int, StockNode], Dict[Optional[int], List[int]]]:
    """Charge tous les nœuds une fois et construit les index utiles."""
    nodes: Dict[int, StockNode] = {}
    children_by_parent: Dict[Optional[int], List[int]] = defaultdict(list)

    for n in db.session.query(StockNode).all():
        nodes[n.id] = n
        children_by_parent[n.parent_id].append(n.id)

    # tri par nom pour un rendu stable
    for pid in list(children_by_parent.keys()):
        children_by_parent[pid].sort(key=lambda nid: nodes[nid].name.lower())

    return nodes, children_by_parent

def _collect_subtree(root_id: int, nodes: Dict[int, StockNode], children_by_parent: Dict[Optional[int], List[int]]) -> List[int]:
    """Retourne la liste des ids du sous-arbre (root inclus) par parcours DFS."""
    out: List[int] = []
    stack = [root_id]
    while stack:
        nid = stack.pop()
        out.append(nid)
        stack.extend(reversed(children_by_parent.get(nid, [])))  # reversed pour garder l'ordre après pop()
    return out

def _fetch_latest_item_status(event_id: int, item_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    """Pour chaque item_id, récupère le dernier statut (OK/NOT_OK) et 'by' + timestamp.
       Retourne un dict: node_id -> {"status": "OK"/"NOT_OK", "by": str, "ts": datetime}"""
    if not item_ids:
        return {}
    # Sous-requête: max(created_at) par node
    sub = (
        db.session.query(
            VerificationRecord.node_id.label("node_id"),
            func.max(VerificationRecord.created_at).label("max_ts"),
        )
        .filter(VerificationRecord.event_id == event_id, VerificationRecord.node_id.in_(item_ids))
        .group_by(VerificationRecord.node_id)
        .subquery()
    )

    latest = {}
    # Joindre pour récupérer la ligne correspondante
    vr = aliased(VerificationRecord)
    rows = (
        db.session.query(vr.node_id, vr.status, vr.verifier_name, vr.created_at)
        .join(sub, and_(vr.node_id == sub.c.node_id, vr.created_at == sub.c.max_ts))
        .all()
    )
    for node_id, status, by, ts in rows:
        # Nos templates attendent "OK" | "NOT_OK" (en MAJUSCULES) | None
        st = str(status)
        # status peut être un enum ou une str; normalize
        st_upper = st.upper()
        if st_upper.endswith("ItemStatus.OK".upper()):  # paranoia
            st_upper = "OK"
        elif st_upper.endswith("NOT_OK"):
            st_upper = "NOT_OK"
        elif "OK" in st_upper and "NOT" not in st_upper:
            st_upper = "OK"
        elif "NOT_OK" in st_upper or "NOT" in st_upper:
            st_upper = "NOT_OK"
        latest[node_id] = {"status": "OK" if st_upper == "OK" else ("NOT_OK" if st_upper == "NOT_OK" else None),
                           "by": by, "ts": ts}
    return latest

def _fetch_parent_status(event_id: int, group_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    """Récupère (charged_vehicle, vehicle_name) par groupe pour l'évènement."""
    if not group_ids:
        return {}
    rows = (
        db.session.query(EventNodeStatus.node_id, EventNodeStatus.charged_vehicle, EventNodeStatus.vehicle_name)
        .filter(EventNodeStatus.event_id == event_id, EventNodeStatus.node_id.in_(group_ids))
        .all()
    )
    out: Dict[int, Dict[str, Any]] = {}
    for nid, charged, vname in rows:
        out[nid] = {"charged_vehicle": bool(charged), "vehicle_name": vname}
    return out

def _build_json_tree_for_root(root_id: int,
                              nodes: Dict[int, StockNode],
                              children_by_parent: Dict[Optional[int], List[int]],
                              latest_status: Dict[int, Dict[str, Any]],
                              parent_status: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
    """Construit le JSON pour un root, en descendant récursivement."""
    def build(nid: int) -> Dict[str, Any]:
        n = nodes[nid]
        base = _node_to_dict_basic(n)
        if base["type"] == "GROUP":
            # Ajout info "charged" si disponible
            ps = parent_status.get(nid) or {}
            base["charged_vehicle"] = bool(ps.get("charged_vehicle"))
            if ps.get("vehicle_name"):
                base["vehicle_name"] = ps["vehicle_name"]
            base["children"] = [build(cid) for cid in children_by_parent.get(nid, [])]
        else:
            # ITEM
            st = latest_status.get(nid) or {}
            base["last_status"] = st.get("status")  # "OK" | "NOT_OK" | None
            base["last_by"] = st.get("by")
            # quantité par défaut
            if base.get("quantity") is None:
                base["quantity"] = 1
        return base

    return build(root_id)

def build_event_tree(event_id: int) -> List[Dict[str, Any]]:
    """
    Construit l'arbre de l'évènement pour le rendu (pages cheffe & publique).
    Chaque nœud renvoyé contient:
      GROUP: {id, name, type:"GROUP", charged_vehicle?, vehicle_name?, children:[...] }
      ITEM:  {id, name, type:"ITEM", quantity, last_status? -> "OK"/"NOT_OK"/None, last_by? }
    """
    root_ids = _fetch_event_roots(event_id)
    if not root_ids:
        return []

    nodes_idx, childs = _fetch_all_nodes_index()

    # collecter tous les ids descendants à partir des roots
    subtrees: Dict[int, List[int]] = {}
    all_ids: List[int] = []
    for rid in root_ids:
        if rid not in nodes_idx:
            continue
        ids = _collect_subtree(rid, nodes_idx, childs)
        subtrees[rid] = ids
        all_ids.extend(ids)

    # séparer items vs groupes
    item_ids = [nid for nid in all_ids if nid in nodes_idx and (nodes_idx[nid].type == NodeType.ITEM or str(nodes_idx[nid].type).upper().endswith("ITEM"))]
    group_ids = [nid for nid in all_ids if nid in nodes_idx and (nodes_idx[nid].type == NodeType.GROUP or str(nodes_idx[nid].type).upper().endswith("GROUP"))]

    latest = _fetch_latest_item_status(event_id, item_ids)
    pstatus = _fetch_parent_status(event_id, group_ids)

    # Construire le JSON pour chaque root
    result: List[Dict[str, Any]] = []
    # garder l'ordre alphabétique des roots pour stabilité
    root_ids_sorted = sorted([rid for rid in root_ids if rid in nodes_idx], key=lambda x: nodes_idx[x].name.lower())
    for rid in root_ids_sorted:
        result.append(_build_json_tree_for_root(rid, nodes_idx, childs, latest, pstatus))

    return result
