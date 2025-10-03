# app/reports/utils.py — utilitaires pour exporter les données d'un événement
from __future__ import annotations
import json
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional

from .. import db
from ..models import (
    Event,
    EventStatus,
    VerificationRecord,
    ItemStatus,
    EventNodeStatus,
    StockNode,
    NodeType,
    event_stock,
)

# -------------------------------------------------------------------
# Helpers: construction d'arbre et lecture de l'état "dernier connu"
# -------------------------------------------------------------------

def _node_json(n: StockNode) -> Dict[str, Any]:
    return {
        "id": n.id,
        "name": n.name,
        "type": n.type.name,   # "GROUP" | "ITEM"
        "level": n.level,
        "quantity": n.quantity if n.type == NodeType.ITEM else None,
        "unique_item": bool(getattr(n, "unique_item", False)),
        "unique_quantity": getattr(n, "unique_quantity", None) if getattr(n, "unique_item", False) else None,
        "children": [],
    }

def _children_index(all_nodes: List[StockNode]) -> Dict[Optional[int], List[StockNode]]:
    idx: Dict[Optional[int], List[StockNode]] = {}
    for n in all_nodes:
        idx.setdefault(n.parent_id, []).append(n)
    # tri stable par type puis nom (pour un rendu constant)
    for k in idx:
        idx[k].sort(key=lambda x: (x.type.name, x.name.lower()))
    return idx

