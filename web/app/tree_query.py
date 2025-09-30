# app/tree_query.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from . import db
from .models import (
    StockNode,
    NodeType,
    event_stock,
    VerificationRecord,
    EventNodeStatus,
)

# -------------------------------------------------------------------
# Types internes
# -------------------------------------------------------------------

@dataclass
class ItemState:
    status: str            # "OK" | "NOT_OK" | "TODO"
    by: Optional[str]      # dernier vérificateur
    at: Optional[str]      # ISO8601 (string) pour JSON-safety


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def _to_iso(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    try:
        return dt.isoformat()
    except Exception:
        return None

def _latest_verifications_map(event_id: int) -> Dict[int, ItemState]:
    """
    Pour chaque node_id (ITEM) de l'événement, retourne uniquement la DERNIÈRE vérification.
    """
    rows: List[VerificationRecord] = (
        VerificationRecord.query
        .filter_by(event_id=event_id)
        .order_by(VerificationRecord.node_id.asc(), VerificationRecord.created_at.desc())
        .all()
    )
    latest: Dict[int, ItemState] = {}
    for r in rows:
        if r.node_id in latest:
            continue  # on a déjà la plus récente pour ce node_id
        s = getattr(r.status, "name", str(r.status)).upper() if r.status else "TODO"
        latest[r.node_id] = ItemState(
            status=s if s in {"OK", "NOT_OK", "TODO"} else "TODO",
            by=r.verifier_name,
            at=_to_iso(r.created_at),
        )
    return latest

def _parent_status_map(event_id: int) -> Dict[int, bool]:
    """
    Map node_id (GROUP) -> charged_vehicle (bool) pour l'événement.
    """
    rows: List[EventNodeStatus] = EventNodeStatus.query.filter_by(event_id=event_id).all()
    return {r.node_id: bool(r.charged_vehicle) for r in rows}

def _children_index(all_nodes: List[StockNode]) -> Dict[Optional[int], List[StockNode]]:
    """
    Index parent_id -> [children] pour parcourir l'arbre efficacement sans N+1.
    """
    idx: Dict[Optional[int], List[StockNode]] = {}
    for n in all_nodes:
        idx.setdefault(n.parent_id, []).append(n)
    # tri stable pour un rendu constant
    for k in idx:
        idx[k].sort(key=lambda x: (x.type.name, x.name.lower()))
    return idx


# -------------------------------------------------------------------
# Construction récursive
# -------------------------------------------------------------------

def _build_subtree(node: StockNode,
                   idx: Dict[Optional[int], List[StockNode]],
                   latest: Dict[int, ItemState],
                   charged_map: Dict[int, bool]) -> Tuple[dict, int, int]:
    """
    Construit récursivement un sous-arbre JSON-safe.
    Retourne (data, ok_count, total_items).
    """
    # ITEM (feuille)
    if node.type == NodeType.ITEM:
        state = latest.get(node.id, ItemState(status="TODO", by=None, at=None))
        data = {
            "id": node.id,
            "name": node.name,
            "type": "ITEM",
            "level": node.level,
            "quantity": node.quantity or 0,
            "children": [],
            "last_status": state.status,
            "last_by": state.by,
            "last_at": state.at,
        }
        ok = 1 if state.status == "OK" else 0
        return data, ok, 1

    # GROUP (parent)
    ok_sum = 0
    total_sum = 0
    children = []
    for c in idx.get(node.id, []):
        cj, ok_c, tot_c = _build_subtree(c, idx, latest, charged_map)
        children.append(cj)
        ok_sum += ok_c
        total_sum += tot_c

    complete = (total_sum > 0 and ok_sum == total_sum)
    data = {
        "id": node.id,
        "name": node.name,
        "type": "GROUP",
        "level": node.level,
        "quantity": None,
        "children": children,
        "ok_count": ok_sum,
        "total_items": total_sum,
        "complete": complete,
        # Nouvel attribut : état "chargé" (pour le bouton/checkbox UI)
        "charged_vehicle": bool(charged_map.get(node.id, False)),
    }
    return data, ok_sum, total_sum


# -------------------------------------------------------------------
# Entrée principale
# -------------------------------------------------------------------

def build_event_tree(event_id: int) -> List[dict]:
    """
    Construit l'arbre complet pour un événement :
      - Prend les racines (level=0) associées via event_stock
      - Ajoute, pour chaque parent (GROUP), `charged_vehicle`
      - Ajoute, pour chaque ITEM, `last_status`, `last_by`, `last_at` (ISO) et `quantity`
      - Calcule `ok_count`, `total_items`, `complete` pour chaque parent
    Retourne une liste de racines (dict JSON-safe).
    """
    # Racines associées à l'événement (seulement level 0)
    roots: List[StockNode] = (
        db.session.query(StockNode)
        .join(event_stock, event_stock.c.node_id == StockNode.id)
        .filter(event_stock.c.event_id == event_id)
        .filter(StockNode.parent_id.is_(None))
        .order_by(StockNode.name.asc())
        .all()
    )
    if not roots:
        return []

    # On charge tout l'inventaire pour éviter N+1
    all_nodes: List[StockNode] = db.session.query(StockNode).all()
    idx = _children_index(all_nodes)
    latest = _latest_verifications_map(event_id)
    charged_map = _parent_status_map(event_id)

    out: List[dict] = []
    for r in roots:
        node_json, _, _ = _build_subtree(r, idx, latest, charged_map)
        out.append(node_json)
    return out
