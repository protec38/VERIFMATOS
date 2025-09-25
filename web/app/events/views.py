# app/events/views.py — API JSON pour les événements (AUCUN HTML ici)
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Iterable
from flask import Blueprint, jsonify, request, abort, current_app
from flask_login import login_required, current_user

from .. import db, socketio
from ..models import (
    Event,
    EventStatus,
    Role,
    StockNode,
    NodeType,
    event_stock,             # Table d'association événement <-> parents racine
    EventShareLink,          # Table des liens partagés
    EventNodeStatus,         # Statut par parent (ex: chargé véhicule)
    VerificationRecord,      # Enregistrements de vérification des items
)
from ..tree_query import build_event_tree

bp = Blueprint("events", __name__)  # enregistré dans create_app() sans prefix

# -------------------------
# Helpers permissions
# -------------------------
def require_can_manage_event(ev: Event | None = None) -> None:
    """Autorise ADMIN et CHEF. Si ev fourni, requiert aussi OPEN pour modifier."""
    if not current_user.is_authenticated:
        abort(401)
    if current_user.role not in (Role.ADMIN, Role.CHEF):
        abort(403)
    if ev is not None and ev.status != EventStatus.OPEN:
        abort(403)

def require_can_view_event(ev: Event) -> None:
    if not current_user.is_authenticated:
        abort(401)
    if current_user.role not in (Role.ADMIN, Role.CHEF, Role.VIEWER):
        abort(403)

# -------------------------
# Utilitaires JSON
# -------------------------
def _normalize_ids(value) -> List[int]:
    """Accepte liste, string CSV, ou None → liste d'int unique triée."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw = value
    elif isinstance(value, str):
        raw = [x.strip() for x in value.split(",") if x.strip()]
    else:
        raw = [value]
    out: List[int] = []
    for v in raw:
        try:
            out.append(int(v))
        except Exception:
            continue
    return list(sorted(set(out)))

def get_json() -> Dict[str, Any]:
    data = request.get_json(silent=True)
    if data is None:
        # Supporte aussi form-urlencoded pour éviter "Unsupported Media Type"
        data = request.form.to_dict(flat=True) if request.form else {}
        # récupère aussi les listes form-data (root_ids[] / parent_ids[])
        for key in ("root_ids", "parent_ids"):
            vals = request.form.getlist(key)
            if vals:
                data[key] = vals
    return data

# -------------------------
# Endpoints privés (auth)
# -------------------------

@bp.post("/events")
@login_required
def create_event():
    """Création via JSON/form :
       Accepte {name, date?, parent_ids? OU root_ids?} et associe les parents level 0.
    """
    require_can_manage_event()

    data = get_json()
    name = (data.get("name") or "").strip()
    date_str = (data.get("date") or "").strip()
    parent_ids = _normalize_ids(data.get("parent_ids")) or _normalize_ids(data.get("root_ids"))

    if not name:
        abort(400, description="name requis")
    if not parent_ids:
        abort(400, description="parent_ids (ou root_ids) requis")

    # Parse date optionnelle (YYYY-MM-DD)
    date_val = None
    if date_str:
        try:
            from datetime import date
            date_val = date.fromisoformat(date_str)
        except Exception:
            date_val = None

    ev = Event(name=name, date=date_val, status=EventStatus.OPEN, created_by_id=current_user.id)
    db.session.add(ev)
    db.session.flush()  # pour ev.id

    # Associer seulement des GROUP level 0
    roots: Iterable[StockNode] = (
        db.session.query(StockNode)
        .filter(StockNode.id.in_(parent_ids), StockNode.type == NodeType.GROUP, StockNode.level == 0)
        .order_by(StockNode.name.asc())
        .all()
    )

    added = 0
    for r in roots:
        db.session.execute(event_stock.insert().values(event_id=ev.id, node_id=r.id))
        added += 1

    current_app.logger.info("[EVENT CREATE] ev_id=%s name=%s parents_in=%s parents_added=%s",
                            ev.id, ev.name, parent_ids, added)

    if added == 0:
        db.session.rollback()
        abort(400, description="Aucun parent racine valide fourni")

    db.session.commit()
    return jsonify({"ok": True, "id": ev.id}), 201

@bp.get("/events/<int:event_id>/tree")
@login_required
def get_event_tree(event_id: int):
    """Renvoie l'arbre complet pour l'événement (utile si le template fetch)."""
    ev = db.session.get(Event, event_id) or abort(404)
    require_can_view_event(ev)
    tree = build_event_tree(event_id)
    return jsonify(tree)

@bp.get("/events/<int:event_id>/stock-roots")
@login_required
def get_event_stock_roots(event_id: int):
    """Parents racine associés à l'événement (id + name)."""
    ev = db.session.get(Event, event_id) or abort(404)
    require_can_view_event(ev)
    q = (
        db.session.query(StockNode)
        .join(event_stock, event_stock.c.node_id == StockNode.id)
        .filter(event_stock.c.event_id == event_id)
        .order_by(StockNode.name.asc())
    )
    roots = [{"id": n.id, "name": n.name} for n in q.all()]
    return jsonify(roots)

