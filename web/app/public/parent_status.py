from __future__ import annotations

from flask import Blueprint, request, jsonify, abort
from sqlalchemy.orm import load_only

from .. import db
from ..models import (
    Event,
    EventStatus,
    EventShareLink,
    EventNodeStatus,
)
from ..tree_query import build_event_tree

bp = Blueprint("public_parent", __name__, url_prefix="/public/event")


# ---------- Helpers ----------
def _event_by_token_or_404(token: str) -> Event:
    link = (
        EventShareLink.query.options(load_only(EventShareLink.event_id, EventShareLink.active))
        .filter_by(token=token, active=True)
        .first()
    )
    if not link:
        abort(404, description="Lien public introuvable ou inactif.")
    ev = db.session.get(Event, link.event_id) or abort(404)
    if ev.status != EventStatus.OPEN:
        abort(403, description="Événement fermé.")
    return ev


def _find_node_in_tree(tree: list[dict], node_id: int) -> dict | None:
    stack = list(tree or [])
    while stack:
        n = stack.pop()
        if n.get("id") == node_id:
            return n
        stack.extend(n.get("children") or [])
    return None


def _all_items_ok(group_node: dict) -> bool:
    """Vrai s'il existe au moins un item descendant ET que tous sont OK."""
    has_item = False

    def rec(n: dict) -> bool:
        nonlocal has_item
        t = (n.get("type") or "").upper()
        if t == "ITEM":
            has_item = True
            return (n.get("last_status") or "").upper() == "OK"
        return all(rec(c) for c in n.get("children") or [])

    ok = rec(group_node)
    return has_item and ok


# ---------- Public API ----------
@bp.post("/<token>/parent-status")
def public_parent_status(token: str):
    """
    Marque un parent (GROUP) comme 'chargé dans véhicule' côté accès public.
    Attend JSON:
      - node_id: int (id du parent)
      - charged_vehicle: bool
      - verifier_name: str (obligatoire)
      - vehicle_label: str (obligatoire si charged_vehicle = true)
    Règles:
      - on ne peut marquer 'chargé' que si TOUT le contenu du parent est OK.
    """
    data = request.get_json(silent=True) or {}
    node_id = int(data.get("node_id") or 0)
    charged = bool(data.get("charged_vehicle"))
    verifier_name = (data.get("verifier_name") or "").strip()
    vehicle_label = (data.get("vehicle_label") or "").strip()

    if not node_id:
        abort(400, description="Paramètre node_id requis.")
    if not verifier_name:
        abort(400, description="Paramètre verifier_name requis.")

    ev = _event_by_token_or_404(token)

    # Vérifie que le nœud appartient bien à l'événement et que c'est un GROUP
    tree = build_event_tree(ev.id)
    node = _find_node_in_tree(tree, node_id)
    if not node:
        abort(404, description="Nœud introuvable pour cet événement.")
    if (node.get("type") or "").upper() != "GROUP":
        abort(400, description="Seuls les parents (GROUP) peuvent être marqués chargés.")

    # Si on veut le passer à 'chargé', on exige que tout soit OK + véhicule saisi
    if charged:
        if not _all_items_ok(node):
            abort(400, description="Ce parent n’est pas entièrement OK.")
        if not vehicle_label:
            abort(400, description="Indique le véhicule (ex: VSAV 1).")

    # Upsert EventNodeStatus
    ens = (
        EventNodeStatus.query.filter_by(event_id=ev.id, node_id=node_id).first()
        or EventNodeStatus(event_id=ev.id, node_id=node_id)
    )
    ens.charged_vehicle = charged

    # Colonne facultative: on n'échoue pas si elle n'existe pas encore dans ton modèle/DB
    if hasattr(ens, "vehicle_label"):
        ens.vehicle_label = vehicle_label if charged else None

    db.session.add(ens)
    db.session.commit()

    return jsonify({
        "ok": True,
        "node_id": node_id,
        "charged_vehicle": ens.charged_vehicle,
        "vehicle_label": getattr(ens, "vehicle_label", None),
    })
