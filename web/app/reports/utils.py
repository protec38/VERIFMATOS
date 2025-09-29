# app/reports/utils.py
from __future__ import annotations
from typing import Any, Dict, List, Tuple

from .. import db
from ..models import VerificationRecord, StockNode
from ..tree_query import build_event_tree as _build_event_tree


# Expose la fonction pour compatibilité avec les imports existants
def build_event_tree(event_id: int) -> List[Dict[str, Any]]:
    return _build_event_tree(event_id)


def compute_summary(roots: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Résumé global + par parent racine.
    Compatible avec l’existant, pas d’ItemStatus.
    """
    summary: Dict[str, Any] = {
        "total_items": 0,
        "ok": 0,
        "not_ok": 0,
        "pending": 0,
        "parents": [],  # [{name, total, ok, not_ok, pending, charged_vehicle, vehicle_name}]
    }

    def stats_for_group(g: Dict[str, Any]) -> Tuple[int, int, int, int]:
        total = ok = not_ok = pending = 0

        def rec(n: Dict[str, Any]):
            nonlocal total, ok, not_ok, pending
            if n.get("type") == "ITEM":
                total += 1
                st = (n.get("last_status") or "PENDING").upper()
                if st == "OK":
                    ok += 1
                elif st == "NOT_OK":
                    not_ok += 1
                else:
                    pending += 1
            for c in n.get("children", []) or []:
                rec(c)

        rec(g)
        return total, ok, not_ok, pending

    for r in roots:
        t, o, b, p = stats_for_group(r)
        summary["total_items"] += t
        summary["ok"] += o
        summary["not_ok"] += b
        summary["pending"] += p
        summary["parents"].append({
            "name": r.get("name", ""),
            "charged_vehicle": bool(r.get("charged_vehicle")),
            "vehicle_name": r.get("vehicle_name") or "",
            "total": t,
            "ok": o,
            "not_ok": b,
            "pending": p,
        })

    return summary


def latest_verifications(event_id: int, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Renvoie les dernières vérifications pour un évènement, avec le nom de l’item.
    Utilisé par certains tableaux de bord / stats.
    """
    q = (
        db.session.query(VerificationRecord, StockNode.name)
        .join(StockNode, StockNode.id == VerificationRecord.node_id)
        .filter(VerificationRecord.event_id == event_id)
        .order_by(VerificationRecord.created_at.desc())
        .limit(limit)
    )
    out: List[Dict[str, Any]] = []
    for rec, node_name in q.all():
        out.append({
            "id": rec.id,
            "node_id": rec.node_id,
            "node_name": node_name,
            "status": rec.status,                 # "OK" | "NOT_OK"
            "verifier_name": rec.verifier_name or "",
            "created_at": rec.created_at.isoformat() if rec.created_at else None,
        })
    return out


# Optionnel : utilitaire parfois importé ailleurs
def rows_for_csv(roots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Aplatis les items d’un arbre en lignes prêtes pour CSV.
    """
    rows: List[Dict[str, Any]] = []

    def rec(n: Dict[str, Any], path: List[str]):
        cur_path = path + [n["name"]]
        if n.get("type") == "ITEM":
            rows.append({
                "parent_name": cur_path[-2] if len(cur_path) >= 2 else "",
                "path": " / ".join(cur_path[:-1]),
                "name": n["name"],
                "quantity": n.get("quantity", 1),
                "status": n.get("last_status", "PENDING"),
                "by": n.get("last_by", ""),
            })
        else:
            for c in n.get("children", []) or []:
                rec(c, cur_path)

    for r in roots:
        rec(r, [])
    return rows
