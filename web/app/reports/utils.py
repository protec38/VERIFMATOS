# app/reports/utils.py
from __future__ import annotations
from typing import Dict, List, Any, Tuple, Iterable
from datetime import datetime

from .. import db
from ..models import (
    Event,
    EventStatus,
    StockNode,
    VerificationRecord,
    EventNodeStatus,
    event_stock,
)
from ..tree_query import build_event_tree


def _flatten_tree_with_path(tree: List[Dict[str, Any]]) -> Iterable[Dict[str, Any]]:
    """
    Aplati l'arbre en énumérant chaque nœud avec son 'path' (liste de noms des groupes)
    jusqu'à lui.
    """
    def rec(node: Dict[str, Any], path: List[str]):
        current_path = path + [node["name"]]
        yield {
            **node,
            "_path": path[:]  # chemin SANS le nom du nœud
        }
        for c in node.get("children", []) or []:
            yield from rec(c, current_path if node["type"] == "GROUP" else path)
    for root in tree or []:
        yield from rec(root, [])


def _latest_verifications_map(event_id: int, item_ids: List[int]) -> Dict[int, Tuple[str, str, datetime]]:
    """
    Pour une liste d'items (ids), renvoie un dict:
      node_id -> (status, verifier_name, created_at)
    Ne renvoie qu'UN seul enregistrement (le plus récent) par item.
    """
    if not item_ids:
        return {}
    q = (
        db.session.query(VerificationRecord)
        .filter(
            VerificationRecord.event_id == event_id,
            VerificationRecord.node_id.in_(item_ids),
        )
        .order_by(VerificationRecord.node_id.asc(), VerificationRecord.created_at.desc())
    )
    out: Dict[int, Tuple[str, str, datetime]] = {}
    for rec in q:
        if rec.node_id not in out:
            out[rec.node_id] = (rec.status or "PENDING", rec.verifier_name or "", rec.created_at)
    return out


def _parent_status_map(event_id: int, node_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    """
    Renvoie pour des GROUP: charged_vehicle + vehicle_name
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


def compute_summary(event_id: int) -> Dict[str, Any]:
    """
    Donne un résumé exploitable pour PDF / Dashboard:
      {
        "event": {...},
        "totals": {"items":N,"ok":A,"not_ok":B,"pending":C},
        "roots": [
          {"id":..,"name":..,"charged_vehicle":bool,"vehicle_name":"", "items":n,"ok":a,"not_ok":b,"pending":c}
        ]
      }
    """
    ev: Event | None = db.session.get(Event, event_id)
    if not ev:
        return {}

    tree = build_event_tree(event_id)

    # Totaux globaux
    total_items = ok = bad = 0

    # Totaux par root
    roots_summary: List[Dict[str, Any]] = []
    for root in tree:
        r_items = r_ok = r_bad = 0

        def rec(n: Dict[str, Any]):
            nonlocal total_items, ok, bad, r_items, r_ok, r_bad
            if n["type"] == "ITEM":
                r_items += 1
                total_items += 1
                st = (n.get("last_status") or "PENDING").upper()
                if st == "OK":
                    r_ok += 1
                    ok += 1
                elif st == "NOT_OK":
                    r_bad += 1
                    bad += 1
            for c in n.get("children") or []:
                rec(c)

        rec(root)
        roots_summary.append({
            "id": root["id"],
            "name": root["name"],
            "charged_vehicle": bool(root.get("charged_vehicle")),
            "vehicle_name": root.get("vehicle_name") or "",
            "items": r_items,
            "ok": r_ok,
            "not_ok": r_bad,
            "pending": max(r_items - r_ok - r_bad, 0),
        })

    pending = max(total_items - ok - bad, 0)

    return {
        "event": {
            "id": ev.id,
            "name": ev.name,
            "date": ev.date.isoformat() if ev.date else None,
            "status": ev.status.value if hasattr(ev.status, "value") else str(ev.status),
            "created_at": ev.created_at.isoformat() if ev.created_at else None,
        },
        "totals": {
            "items": total_items,
            "ok": ok,
            "not_ok": bad,
            "pending": pending,
        },
        "roots": roots_summary,
        "tree": tree,  # utile si on veut l’inclure dans le PDF
    }


def rows_for_csv(event_id: int) -> List[Dict[str, Any]]:
    """
    Table à plat prête pour export CSV.
    Colonnes: Root, Chemin, Élément, Qté, Statut, Vérifié par, Date vérif, Parent chargé, Véhicule
    """
    ev: Event | None = db.session.get(Event, event_id)
    if not ev:
        return []

    tree = build_event_tree(event_id)

    # Récupérer tous les ids d'items et les ids des roots (pour statut véhicule)
    item_ids: List[int] = []
    root_ids: List[int] = []
    for root in tree:
        root_ids.append(root["id"])
        def rec(n: Dict[str, Any]):
            if n["type"] == "ITEM":
                item_ids.append(n["id"])
            for c in n.get("children") or []:
                rec(c)
        rec(root)

    latest_map = _latest_verifications_map(event_id, item_ids)
    parent_map = _parent_status_map(event_id, root_ids)

    rows: List[Dict[str, Any]] = []
    for node in _flatten_tree_with_path(tree):
        if node["type"] != "ITEM":
            continue

        # root name = premier élément du chemin complet (si dispo)
        root_name = ""
        if node["_path"]:
            root_name = node["_path"][0]

        status = (node.get("last_status") or "PENDING").upper()
        by = node.get("last_by") or ""
        verified_at = ""
        if node["id"] in latest_map:
            _, _, ts = latest_map[node["id"]]
            verified_at = ts.isoformat()

        # statut véhicule pris sur la racine
        parent_info = parent_map.get(node["_path_id"] if "_path_id" in node else None, {})  # precaution
        # mieux: chercher la racine correspondante dans tree
        # (on peut faire simple: rebalayer pour la racine active)
        charged = ""
        vehicle = ""
        # on déduit depuis le tree: remonter jusqu'à la racine
        charged = ""
        vehicle = ""
        # Le plus simple: re-parcourir pour trouver la racine du path
        # mais comme _path n'a pas les ids, on va plutôt récupérer via tree:
        # on crée un dict id->(charged,vehicle) depuis tree:
        # (optimisé plus haut; ici, fallback si non trouvé dans parent_map)
        # Au final, on essaye depuis le champ du root courant:
        for root in tree:
            if root["name"] == root_name:
                charged = "oui" if root.get("charged_vehicle") else "non"
                vehicle = root.get("vehicle_name") or ""
                break

        rows.append({
            "Root": root_name,
            "Chemin": " / ".join(node["_path"] + [node["name"]]),
            "Élément": node["name"],
            "Qté": node.get("quantity") or 1,
            "Statut": "OK" if status == "OK" else ("Non conforme" if status == "NOT_OK" else "En attente"),
            "Vérifié par": by,
            "Date vérif": verified_at,
            "Parent chargé": charged,
            "Véhicule": vehicle,
        })

    return rows