@bp.post("/events/<int:event_id>/share-link")
@login_required
def create_share_link(event_id: int):
    """Génère (ou réutilise) un lien public pour les secouristes."""
    ev = db.session.get(Event, event_id) or abort(404)
    require_can_manage_event(ev)
    link = EventShareLink.query.filter_by(event_id=event_id, active=True).first()
    if not link:
        token = uuid.uuid4().hex
        link = EventShareLink(event_id=event_id, token=token, active=True)
        db.session.add(link)
        db.session.commit()
    return jsonify({"ok": True, "token": link.token, "url": f"/public/event/{link.token}"}), 201

@bp.patch("/events/<int:event_id>/status")
@login_required
def update_event_status(event_id: int):
    """Change le statut de l'événement (ex: CLOSED / OPEN)."""
    ev = db.session.get(Event, event_id) or abort(404)
    data = get_json()
    status_str = (data.get("status") or "").upper()

    if status_str == "CLOSED":
        require_can_manage_event(ev)
        ev.status = EventStatus.CLOSED
        db.session.commit()
        try:
            socketio.emit("event_update", {"type": "event_closed", "event_id": ev.id}, room=f"event_{ev.id}")
        except Exception:
            pass
        return jsonify({"ok": True, "status": "CLOSED"})

    if status_str == "OPEN":
        if current_user.role != Role.ADMIN:
            abort(403)
        ev.status = EventStatus.OPEN
        db.session.commit()
        try:
            socketio.emit("event_update", {"type": "event_opened", "event_id": ev.id}, room=f"event_{ev.id}")
        except Exception:
            pass
        return jsonify({"ok": True, "status": "OPEN"})

    abort(400, description="Statut invalide")

@bp.post("/events/<int:event_id>/parent-status")
@login_required
def update_parent_status(event_id: int):
    """Marque un parent (sac/ambulance…) comme 'chargé dans le véhicule'."""
    ev = db.session.get(Event, event_id) or abort(404)
    require_can_manage_event(ev)
    data = get_json()
    node_id = int(data.get("node_id") or 0)
    charged = bool(data.get("charged_vehicle"))
    if not node_id:
        abort(400, description="node_id manquant")
    ens = (
        EventNodeStatus.query.filter_by(event_id=event_id, node_id=node_id).first()
        or EventNodeStatus(event_id=event_id, node_id=node_id)
    )
    ens.charged_vehicle = charged
    db.session.add(ens)
    db.session.commit()
    try:
        socketio.emit(
            "event_update",
            {"type": "parent_charged", "event_id": ev.id, "node_id": node_id, "charged": charged},
            room=f"event_{ev.id}",
        )
    except Exception:
        pass
    return jsonify({"ok": True, "node_id": node_id, "charged_vehicle": charged})

