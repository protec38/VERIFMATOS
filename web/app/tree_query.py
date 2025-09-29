from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional

from sqlalchemy import func, select, and_

from . import db
from .models import (
    StockNode,
    NodeType,
    VerificationRecord,
    EventNodeStatus,
    Event,
    event_stock,  # Table association évènement -> racines sélectionnées
)


def _type_str(t: NodeType | str | None) -> str:
    if t is None:
        return ""
    if isinstance(t, str):
        return t.upper()
    try:
        return t.name.upper()
    except Exception:
        return str(t).upper()


def _latest_verif_map(event_id: int) -> Dict[int, Dict[str, Optional[str]]]:
    """
    Retourne un dict: node_id -> { 'status': 'OK'|'NOT_OK', 'by': 'Nom', 'created_at': datetime }
    (dernière vérification par item pour l'évènement donné)
    """
    # Sous-requête: dernière date par (event_id, node_id)
    subq = (
        db.session.query(
            VerificationRecord.node_id.label("node_id"),
            func.max(VerificationRecord.created_at).label("max_ts"),
        )
        .filter(VerificationRecord.event_id == event_id)
        .group_by(VerificationRecord.node_id)
        .subquery()
    )

    # Jointure pour récupérer la ligne correspondante (status + by)
    q = (
        db.session.query(
            VerificationRecord.node_id,
            VerificationRecord.status,
            VerificationRecord.verifier_name,
            VerificationRecord.created_at,
        )
        .join(
            subq,
            and_(
                VerificationRecord.node_id == subq.c.node_id,
                VerificationRecord.created_at == subq.c.max_ts,
            ),
        )
        .filter(VerificationRecord.event_id == event_id)
    )

    out: Dict[int, Dict[str, Optional[str]]] = {}
    for node_id, status, by, created_at in q.all():
        out[int(node_id)] = {
            "status": (status or "").upper(),
            "by": by or "",
            "created_at": created_at,
        }
    return out


def _event_roots_ids(event_id: int) -> List[int]:
    rows = db.session.execute(
        select(event_stock.c.node_id).where(event_stock.c.event_id == event_id)
    ).all()
    return [int(r[0]) for r in rows]


def _event_group_status_map(event_id: int) -> Dict[int, Dict[str, Optional[str]]]:
    """
    node_id -> { 'charged_vehicle': bool, 'vehicle_label': str|None }
    """
    out: Dict[int, Dict[str, Optional[str]]] = {}
    rows = (
        db.session.query(EventNodeStatus)
        .filter(EventNodeStatus.event_id == event_id)
        .all()
    )
    has_vehicle_label = hasattr(EventNodeStatus, "vehicle_label")
    for r in rows:
        out[int(r.node_id)] = {
            "charged_vehicle": bool(r.charged_vehicle),
            "vehicle_label": (r.vehicle_label if has_vehicle_label else None),
        }
    return out


def _build_adjacency(nodes: List[StockNode]) -> Dict[Optional[int], List[StockNode]]:
    children: Dict[Optional[int], List[StockNode]] = defaultdict(list)
    for n in nodes:
        parent_id = getattr(n, "parent_id", None)
        children[parent_id].append(n)
    # tri léger pour une sortie stable
    for lst in children.values():
        lst.sort(key=lambda n: (0 if _type_str(n.type) == "GROUP" else 1, (n.name or "").lower(), n.id))
    return children


def _collect_descendants(root_id: int, children_map: Dict[Optional[int], List[StockNode]]) -> List[int]:
    """Renvoie tous les ids du sous-arbre (root compris)."""
    out: List[int] = []
    stack: List[int] = [root_id]
    id_map = {n.id: n for lst in children_map.values() for n in lst}
    while stack:
        nid = stack.pop()
        out.append(nid)
        for ch in children_map.get(nid, []):
            stack.append(ch.id)
    return out


def _node_to_json(
    n: StockNode,
    children_map: Dict[Optional[int], List[StockNode]],
    verif_map: Dict[int, Dict[str, Optional[str]]],
    group_status_map: Dict[int, Dict[str, Optional[str]]],
) -> Dict:
    t = _type_str(n.type)
    base = {
        "id": n.id,
        "name": n.name,
        "type": t,
        "quantity": getattr(n, "quantity", None),
        # Les clés suivantes sont ajoutées selon le type
        "children": [],
    }

    if t == "ITEM":
        last = verif_map.get(n.id)
        if last:
            base["last_status"] = last.get("status") or None
            base["last_by"] = last.get("by") or None
        else:
            # Pas de vérification => en attente
            base["last_status"] = None
            base["last_by"] = None
        return base

    # GROUP
    # État "chargé" + label véhicule s'ils existent
    gs = group_status_map.get(n.id)
    base["charged_vehicle"] = bool(gs.get("charged_vehicle")) if gs else False
    base["vehicle_label"] = gs.get("vehicle_label") if gs else None

    # Enfants
    children = []
    for ch in children_map.get(n.id, []):
        children.append(_node_to_json(ch, children_map, verif_map, group_status_map))
    base["children"] = children
    return base


def build_event_tree(event_id: int) -> List[Dict]:
    """
    Construit l'arbre JSON des stocks à vérifier pour un évènement.
    Sortie (liste de racines):
      - GROUP:
          { id, name, type:'GROUP', charged_vehicle:bool, vehicle_label:str|None, children:[...] }
      - ITEM:
          { id, name, type:'ITEM', quantity:int|None, last_status:'OK'|'NOT_OK'|None, last_by:str|None }
    """
    # 1) Vérifie existence évènement
    ev = db.session.get(Event, event_id)
    if not ev:
        return []

    # 2) Racines sélectionnées pour l'évènement
    root_ids = _event_roots_ids(event_id)
    if not root_ids:
        return []

    # 3) Charge tous les nœuds (on reste côté Python pour assembler le sous-arbre)
    all_nodes: List[StockNode] = db.session.query(StockNode).all()

    # 4) Tables d'aide
    children_map = _build_adjacency(all_nodes)
    id_map = {n.id: n for n in all_nodes}

    # 5) On délimite l'univers: tous descendants de chaque racine
    allowed_ids: set[int] = set()
    for rid in root_ids:
        if rid in id_map:
            allowed_ids.update(_collect_descendants(rid, children_map))

    # 6) Prépare les données de statut (items + groupes)
    verif_map = _latest_verif_map(event_id)
    group_status_map = _event_group_status_map(event_id)

    # 7) Construit le JSON racine par racine
    result: List[Dict] = []
    for rid in root_ids:
        root = id_map.get(rid)
        if not root:
            continue
        # Filtre les enfants hors périmètre en clonant temporairement children_map
        # (mais comme _node_to_json lit via children_map, on se contente de la
        #  liste existante; le 'allowed_ids' sert surtout si tu veux filtrer plus finement)
        result.append(_node_to_json(root, children_map, verif_map, group_status_map))

    return result
