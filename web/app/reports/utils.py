# app/reports/utils.py — utilitaires de reporting / exports
from __future__ import annotations
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime

from sqlalchemy import func, and_, select
from sqlalchemy.orm import aliased

from .. import db
from ..models import (
    Event,
    StockNode,
    VerificationRecord,
    EventNodeStatus,
)
# On ré-exporte build_event_tree pour compat. avec stats/views.py
from ..tree_query import build_event_tree  # noqa: F401

StatusTuple = Tuple[Optional[str], Optional[str], Optional[datetime]]
# (status_normalisé, verifier_name, created_at)


# ---------- Outils internes ----------

def _norm_status(s: Optional[str]) -> Optional[str]:
    """
    Normalise un statut en 'OK' / 'NOT_OK' ou None.
    Tout autre valeur (ex: 'PENDING', 'RESET', etc.) => None.
    """
    if not s:
        return None
    s = s.strip().upper()
    if s in ("OK", "NOT_OK"):
        return s
    return None


def last_status_by_node(event_id: int) -> Dict[int, StatusTuple]:
    """
    Retourne, pour un évènement, le dernier statut par node_id sous la forme:
      { node_id: (status_normalisé, verifier_name, created_at) }
    Si le dernier enregistrement n'est ni OK ni NOT_OK => status None.
    """
    # Sous-requête: dernière date par node_id
    sub = (
        db.session.query(
            VerificationRecord.node_id.label("node_id"),
            func.max(VerificationRecord.created_at).label("max_ts"),
        )
        .filter(VerificationRecord.event_id == event_id)
        .group_by(VerificationRecord.node_id)
        .subquery()
    )

    vr_alias = aliased(VerificationRecord)

    q = (
        db.session.query(
            vr_alias.node_id,
            vr_alias.status,
            vr_alias.verifier_name,
            vr_alias.created_at,
        )
        .join(
            sub,
            and_(
                vr_alias.node_id == sub.c.node_id,
                vr_alias.created_at == sub.c.max_ts,
            ),
        )
        .filter(vr_alias.event_id == event_id)
    )

    out: Dict[int, StatusTuple] = {}
    for node_id, status, by, ts in q.all():
        out[int(node_id)] = (_norm_status(status), by, ts)
    return out


# ---------- Exposés pour les vues ----------

