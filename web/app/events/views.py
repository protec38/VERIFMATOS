from __future__ import annotations

import secrets
from typing import Any, Dict, List, Optional
from datetime import datetime

from flask import Blueprint, request, jsonify, abort
from flask_login import login_required, current_user
from sqlalchemy import select

from .. import db, socketio
from ..models import (
    Event,
    EventStatus,
    EventShareLink,
    StockNode,
    NodeType,
    VerificationRecord,
    EventNodeStatus,
    event_stock,
    Role,
)

# Deux blueprints, comme dans ton projet
bp_events = Blueprint("events_api", __name__, url_prefix="/events")
bp_public = Blueprint("public_api", __name__, url_prefix="/public")


# -------------------------------------------------
# Helpers droits
# -------------------------------------------------
def _is_manager() -> bool:
    return current_user.is_authenticated and current_user.role in (Role.ADMIN, Role.CHEF)

def _can_view() -> bool:
    return current_user.is_authenticated and current_user.role in (Role.ADMIN, Role.CHEF, Role.VIEWER)


# -------------------------------------------------
# Helpers communs
# -------------------------------------------------
def _event_or_404(event_id: int) -> Event:
    ev = db.session.get(Event, int(event_id))
    if not ev:
        abort(404, description="Événement introuvable.")
    return ev

def _event_from_token_or_404(token: str) -> Event:
    link = EventShareLink.query.filter_by(token=token, active=True).first()
    if not link or not link.event:
        abort(404, description="Lien public invalide.")
    return link.event

def _emit(event_name: str, payload: Dict[str, Any]):
    # S'il y a SocketIO, on émet localement (pas de Redis si non configuré)
    try:
        if socketio:
            socketio.emit(event_name, payload, namespace="/events")
    except Exception:
        # Ne jamais faire planter l'API pour un emit
        pass


# -------------------------------------------------
# Utils vérif + arbre
# -------------------------------------------------
def _last_verif_map(event_id: int, item_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    """
    Pour chaque item_id, récupère la dernière vérif (status/by/at/comment).
    """
    if not item_ids:
        return {}
    q = (
        VerificationRecord.query
        .filter(VerificationRecord.event_id == event_id)
        .filter(VerificationRecord.node_id.in_(item_ids))
        .order_by(VerificationRecord.node_id.asc(), VerificationRecord.created_at.desc())
    )
    out: Dict[int, Dict[str, Any]] = {}
    for r in q:
        nid = int(r.node_id)
        if nid in out:
            continue
        status_val = getattr(r, "status", None)
        status = status_val.name if hasattr(status_val, "name") else (str(status_val).upper() if status_val else "TODO")
        ts = getattr(r, "updated_at", None) or getattr(r, "created_at", None)
        out[nid] = {
            "status": status,
            "by": getattr(r, "verifier_name", None),
            "at": ts.isoformat() if ts else None,
            "comment": getattr(r, "comment", None),
        }
    return out


def _collect_desc_item_ids(root: StockNode) -> List[int]:
    """
    Renvoie tous les IDs d'ITEM sous ce noeud (récursif).
    """
    ids: List[int] = []

    def walk(n: StockNode):
        if n.type == NodeType.ITEM:
            ids.append(int(n.id))
            return
        for c in StockNode.query.filter_by(parent_id=n.id).all():
            walk(c)

    walk(root)
    return ids


def _all_descendants_ok(event_id: int, group_node: StockNode) -> bool:
    """
    True ssi tous les items descendants de group_node ont pour DERNIER status 'OK'.
    """
    if group_node.type != NodeType.GROUP:
        return False
    item_ids = _collect_desc_item_ids(group_node)
    if not item_ids:
        # pas d'items => on autorise (considéré OK)
        return True
    last = _last_verif_map(event_id, item_ids)
    for iid in item_ids:
        if (last.get(iid, {}).get("status") or "TODO") != "OK":
            return False
    return True


def _extract_expiry(n: StockNode) -> Optional[str]:
    """
    Extrait une date de péremption si disponible sur StockNode.
    On normalise en ISO string (YYYY-MM-DD).
    Couvre notamment: expiry_date = db.Date.
    """
    candidates = (
        "expiry",
        "expiry_date",
        "expires_at",
        "peremption",
        "peremption_date",
        "valid_until",
    )
    for attr in candidates:
        v = getattr(n, attr, None)
        if v:
            try:
                # datetime.date/datetime
                if hasattr(v, "isoformat"):
                    return v.isoformat()  # type: ignore[no-any-return]
                # str: renvoyer tel quel
                return str(v)
            except Exception:
                return str(v)
    return None


def _build_event_tree(event_id: int) -> List[Dict[str, Any]]:
    """
    Construit l'arbre demandé par le front (parents inclus dans l'évènement + enfants).
    Pour les ITEMs, ajoute last_status/last_by/last_at/comment et 'expiry' + 'expiry_date'.
    Pour les GROUPs, ajoute charged_vehicle / charged_vehicle_name / charged_vehicle_by.
    """
    # Racines liées à l’évènement (GROUP)
    rows = db.session.execute(
        select(StockNode).join(
            event_stock, StockNode.id == event_stock.c.node_id
        ).where(event_stock.c.event_id == event_id)
    ).scalars().all()
    roots = [n for n in rows if n.type == NodeType.GROUP]

    # Collecte items pour map des dernières vérifs
    all_items: List[StockNode] = []

    def collect_items(n: StockNode):
        if n.type == NodeType.ITEM:
            all_items.append(n)
        else:
            for c in StockNode.query.filter_by(parent_id=n.id).all():
                collect_items(c)

    for r in roots:
        collect_items(r)

    last = _last_verif_map(event_id, [i.id for i in all_items])

    def ser(n: StockNode) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "id": n.id,
            "name": n.name,
            "type": n.type.name if hasattr(n.type, "name") else str(n.type),
        }
        if n.type == NodeType.ITEM:
            info = last.get(int(n.id), {})
            exp_iso = _extract_expiry(n)
            base.update({
                "last_status": (info.get("status") or "TODO"),
                "last_by": info.get("by"),
                "last_at": info.get("at"),
                "comment": info.get("comment"),
                # ---> on expose les deux clés :
                "expiry": exp_iso,
                "expiry_date": exp_iso,
                "children": [],
            })
            return base

        # GROUP
        ch = [ser(c) for c in StockNode.query.filter_by(parent_id=n.id).all()]
        base["children"] = ch
        ens = EventNodeStatus.query.filter_by(event_id=event_id, node_id=n.id).first()
        if ens:
            base["charged_vehicle"] = getattr(ens, "charged_vehicle", None)
            if hasattr(ens, "charged_vehicle_name"):
                base["charged_vehicle_name"] = getattr(ens, "charged_vehicle_name", None)
            # Nom affiché côté UI : "chargé par ..."
            base["charged_vehicle_by"] = getattr(ens, "verifier_name", None)
        else:
            base["charged_vehicle"] = None
            base["charged_vehicle_name"] = None
            base["charged_vehicle_by"] = None
        return base

    return [ser(r) for r in roots]