def _decode_charge_comment(raw: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    vehicle: Optional[str] = None
    operator: Optional[str] = None
    display: Optional[str] = None
    if raw:
        txt = raw.strip()
        if txt:
            try:
                data = json.loads(txt)
            except Exception:
                parts = [p.strip() for p in txt.split("|")]
                for part in parts:
                    low = part.lower()
                    if low.startswith("véhicule"):
                        _, _, rest = part.partition(":")
                        if rest.strip():
                            vehicle = rest.strip()
                    elif low.startswith("par"):
                        _, _, rest = part.partition(":")
                        if rest.strip():
                            operator = rest.strip()
                display = txt if txt else None
            else:
                if isinstance(data, dict):
                    veh_val = data.get("vehicle_name")
                    op_val = data.get("operator_name")
                    if veh_val:
                        vehicle = veh_val.strip() or None
                    if op_val:
                        operator = op_val.strip() or None
                    parts: List[str] = []
                    if vehicle:
                        parts.append(f"Véhicule: {vehicle}")
                    if operator:
                        parts.append(f"Par: {operator}")
                    display = " | ".join(parts) if parts else None
                else:
                    display = txt
    return vehicle, operator, display


def _latest_verifications_map(event_id: int) -> Dict[int, Dict[str, Any]]:
    """
    Pour chaque ITEM (node_id) de l'événement, retourne uniquement
    la DERNIÈRE vérif (la plus récente).
    """
    # On récupère tout et on déduplique en gardant la plus récente par node_id
    rows: List[VerificationRecord] = (
        VerificationRecord.query
        .filter_by(event_id=event_id)
        .order_by(VerificationRecord.node_id.asc(), VerificationRecord.created_at.desc())
        .all()
    )
    latest: Dict[int, Dict[str, Any]] = {}
    for r in rows:
        if r.node_id not in latest:
            latest[r.node_id] = {
                "status": (r.status.name if isinstance(r.status, ItemStatus) else str(r.status)).upper(),
                "verifier_name": r.verifier_name,
                "comment": r.comment,
                "created_at": r.created_at,
                # champs étendus (peuvent être None)
                "issue_code": getattr(r.issue_code, "name", None),
                "observed_qty": r.observed_qty,
                "missing_qty": r.missing_qty,
            }
    return latest

def _build_subtree(node: StockNode,
                   idx: Dict[Optional[int], List[StockNode]],
                   latest: Dict[int, Dict[str, Any]],
                   selected_quantities: Dict[int, Optional[int]]) -> Tuple[Dict[str, Any], int, int]:
    """
    Construit récursivement un sous-arbre JSON-safe.
    Retourne (data, ok_count, total_items)
    """
    data = _node_json(node)

    # Feuille = ITEM
    is_unique = bool(getattr(node, "unique_item", False))

    if node.type == NodeType.ITEM or is_unique:
        info = latest.get(node.id, {})
        status = info.get("status", "TODO")
        ok = 1 if status == "OK" else 0
        total = 1
        if is_unique:
            qty_selected = selected_quantities.get(node.id)
            if qty_selected is None:
                qty_selected = getattr(node, "unique_quantity", None)
            data["unique_item"] = True
            data["unique_quantity"] = getattr(node, "unique_quantity", None)
            data["quantity"] = qty_selected
            data["selected_quantity"] = qty_selected
        leaf_payload = {
            "last_status": status,
            "last_by": info.get("verifier_name"),
            "last_at": info.get("created_at"),
            "comment": info.get("comment"),
            "issue_code": info.get("issue_code"),
            "observed_qty": info.get("observed_qty"),
            "missing_qty": info.get("missing_qty"),
        }
        data.update(leaf_payload)

        if node.type == NodeType.ITEM:
            data.update(leaf_payload)
            return data, ok, total

        # unique parent behaving like a group -> attach synthetic child
        data.update({
            "unique_item": True,
            "unique_parent": True,
            "unique_quantity": getattr(node, "unique_quantity", None),
            "quantity": qty_selected,
            "selected_quantity": qty_selected,
        })

        child = {
            "id": f"unique-{node.id}",
            "name": node.name,
            "type": NodeType.ITEM.name,
            "level": node.level + 1,
            "quantity": qty_selected,
            "unique_item": True,
            "unique_from_parent": True,
            "unique_parent_id": node.id,
            "target_node_id": node.id,
            **leaf_payload,
        }
        data["children"].append(child)
        return data, ok, total

    # Groupe = GROUP
    children = idx.get(node.id, [])
    data["unique_item"] = is_unique
    if is_unique:
        data["unique_quantity"] = getattr(node, "unique_quantity", None)
    ok_sum = 0
    total_sum = 0
    for c in children:
        cj, ok_c, tot_c = _build_subtree(c, idx, latest, selected_quantities)
        data["children"].append(cj)
        ok_sum += ok_c
        total_sum += tot_c

    # Un parent "complet" si tous ses items descendants sont OK
    data.update({
        "ok_count": ok_sum,
        "total_items": total_sum,
        "complete": (total_sum > 0 and ok_sum == total_sum),
    })
    return data, ok_sum, total_sum

def build_event_tree(event_id: int) -> List[Dict[str, Any]]:
    """
    Arbre complet des racines de stock attachées à l'événement.
    Chaque nœud est JSON-safe et contient les infos nécessaires aux exports.
    """
    # Racines liées à l'événement
    selection_rows = db.session.execute(
        event_stock.select().where(event_stock.c.event_id == event_id)
    ).fetchall()
    selected_quantities: Dict[int, Optional[int]] = {int(r.node_id): r.selected_quantity for r in selection_rows}

    roots: List[StockNode] = (
        db.session.query(StockNode)
        .join(event_stock, event_stock.c.node_id == StockNode.id)
        .filter(event_stock.c.event_id == event_id)
        .filter(StockNode.parent_id.is_(None))   # uniquement les racines
        .order_by(StockNode.name.asc())
        .all()
    )
    if not roots:
        return []

    # Tous les nœuds (pour pouvoir remonter les enfants sans n+1)
    all_nodes: List[StockNode] = db.session.query(StockNode).all()
    idx = _children_index(all_nodes)
    latest = _latest_verifications_map(event_id)

    out: List[Dict[str, Any]] = []
    for r in roots:
        tree, _, _ = _build_subtree(r, idx, latest, selected_quantities)
        out.append(tree)
    return out

# -------------------------------------------------------------------
# Flatten, stats et exports
# -------------------------------------------------------------------

def flatten_items(tree: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Aplati l'arbre d'un événement en ne conservant que les ITEMS.
    """
    items: List[Dict[str, Any]] = []

    def rec(n: Dict[str, Any]):
        if n.get("type") == "ITEM" or n.get("unique_item"):
            items.append(n)
        for c in n.get("children", []):
            rec(c)

    for r in tree:
        rec(r)
    return items

def latest_verifications(event_id: int) -> Dict[int, Dict[str, Any]]:
    """
    Exposé public : map node_id -> infos dernière vérif.
    (Réutilisé par rows_for_csv)
    """
    return _latest_verifications_map(event_id)

def parent_statuses(event_id: int) -> Dict[int, Dict[str, Any]]:
    """
    Retourne l'état par parent (EventNodeStatus) : chargé, commentaire, MAJ.
    """
    rows = EventNodeStatus.query.filter_by(event_id=event_id).all()
    out: Dict[int, Dict[str, Any]] = {}
    for r in rows:
        vehicle, operator, display = _decode_charge_comment(r.comment)
        out[r.node_id] = {
            "charged_vehicle": r.charged_vehicle,
            "vehicle_name": vehicle,
            "operator_name": operator,
            "comment": display or r.comment,
            "updated_at": r.updated_at,
        }
    return out

def compute_summary(event_id: int) -> Dict[str, Any]:
    """
    Calcule un récap global simple (nb total d’items, OK, NOT_OK, TODO).
    """
    tree = build_event_tree(event_id)
    items = flatten_items(tree)
    latest = latest_verifications(event_id)
    total = len(items)

    def status_of(n: Dict[str, Any]) -> str:
        # priorise last_status déjà présent dans l'arbre
        s = n.get("last_status")
        if s:
            return s
        info = latest.get(n["id"], {})
        return info.get("status", "TODO")

    ok = sum(1 for it in items if status_of(it) == "OK")
    not_ok = sum(1 for it in items if status_of(it) == "NOT_OK")
    todo = total - ok - not_ok
    return {"total": total, "ok": ok, "not_ok": not_ok, "todo": todo}

def rows_for_csv(event_id: int) -> List[List[str]]:
    """
    Ligne CSV par ITEM:
    [Parent, Sous-parent, Nom item, Quantité cible, Statut, Vérificateur, Commentaire, Horodatage ISO,
     (optionnel) Motif, Qte constatée, Qte manquante]
    """
    tree = build_event_tree(event_id)
    latest = latest_verifications(event_id)

    headers = [
        "Parent",
        "Sous-parent",
        "Item",
        "Quantité",
        "Statut",
        "Vérificateur",
        "Commentaire",
        "Horodatage",
        "Motif",
        "QteConstatée",
        "QteManquante",
    ]
    rows: List[List[str]] = [headers]

    def rec(n: Dict[str, Any], parents: List[str]):
        t = n.get("type")
        name = n.get("name", "")

        if t == "ITEM":
            info = latest.get(n["id"], {})
            status = n.get("last_status") or info.get("status", "TODO")
            who = n.get("last_by") or info.get("verifier_name", "")
            com = n.get("comment") or info.get("comment", "")
            when_dt: Optional[datetime] = n.get("last_at") or info.get("created_at")
            when = when_dt.isoformat() if isinstance(when_dt, datetime) else ""

            issue = n.get("issue_code") or info.get("issue_code") or ""
            observed = n.get("observed_qty")
            if observed is None:
                observed = info.get("observed_qty")
            missing = n.get("missing_qty")
            if missing is None:
                missing = info.get("missing_qty")

            row = [
                parents[0] if len(parents) > 0 else "",
                parents[1] if len(parents) > 1 else "",
                name,
                str(n.get("quantity") or 0),
                status,
                who,
                com or "",
                when,
                str(issue or ""),
                "" if observed is None else str(observed),
                "" if missing is None else str(missing),
            ]
            rows.append(row)

        # descente
        new_parents = parents
        if t == "GROUP":
            # On ne garde que les deux premiers niveaux dans les colonnes Parent/Sous-parent
            if len(parents) < 2:
                new_parents = parents + [name]
        for c in n.get("children", []):
            rec(c, new_parents)

    for r in tree:
        rec(r, [])

    return rows
