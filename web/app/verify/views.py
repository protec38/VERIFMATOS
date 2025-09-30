# app/verify/views.py
from __future__ import annotations
from typing import Any, Dict, List
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

# -------------------- Vérification publique --------------------

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
