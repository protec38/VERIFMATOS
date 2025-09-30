# app/verify/views.py
from __future__ import annotations
from typing import Any, Dict, List, Optional
from flask import Blueprint, jsonify, request, abort, render_template
from .. import db
from ..models import (
    Event,
    EventStatus,
    EventShareLink,
    VerificationRecord,
    StockNode,
    ItemStatus,
    IssueCode,
    EventNodeStatus,
    NodeType,
)
from ..tree_query import build_event_tree

bp = Blueprint("verify", __name__)

# -------------------- Helpers --------------------

def _json() -> Dict[str, Any]:
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        abort(400, description="Payload JSON attendu")
    return data

def _sanitize_tree(node: Dict[str, Any]) -> Dict[str, Any]:
    """
    Le résultat de build_event_tree est déjà JSON-safe.
    On se contente ici de retourner tel quel pour la page publique.
    """
    return node

def _find_node(tree: List[dict], node_id: int) -> Optional[dict]:
    """Retrouve un nœud dans l'arbre JSON (par id)."""
    for r in tree:
        if r.get("id") == node_id:
            return r
        stack = list(r.get("children", []))
        while stack:
            n = stack.pop()
            if n.get("id") == node_id:
                return n
            stack.extend(n.get("children", []))
    return None

def _node_in_tree(tree: List[dict], node_id: int) -> bool:
    return _find_node(tree, node_id) is not None

# -------------------- Pages publiques --------------------

@bp.get("/public/event/<token>")
def public_event_page(token: str):
    """
    Page publique utilisée par les secouristes (pas besoin de compte).
    Affiche l'arbre (parents + items) attaché à l'événement identifié par <token>.
    """
    link = EventShareLink.query.filter_by(token=token, active=True).first()
    if not link or not link.event:
        abort(404)
    ev = link.event
    tree: List[dict] = build_event_tree(ev.id) or []
    tree = [_sanitize_tree(n) for n in tree]
    return render_template("public_event.html", token=token, event=ev, tree=tree)

@bp.get("/public/event/<token>/tree")
def public_event_tree(token: str):
    """
    Endpoint JSON pour rafraîchir l'arbre côté client.
    """
    link = EventShareLink.query.filter_by(token=token, active=True).first()
    if not link or not link.event:
        abort(404)
    ev = link.event
    tree: List[dict] = build_event_tree(ev.id) or []
    tree = [_sanitize_tree(n) for n in tree]
    return jsonify(tree)

# -------------------- Vérification publique (ITEM) --------------------

@bp.post("/public/event/<token>/verify")
def public_verify_item(token: str):
    """
    Enregistre une vérification sur un ITEM (feuille) pour l'événement.
    Accepte:
      - node_id (int)
      - status: "ok" | "not_ok" | "todo"
      - verifier_name (str)
      - comment (str, optionnel)
      - (si not_ok) issue_code: "broken" | "missing" | "other"
      - (optionnels) observed_qty (int >=0), missing_qty (int >=0)
    """
    link = EventShareLink.query.filter_by(token=token, active=True).first()
    if not link or not link.event:
        abort(404)
    ev = link.event
    if ev.status != EventStatus.OPEN:
        abort(403, description="Événement fermé")

    data = _json()

    # --- node_id ---
    try:
        node_id = int(data.get("node_id") or 0)
    except Exception:
        abort(400, description="node_id invalide")

    # --- status ---
    status_map = {"ok": ItemStatus.OK, "not_ok": ItemStatus.NOT_OK, "todo": ItemStatus.TODO}
    status_str = (data.get("status") or "").strip().lower()
    if status_str not in status_map:
        abort(400, description="status doit être ok | not_ok | todo")
    status = status_map[status_str]

    # --- verifier_name ---
    verifier_name = (data.get("verifier_name") or "").strip()
    if not verifier_name:
        abort(400, description="Nom du vérificateur requis")

    # --- récup item ---
    node = db.session.get(StockNode, node_id)
    if not node:
        abort(404, description="Item introuvable")
    # On ne vérifie que les feuilles (ITEM)
    if getattr(node.type, "name", None) != "ITEM":
        abort(400, description="Seuls les items (feuilles) sont vérifiables")

    # --- champs optionnels + validations ---
    comment = (data.get("comment") or "").strip() or None

    issue_code = None
    observed_qty = None
    missing_qty = None

    if status == ItemStatus.NOT_OK:
        code_str = (data.get("issue_code") or "").strip().lower()
        code_map = {"broken": IssueCode.BROKEN, "missing": IssueCode.MISSING, "other": IssueCode.OTHER}
        if code_str not in code_map:
            abort(400, description="issue_code requis (broken | missing | other)")
        issue_code = code_map[code_str]

        def as_int(x):
            try:
                if x is None or x == "":
                    return None
                return int(x)
            except Exception:
                abort(400, description="observed_qty / missing_qty doivent être des entiers")
        observed_qty = as_int(data.get("observed_qty"))
        missing_qty = as_int(data.get("missing_qty"))

        # bornes minimales
        if observed_qty is not None and observed_qty < 0:
            abort(400, description="observed_qty doit être ≥ 0")
        if missing_qty is not None and missing_qty < 0:
            abort(400, description="missing_qty doit être ≥ 0")

        # cohérence simple avec la quantité cible si connue
        target = node.quantity or 0
        if target > 0:
            if observed_qty is not None and observed_qty > target:
                abort(400, description="observed_qty ne peut pas dépasser la quantité cible")
            if missing_qty is not None and missing_qty > target:
                abort(400, description="missing_qty ne peut pas dépasser la quantité cible")

    # --- création en base ---
    rec = VerificationRecord(
        event_id=ev.id,
        node_id=node_id,
        status=status,
        verifier_name=verifier_name,
        comment=comment,
        issue_code=issue_code,
        observed_qty=observed_qty,
        missing_qty=missing_qty,
    )
    db.session.add(rec)
    db.session.commit()

    return jsonify({"ok": True, "record_id": rec.id})