@bp.post("/events/<int:event_id>/verify")
@login_required
def verify_item(event_id: int):
    """Ajoute un enregistrement de vérification pour un item (OK / NOT_OK) — version privée (auth)."""
    ev = db.session.get(Event, event_id) or abort(404)
    require_can_manage_event(ev)  # CHEF/ADMIN
    data = get_json()
    node_id = int(data.get("node_id") or 0)
    status = (data.get("status") or "").upper()  # "OK" | "NOT_OK"
    verifier_name = (data.get("verifier_name") or "").strip()
    if not node_id or status not in ("OK", "NOT_OK") or not verifier_name:
        abort(400, description="Paramètres invalides (node_id, status, verifier_name)")
    rec = VerificationRecord(event_id=event_id, node_id=node_id, status=status, verifier_name=verifier_name)
    db.session.add(rec)
    db.session.commit()
    try:
        socketio.emit(
            "event_update",
            {"type": "item_verified", "event_id": ev.id, "node_id": node_id, "status": status, "by": verifier_name},
            room=f"event_{ev.id}",
        )
    except Exception:
        pass
    return jsonify({"ok": True, "record_id": rec.id})

@bp.get("/events/<int:event_id>/stats")
@login_required
def event_stats(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    require_can_view_event(ev)
    total_ok = db.session.query(VerificationRecord).filter_by(event_id=event_id, status="OK").count()
    total_all = db.session.query(VerificationRecord).filter_by(event_id=event_id).count()
    return jsonify({"ok": True, "verified_ok": total_ok, "verified_total": total_all})

# --------- Admin: suppression d’événement ----------
@bp.delete("/events/<int:event_id>")
@login_required
def delete_event(event_id: int):
    if not current_user.is_authenticated or current_user.role != Role.ADMIN:
        abort(403)
    ev = db.session.get(Event, event_id)
    if not ev:
        abort(404)
    # Nettoyage manuel si cascade non définie
    db.session.query(EventShareLink).filter_by(event_id=event_id).delete()
    db.session.query(EventNodeStatus).filter_by(event_id=event_id).delete()
    db.session.query(VerificationRecord).filter_by(event_id=event_id).delete()
    db.session.execute(event_stock.delete().where(event_stock.c.event_id == event_id))
    db.session.delete(ev)
    db.session.commit()
    return jsonify({"ok": True})

# -------------------------
# Endpoints PUBLICS (via token de partage)
# -------------------------

@bp.get("/public/event/<token>/tree")
def public_event_tree(token: str):
    """Arbre accessible via lien de partage. Pas de login requis."""
    link = EventShareLink.query.filter_by(token=token, active=True).first()
    if not link or not link.event:
        abort(404)
    tree = build_event_tree(link.event_id)
    return jsonify(tree)

@bp.post("/public/event/<token>/verify")
def public_verify_item(token: str):
    """Vérification d’un item sans compte, via le token. Nécessite que l’événement soit OPEN."""
    link = EventShareLink.query.filter_by(token=token, active=True).first()
    if not link or not link.event:
        abort(404)
    ev = link.event
    if ev.status != EventStatus.OPEN:
        abort(403, description="Événement clôturé")

    data = get_json()
    node_id = int(data.get("node_id") or 0)
    status = (data.get("status") or "").upper()  # "OK" | "NOT_OK"
    verifier_name = (data.get("verifier_name") or "").strip()

    if not node_id or status not in ("OK", "NOT_OK") or not verifier_name:
        abort(400, description="Paramètres invalides (node_id, status, verifier_name)")

    rec = VerificationRecord(event_id=ev.id, node_id=node_id, status=status, verifier_name=verifier_name)
    db.session.add(rec)
    db.session.commit()

    try:
        socketio.emit(
            "event_update",
            {"type": "item_verified", "event_id": ev.id, "node_id": node_id, "status": status, "by": verifier_name},
            room=f"event_{ev.id}",
        )
    except Exception:
        pass

    return jsonify({"ok": True, "record_id": rec.id})
