# app/tree_query.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from . import db
from .models import StockNode, NodeType, event_stock, VerificationRecord

@dataclass
class ItemState:
    status: Optional[str]  # "OK" | "NOT_OK" | None
    by: Optional[str]
    at: Optional[datetime]

def _latest_verifications_map(event_id: int) -> Dict[int, ItemState]:
    """
    Retourne un dict {node_id: ItemState} avec la DERNIÈRE vérification (par created_at) par item pour l'événement.
    """
    rows = (
        db.session.query(VerificationRecord)
        .filter(VerificationRecord.event_id == event_id)
        .order_by(VerificationRecord.node_id.asc(), VerificationRecord.created_at.asc())
        .all()
    )
    out: Dict[int, ItemState] = {}
    for r in rows:
        # On écrase au fil de l'eau -> le dernier pour un node_id reste
        out[r.node_id] = ItemState(status=r.status, by=r.verifier_name, at=r.created_at)
    return out

def _children_index(all_nodes: List[StockNode]) -> Dict[Optional[int], List[StockNode]]:
    idx: Dict[Optional[int], List[StockNode]] = {}
    for n in all_nodes:
        idx.setdefault(n.parent_id, []).append(n)
    # Optionnel: ordonner enfants par type puis nom
    for k in idx:
        idx[k].sort(key=lambda x: (x.type.value, x.name.lower()))
    return idx

def _build_subtree(
    node: StockNode,
    idx: Dict[Optional[int], List[StockNode]],
    latest: Dict[int, ItemState],
) -> Tuple[dict, int, int]:
    """
    Construit récursivement un noeud JSON.
    Renvoie (json, ok_count_subtree, total_items_subtree).
    """
    children_json: List[dict] = []
    ok_count = 0
    total_items = 0

    for ch in idx.get(node.id, []):
        ch_json, ch_ok, ch_tot = _build_subtree(ch, idx, latest)
        children_json.append(ch_json)
        ok_count += ch_ok
        total_items += ch_tot

    if node.type == NodeType.ITEM:
        total_items += 1
        st = latest.get(node.id)
        last_status = st.status if st else None
        last_by = st.by if st else None
        last_at = st.at.isoformat() if (st and st.at) else None
        if last_status == "OK":
            ok_count += 1
        data = {
            "id": node.id,
            "name": node.name,
            "type": "ITEM",
            "level": node.level,
            "quantity": node.quantity,
            "children": children_json,  # devrait être vide
            "last_status": last_status,  # "OK" | "NOT_OK" | null
            "last_by": last_by,
            "last_at": last_at,
        }
        return data, ok_count, total_items

    # GROUP
    complete = (total_items > 0 and ok_count == total_items)
    data = {
        "id": node.id,
        "name": node.name,
        "type": "GROUP",
        "level": node.level,
        "quantity": None,
        "children": children_json,
        "ok_count": ok_count,
        "total_items": total_items,
        "complete": complete,
    }
    return data, ok_count, total_items

def build_event_tree(event_id: int) -> List[dict]:
    """
    Construit l'arbre complet pour un événement (parents racine associés + descendants).
    Inclus les champs d'état:
      - ITEM: last_status, last_by, last_at
      - GROUP: ok_count, total_items, complete
    """
    # Récupère les roots liés à l'événement
    roots: List[StockNode] = (
        db.session.query(StockNode)
        .join(event_stock, event_stock.c.node_id == StockNode.id)
        .filter(event_stock.c.event_id == event_id)
        .order_by(StockNode.name.asc())
        .all()
    )
    if not roots:
        return []

    # On charge tous les noeuds pour construire l'arbre côté Python
    all_nodes: List[StockNode] = db.session.query(StockNode).all()
    idx = _children_index(all_nodes)
    latest = _latest_verifications_map(event_id)

    result: List[dict] = []
    for r in roots:
        item, *_agg = _build_subtree(r, idx, latest)
        result.append(item)
    return result
