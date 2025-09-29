# app/tree_query.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from . import db
from .models import StockNode, NodeType, event_stock, VerificationRecord

# --------- Helpers de conversion JSON-safe ---------
def _enum_to_str(x) -> Optional[str]:
    """Convertit proprement un Enum (ou autre) en str simple ('OK', 'NOT_OK', 'GROUP', 'ITEM', etc.)."""
    if x is None:
        return None
    # Enum.name prioritaire
    name = getattr(x, "name", None)
    if isinstance(name, str):
        return name
    # Sinon .value si c'est une str ('OK' / 'NOT_OK')
    value = getattr(x, "value", None)
    if isinstance(value, str):
        return value
    # Fallback
    s = str(x)
    # Nettoie "ItemStatus.OK" -> "OK"
    if "." in s:
        s = s.split(".")[-1]
    return s

def _dt_to_iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if isinstance(dt, datetime) else None

# --------- Etat dernier enregistrement par item ---------
@dataclass
class ItemState:
    status: Optional[str]  # "OK" | "NOT_OK" | None (toujours string ici)
    by: Optional[str]
    at: Optional[datetime]

def _latest_verifications_map(event_id: int) -> Dict[int, ItemState]:
    """
    Retourne {node_id: ItemState} avec la DERNIÈRE vérification (par created_at) par item pour l'événement.
    On convertit le status Enum -> str dès maintenant.
    """
    rows = (
        db.session.query(VerificationRecord)
        .filter(VerificationRecord.event_id == event_id)
        .order_by(VerificationRecord.node_id.asc(), VerificationRecord.created_at.asc())
        .all()
    )
    out: Dict[int, ItemState] = {}
    for r in rows:
        out[r.node_id] = ItemState(
            status=_enum_to_str(r.status),
            by=r.verifier_name,
            at=r.created_at,
        )
    return out

# --------- Index enfants ---------
def _children_index(all_nodes: List[StockNode]) -> Dict[Optional[int], List[StockNode]]:
    idx: Dict[Optional[int], List[StockNode]] = {}
    for n in all_nodes:
        idx.setdefault(n.parent_id, []).append(n)
    # Ordonne les enfants par type puis nom pour un rendu stable
    for k in idx:
        idx[k].sort(key=lambda x: (_enum_to_str(x.type), x.name.lower()))
    return idx

# --------- Construction récursive ---------
def _build_subtree(
    node: StockNode,
    idx: Dict[Optional[int], List[StockNode]],
    latest: Dict[int, ItemState],
) -> Tuple[dict, int, int]:
    """
    Renvoie (json_node, ok_count_subtree, total_items_subtree).
    Tous les champs sont JSON-safe (str/int/bool/list/dict/None).
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
        last_status = st.status if st else None            # déjà str
        last_by = st.by if st else None
        last_at = _dt_to_iso(st.at) if st else None
        if last_status == "OK":
            ok_count += 1
        data = {
            "id": node.id,
            "name": node.name,
            "type": "ITEM",                     # str
            "level": node.level,
            "quantity": node.quantity,
            "children": children_json,          # vide
            "last_status": last_status,         # "OK" | "NOT_OK" | None
            "last_by": last_by,
            "last_at": last_at,
        }
        return data, ok_count, total_items

    # GROUP
    complete = (total_items > 0 and ok_count == total_items)
    data = {
        "id": node.id,
        "name": node.name,
        "type": "GROUP",                        # str
        "level": node.level,
        "quantity": None,
        "children": children_json,
        "ok_count": ok_count,
        "total_items": total_items,
        "complete": complete,
    }
    return data, ok_count, total_items

# --------- Entrée publique ---------
def build_event_tree(event_id: int) -> List[dict]:
    """
    Construit l'arbre complet pour un événement (parents racine associés + descendants).
    Ne contient QUE des types JSON-sérialisables.
    """
    roots: List[StockNode] = (
        db.session.query(StockNode)
        .join(event_stock, event_stock.c.node_id == StockNode.id)
        .filter(event_stock.c.event_id == event_id)
        .order_by(StockNode.name.asc())
        .all()
    )
    if not roots:
        return []

    # Charge tous les noeuds une fois
    all_nodes: List[StockNode] = db.session.query(StockNode).all()
    idx = _children_index(all_nodes)
    latest = _latest_verifications_map(event_id)

    result: List[dict] = []
    for r in roots:
        node_json, _, _ = _build_subtree(r, idx, latest)
        result.append(node_json)
    return result