# -------------------------------------------------
# Routes internes (manager/chef)
# -------------------------------------------------
@bp_events.post("/")
@bp_events.post("")  # accepte /events ET /events/
@login_required
def create_event():
    if not _is_manager():
        abort(403)

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    date_raw = (data.get("date") or "").strip() or None
    root_ids = data.get("root_ids") or data.get("root_node_ids") or []

    if not name or not isinstance(root_ids, list) or not root_ids:
        abort(400, description="name et root_ids (liste non vide) requis.")

    # date optionnelle
    dt = None
    if date_raw:
        try:
            dt = datetime.fromisoformat(date_raw).date()
        except Exception:
            abort(400, description="date invalide (YYYY-MM-DD).")

    # created_by : utiliser *_id si la FK s'appelle comme ça (évite l’erreur ORM)
    ev = Event(
        name=name,
        date=dt,
        status=EventStatus.OPEN,
        created_by_id=current_user.id  # <--- important
    )
    db.session.add(ev)
    db.session.flush()

    seen = set()
    for nid in root_ids:
        try:
            nid_i = int(nid)
        except Exception:
            abort(400, description=f"root_id invalide: {nid}")
        if nid_i in seen:
            continue
        seen.add(nid_i)
        node = db.session.get(StockNode, nid_i)
        if not node:
            abort(400, description=f"StockNode {nid_i} introuvable.")
        if node.type != NodeType.GROUP:
            abort(400, description=f"StockNode {nid_i} doit être de type GROUP.")
        db.session.execute(event_stock.insert().values(event_id=ev.id, node_id=nid_i))

    db.session.commit()
    return jsonify({"ok": True, "id": ev.id, "url": f"/events/{ev.id}"}), 201


@bp_events.get("/list")
@login_required
def list_events():
    if not _can_view():
        abort(403)
    evs = Event.query.order_by(Event.created_at.desc()).all()
    return jsonify([
        {
            "id": e.id,
            "name": e.name,
            "status": getattr(e.status, "name", str(e.status)).upper(),
            "date": str(e.date) if e.date else None,
        }
        for e in evs
    ])