def latest_verifications(event_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Dernières vérifications (desc), utile pour un widget d'historique récent.
    """
    q = (
        db.session.query(
            VerificationRecord.id,
            VerificationRecord.node_id,
            VerificationRecord.status,
            VerificationRecord.verifier_name,
            VerificationRecord.created_at,
            StockNode.name.label("node_name"),
        )
        .join(StockNode, StockNode.id == VerificationRecord.node_id)
        .filter(VerificationRecord.event_id == event_id)
        .order_by(VerificationRecord.created_at.desc())
        .limit(limit)
    )

    rows: List[Dict[str, Any]] = []
    for rid, node_id, status, by, ts, node_name in q.all():
        rows.append(
            {
                "id": rid,
                "node_id": node_id,
                "node_name": node_name,
                "status": _norm_status(status),
                "raw_status": status,  # pour debug si besoin
                "by": by,
                "at": ts,
            }
        )
    return rows


def compute_summary(event_id: int) -> Dict[str, Any]:
    """
    Petit résumé global + par parent racine (si disponible).
    """
    # Dernier statut par item
    last = last_status_by_node(event_id)

    # Lister les items de l'évènement (via les parents liés)
    # On considère “item” = StockNode.type == 'ITEM' (côté base actuelle).
    # La requête passe par les nodes présents dans l’arbre de l’évènement.
    # Ici on récupère tous les nodes et on filtrera côté Python sur type.
    # (build_event_tree fait le job complet, mais ici on veut un résumé rapide SQL + last)
    nodes_q = (
        db.session.query(StockNode.id, StockNode.name, StockNode.type, StockNode.parent_id, StockNode.level)
        .join(
            # On passe par les parents racines liés à l'évènement via EventStock (si présent dans la base).
            # Si ta base n'a pas de table d'association accessible ici, ce résumé restera global.
            # On se contente donc de prendre tous les nœuds; le détail fin sera dans l'export CSV.
            # NOTE: Si tu as la table event_stock, tu peux améliorer ce bloc avec un join sur elle.
            # Pour rester “safe” et compatible, on ne met pas ce join ici.
            StockNode, StockNode.id == StockNode.id  # no-op, évite l'erreur de JOIN vide
        )
    )

    total_items = ok = bad = 0
    for nid, _nm, typ, _pid, _lvl in nodes_q.all():
        if (typ or "").upper() != "ITEM":
            continue
        total_items += 1
        st = last.get(nid, (None, None, None))[0]
        if st == "OK":
            ok += 1
        elif st == "NOT_OK":
            bad += 1

    wait = max(total_items - ok - bad, 0)

    # Parents “chargés” (si EventNodeStatus existe pour l'évènement)
    parents_q = (
        db.session.query(
            EventNodeStatus.node_id,
            EventNodeStatus.charged_vehicle,
            EventNodeStatus.vehicle_label,
            StockNode.name.label("node_name"),
        )
        .join(StockNode, StockNode.id == EventNodeStatus.node_id)
        .filter(EventNodeStatus.event_id == event_id)
    )
    parents = [
        {
            "node_id": row.node_id,
            "name": row.node_name,
            "charged": bool(row.charged_vehicle),
            "vehicle": row.vehicle_label,
        }
        for row in parents_q.all()
    ]

    return {
        "event_id": event_id,
        "totals": {"total": total_items, "ok": ok, "bad": bad, "wait": wait},
        "parents": parents,  # liste indicative; l’état couleur exact reste déterminé par l’arbre
    }


def rows_for_csv(event_id: int) -> List[Dict[str, Any]]:
    """
    Prépare des lignes “plates” pour CSV / Excel.
    Colonnes: node_id, chemin, nom, type, quantity, dernier_statut, verificateur, date, vehicule(parent)
    NB: On remonte le véhicule porté par le parent direct si EventNodeStatus est renseigné.
    """
    # On va récupérer:
    #  - les nœuds
    #  - leur parent (pour remonter un libellé véhicule éventuel)
    #  - le dernier statut (via subquery)
    sub_last = (
        db.session.query(
            VerificationRecord.node_id.label("node_id"),
            func.max(VerificationRecord.created_at).label("max_ts"),
        )
        .filter(VerificationRecord.event_id == event_id)
        .group_by(VerificationRecord.node_id)
        .subquery()
    )
    vr = aliased(VerificationRecord)

    q = (
        db.session.query(
            StockNode.id.label("node_id"),
            StockNode.name.label("node_name"),
            StockNode.type.label("node_type"),
            StockNode.quantity.label("qty"),
            StockNode.parent_id.label("parent_id"),
            vr.status.label("last_status"),
            vr.verifier_name.label("last_by"),
            vr.created_at.label("last_at"),
        )
        .outerjoin(sub_last, sub_last.c.node_id == StockNode.id)
        .outerjoin(
            vr,
            and_(
                vr.node_id == sub_last.c.node_id,
                vr.created_at == sub_last.c.max_ts,
                vr.event_id == event_id,
            ),
        )
    )

    # Charger une map parent -> (charged_vehicle, vehicle_label)
    ens_map: Dict[int, Dict[str, Any]] = {}
    for row in (
        db.session.query(
            EventNodeStatus.node_id,
            EventNodeStatus.charged_vehicle,
            EventNodeStatus.vehicle_label,
        )
        .filter(EventNodeStatus.event_id == event_id)
        .all()
    ):
        ens_map[int(row.node_id)] = {
            "charged": bool(row.charged_vehicle),
            "vehicle": row.vehicle_label,
        }

    # Pour construire un “chemin” simple, on remontera les parents en mémoire.
    # On récupère une mini map id -> (name, parent_id)
    all_nodes = {
        int(n.id): (n.name, n.parent_id)
        for n in db.session.query(StockNode.id, StockNode.name, StockNode.parent_id).all()
    }

    def build_path(nid: Optional[int]) -> str:
        path: List[str] = []
        cur = nid
        seen = set()
        while cur and cur in all_nodes and cur not in seen:
            seen.add(cur)
            nm, parent_id = all_nodes[cur]
            path.append(nm)
            cur = parent_id
        return " / ".join(reversed(path))

    rows: List[Dict[str, Any]] = []
    for r in q.all():
        # Véhicule pris sur le parent direct s’il y a une info EventNodeStatus
        veh: Optional[str] = None
        if r.parent_id and int(r.parent_id) in ens_map:
            veh = ens_map[int(r.parent_id)].get("vehicle")

        rows.append(
            {
                "node_id": int(r.node_id),
                "path": build_path(int(r.node_id)),
                "name": r.node_name,
                "type": (r.node_type or "").upper(),
                "quantity": r.qty,
                "status": _norm_status(r.last_status),
                "status_raw": r.last_status,
                "verifier": r.last_by,
                "timestamp": r.last_at,
                "vehicle": veh,
            }
        )

    # Optionnel: trier par chemin puis nom
    rows.sort(key=lambda x: (x["path"], x["name"]))
    return rows