# -------------------- Chargement d'un parent (GROUP) --------------------

@bp.post("/public/event/<token>/charge")
def public_charge_parent(token: str):
    """
    Marque un parent (GROUP) comme 'chargé' pour l'événement <token>,
    après vérification que TOUS ses items descendants sont OK.
    Données:
      - node_id (int) : id du parent GROUP
      - vehicle_name (str) : nom du véhicule saisi par l'opérateur
      - operator_name (str, optionnel) : si présent, journalise le nom (sinon utiliser côté UI le même que verifier_name)
    Effet:
      - upsert EventNodeStatus(event_id, node_id) avec:
        charged_vehicle=True, comment="Véhicule: <vehicle_name>"
    """
    link = EventShareLink.query.filter_by(token=token, active=True).first()
    if not link or not link.event:
        abort(404)
    ev = link.event
    if ev.status != EventStatus.OPEN:
        abort(403, description="Événement fermé")

    data = _json()
    try:
        node_id = int(data.get("node_id") or 0)
    except Exception:
        abort(400, description="node_id invalide")

    vehicle_name = (data.get("vehicle_name") or "").strip()
    if not vehicle_name:
        abort(400, description="Nom du véhicule requis")

    operator_name = (data.get("operator_name") or "").strip() or None

    node = db.session.get(StockNode, node_id)
    if not node:
        abort(404, description="Parent introuvable")
    if node.type != NodeType.GROUP:
        abort(400, description="Seuls les parents (GROUP) peuvent être chargés")

    # Vérifie que ce node appartient bien à l'arbre de l'événement
    tree: List[dict] = build_event_tree(ev.id) or []
    if not _node_in_tree(tree, node_id):
        abort(400, description="Le parent ne fait pas partie de cet événement")

    # Vérifie l'état 'complete' du parent (tous les items OK)
    node_json = _find_node(tree, node_id)
    if not node_json:
        abort(404, description="Parent introuvable dans l'arbre")
    if not node_json.get("complete", False):
        abort(400, description="Impossible de charger: tous les items ne sont pas OK")

    # Upsert EventNodeStatus
    ens = (
        EventNodeStatus.query
        .filter_by(event_id=ev.id, node_id=node_id)
        .first()
    )
    if not ens:
        ens = EventNodeStatus(event_id=ev.id, node_id=node_id)

    ens.charged_vehicle = True
    # On stocke le nom du véhicule dans comment (pour éviter une migration maintenant)
    # Format simple et lisible:
    comment_parts = [f"Véhicule: {vehicle_name}"]
    if operator_name:
        comment_parts.append(f"Par: {operator_name}")
    ens.comment = " | ".join(comment_parts)

    db.session.add(ens)
    db.session.commit()

    return jsonify({
        "ok": True,
        "event_id": ev.id,
        "node_id": node_id,
        "charged_vehicle": True,
        "comment": ens.comment,
        "updated_at": ens.updated_at.isoformat() if ens.updated_at else None,
    })