@bp_events.get("/<int:event_id>/tree")
@login_required
def event_tree(event_id: int):
    if not _can_view():
        abort(403)
    ev = _event_or_404(event_id)
    tree = _build_event_tree(ev.id)
    return jsonify(tree)


@bp_events.post("/<int:event_id>/verify")
@login_required
def event_verify(event_id: int):
    if not _is_manager():
        abort(403)
    ev = _event_or_404(event_id)
    if ev.status != EventStatus.OPEN:
        return jsonify({"error": "Événement fermé — vérifications verrouillées."}), 403

    payload = request.get_json(silent=True) or {}
    node_id = int(payload.get("node_id") or 0)
    status = (payload.get("status") or "").upper()  # "OK" | "NOT_OK" | "TODO"
    verifier_name = (payload.get("verifier_name") or current_user.username or "").strip()
    comment = (payload.get("comment") or "").strip() or None

    if not node_id or status not in ("OK", "NOT_OK", "TODO"):
        abort(400, description="Paramètres invalides (node_id, status).")

    node = db.session.get(StockNode, node_id)
    if not node or node.type != NodeType.ITEM:
        abort(404, description="Item introuvable.")

    rec = VerificationRecord(
        event_id=ev.id,
        node_id=node.id,
        status=status,
        verifier_name=verifier_name or None,
        comment=comment,
    )
    db.session.add(rec)
    db.session.commit()

    _emit("event_update", {
        "type": "item_verified",
        "event_id": ev.id,
        "node_id": node.id,
        "status": status,
        "verifier_name": verifier_name or None,
        "comment": comment,
    })

    return jsonify({"ok": True})


@bp_events.post("/<int:event_id>/parent-status")
@login_required
def event_parent_charged(event_id: int):
    """
    Marque un parent (GROUP) comme 'chargé'.
    Autorisé uniquement si TOUT le sous-arbre est OK (blocage côté serveur).
    """
    if not _is_manager():
        abort(403)
    ev = _event_or_404(event_id)
    if ev.status != EventStatus.OPEN:
        return jsonify({"error": "Événement fermé — vérifications verrouillées."}), 403

    payload = request.get_json(silent=True) or {}
    node_id = int(payload.get("node_id") or 0)
    charged_vehicle = bool(payload.get("charged_vehicle"))
    operator_name = (payload.get("operator_name") or current_user.username or "").strip()
    vehicle_name = (payload.get("vehicle_name") or "").strip() or None

    if not node_id:
        abort(400, description="node_id requis.")
    node = db.session.get(StockNode, node_id)
    if not node or node.type != NodeType.GROUP:
        abort(404, description="Parent introuvable ou non GROUP.")

    # Blocage serveur si tout n'est pas OK
    if charged_vehicle and not _all_descendants_ok(ev.id, node):
        abort(400, description="Impossible de charger : tous les éléments ne sont pas OK.")

    ens = EventNodeStatus.query.filter_by(event_id=ev.id, node_id=node.id).first() \
        or EventNodeStatus(event_id=ev.id, node_id=node.id)
    ens.charged_vehicle = charged_vehicle
    if hasattr(ens, "charged_vehicle_name"):
        ens.charged_vehicle_name = vehicle_name if charged_vehicle else None
    # On stocke le nom (côté UI : 'Chargé par ...')
    try:
        ens.verifier_name = operator_name or None
    except Exception:
        pass
    ens.updated_at = datetime.utcnow()

    db.session.add(ens)
    db.session.commit()

    out = {
        "type": "parent_charged",
        "event_id": ev.id,
        "node_id": node.id,
        "charged": charged_vehicle,
        "vehicle_name": getattr(ens, "charged_vehicle_name", None),
        "by": getattr(ens, "verifier_name", None),
    }
    _emit("event_update", out)

    return jsonify({"ok": True, **out})


@bp_events.patch("/<int:event_id>/status")
@login_required
def event_set_status(event_id: int):
    if not _is_manager():
        abort(403)
    ev = _event_or_404(event_id)

    data = request.get_json(silent=True) or {}
    status_raw = (data.get("status") or "").upper()
    if status_raw not in ("OPEN", "CLOSED"):
        abort(400, description="Statut invalide (OPEN | CLOSED).")

    ev.status = EventStatus.OPEN if status_raw == "OPEN" else EventStatus.CLOSED
    ev.updated_at = datetime.utcnow()
    db.session.commit()

    _emit("event_update", {"type": "status", "event_id": ev.id, "status": ev.status.name})
    return jsonify({"ok": True, "status": ev.status.name})


