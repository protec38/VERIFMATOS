# app/events/views.py — API JSON pour les événements (AUCUN HTML ici)
from __future__ import annotations
import uuid
from typing import Any, Dict, List
from flask import Blueprint, jsonify, request, abort
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

bp = Blueprint("events", __name__)  # enregistré dans create_app() sans prefix pour /events/...

# -------------------------
# Helpers permissions
# -------------------------
def require_can_manage_event(ev: Event) -> None:
    """Autorise ADMIN et CHEF tant que l'événement est OPEN."""
    if not current_user.is_authenticated:
        abort(401)
    if current_user.role not in (Role.ADMIN, Role.CHEF):
        abort(403)
    if ev.status != EventStatus.OPEN:
        abort(403)

def require_can_view_event(ev: Event) -> None:
    if not current_user.is_authenticated:
        abort(401)
    if current_user.role not in (Role.ADMIN, Role.CHEF, Role.VIEWER):
        abort(403)

# -------------------------
# Utilitaires JSON
# -------------------------
def get_json() -> Dict[str, Any]:
    data = request.get_json(silent=True)
    if data is None:
        # Supporte aussi form-urlencoded pour éviter "Unsupported Media Type"
        data = request.form.to_dict() if request.form else {}
    return data

# -------------------------
# Endpoints
# -------------------------

@bp.get("/events/<int:event_id>/stock-roots")
@login_required
def get_event_stock_roots(event_id: int):
    """Retourne la liste des parents racine associés à l'événement (id + name)."""
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

    # Réutilise un lien actif s'il existe
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
    """Change le statut de l'événement (ex: CLOSED)."""
    ev = db.session.get(Event, event_id) or abort(404)
    data = get_json()
    status_str = (data.get("status") or "").upper()

    if status_str == "CLOSED":
        require_can_manage_event(ev)
        ev.status = EventStatus.CLOSED
        db.session.commit()
        # Notifie via Socket.IO (canal de l'événement)
        try:
            socketio.emit("event_update", {"type": "event_closed", "event_id": ev.id}, room=f"event_{ev.id}")
        except Exception:
            pass
        return jsonify({"ok": True, "status": "CLOSED"})

    elif status_str == "OPEN":
        # Optionnel : autoriser réouverture aux ADMIN uniquement
        if not current_user.is_authenticated or current_user.role != Role.ADMIN:
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
    """Ajoute un enregistrement de vérification pour un item (OK / NOT_OK)."""
    ev = db.session.get(Event, event_id) or abort(404)
    # Autoriser CHEF/ADMIN. Si tu veux autoriser aussi VIEWER, élargis ici.
    require_can_manage_event(ev)

    data = get_json()
    node_id = int(data.get("node_id") or 0)
    status = (data.get("status") or "").upper()  # "OK" | "NOT_OK"
    verifier_name = (data.get("verifier_name") or "").strip()

    if not node_id or status not in ("OK", "NOT_OK") or not verifier_name:
        abort(400, description="Paramètres invalides (node_id, status, verifier_name)")

    # On pourrait contrôler ici que node_id correspond bien à un ITEM rattaché à l'événement.
    rec = VerificationRecord(
        event_id=event_id,
        node_id=node_id,
        status=status,
        verifier_name=verifier_name,
    )
    db.session.add(rec)
    db.session.commit()

    # Notifie le front pour mettre à jour la progression
    try:
        socketio.emit(
            "event_update",
            {"type": "item_verified", "event_id": ev.id, "node_id": node_id, "status": status, "by": verifier_name},
            room=f"event_{ev.id}",
        )
    except Exception:
        pass

    return jsonify({"ok": True, "record_id": rec.id})

# (Optionnel) statistiques brèves
@bp.get("/events/<int:event_id>/stats")
@login_required
def event_stats(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    require_can_view_event(ev)

    total_ok = db.session.query(VerificationRecord).filter_by(event_id=event_id, status="OK").count()
    total_all = db.session.query(VerificationRecord).filter_by(event_id=event_id).count()
    return jsonify({"ok": True, "verified_ok": total_ok, "verified_total": total_all})