@bp_events.post("/<int:event_id>/share-link")
@login_required
def create_public_share_link(event_id: int):
    if not _is_manager():
        abort(403)
    ev = _event_or_404(event_id)

    EventShareLink.query.filter_by(event_id=ev.id, active=True).update({"active": False})

    token = secrets.token_urlsafe(24)
    link = EventShareLink(event_id=ev.id, token=token, active=True)
    db.session.add(link)
    db.session.commit()

    return jsonify({"ok": True, "token": token, "url": f"/public/event/{token}"})


@bp_events.post("/<int:event_id>/delete")
@login_required
def delete_event(event_id: int):
    if not _is_manager():
        abort(403)
    ev = _event_or_404(event_id)

    VerificationRecord.query.filter_by(event_id=ev.id).delete()
    EventNodeStatus.query.filter_by(event_id=ev.id).delete()
    EventShareLink.query.filter_by(event_id=ev.id).delete()
    db.session.execute(event_stock.delete().where(event_stock.c.event_id == ev.id))
    db.session.delete(ev)
    db.session.commit()

    return jsonify({"ok": True})


# -------------------------------------------------
# Public routes (secouristes)
# -------------------------------------------------
@bp_public.get("/event/<token>/tree")
def public_event_tree(token: str):
    ev = _event_from_token_or_404(token)
    tree = _build_event_tree(ev.id)
    return jsonify(tree)


@bp_public.post("/event/<token>/verify")
def public_verify(token: str):
    ev = _event_from_token_or_404(token)
    if ev.status != EventStatus.OPEN:
        return jsonify({"error": "Événement fermé — vérifications verrouillées."}), 403

    payload = request.get_json(silent=True) or {}
    node_id = int(payload.get("node_id") or 0)
    status = (payload.get("status") or "").upper()  # "OK" | "NOT_OK" | "TODO"
    verifier_name = (payload.get("verifier_name") or "").strip()
    comment = (payload.get("comment") or "").strip() or None

    if not node_id or status not in ("OK", "NOT_OK", "TODO"):
        abort(400, description="Paramètres invalides (node_id, status).")

    node = db.session.get(StockNode, node_id)
    if not node or node.type != NodeType.ITEM:
        abort(404, description="Élément introuvable ou non vérifiable.")

    rec = VerificationRecord(
        event_id=ev.id,
        node_id=node.id,
        status=status,
        verifier_name=verifier_name or None,
        comment=comment,
    )
    db.session.add(rec)
    db.session.commit()

    _emit("event_update", {
        "type": "public_verify",
        "event_id": ev.id,
        "node_id": node.id,
        "status": status,
        "verifier_name": verifier_name or None,
        "comment": comment,
    })
    return jsonify({"ok": True})


@bp_public.post("/event/<token>/charge")
def public_parent_charge(token: str):
    """
    Marque un parent (GROUP) comme 'chargé' côté public.
    Autorisé uniquement si tout le sous-arbre est OK (sécurité serveur).
    """
    ev = _event_from_token_or_404(token)
    if ev.status != EventStatus.OPEN:
        return jsonify({"error": "Événement fermé — vérifications verrouillées."}), 403

    payload = request.get_json(silent=True) or {}
    node_id = int(payload.get("node_id") or 0)
    charged_vehicle = bool(payload.get("charged_vehicle", True))
    operator_name = (payload.get("operator_name") or "").strip()
    vehicle_name = (payload.get("vehicle_name") or "").strip() or None

    if not node_id:
        abort(400, description="node_id requis.")
    node = db.session.get(StockNode, node_id)
    if not node or node.type != NodeType.GROUP:
        abort(404, description="Parent introuvable ou non GROUP.")

    # Blocage serveur si tout n'est pas OK
    if charged_vehicle and not _all_descendants_ok(ev.id, node):
        abort(400, description="Impossible de charger : tous les éléments ne sont pas OK.")

    ens = EventNodeStatus.query.filter_by(event_id=ev.id, node_id=node.id).first() \
        or EventNodeStatus(event_id=ev.id, node_id=node.id)
    ens.charged_vehicle = charged_vehicle
    if hasattr(ens, "charged_vehicle_name"):
        ens.charged_vehicle_name = vehicle_name if charged_vehicle else None
    # on stocke le nom du secouriste qui a chargé
    try:
        ens.verifier_name = operator_name or None
    except Exception:
        pass
    ens.updated_at = datetime.utcnow()

    db.session.add(ens)
    db.session.commit()

    out = {
        "type": "parent_charged",
        "event_id": ev.id,
        "node_id": node.id,
        "charged": charged_vehicle,
        "vehicle_name": getattr(ens, "charged_vehicle_name", None),
        "by": getattr(ens, "verifier_name", None),
    }
    _emit("event_update", out)

    return jsonify({"ok": True, **out})
