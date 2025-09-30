# app/events/views.py — API JSON pour les événements (création, suppression, opérations)
from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Dict, List

from flask import Blueprint, jsonify, request, abort, redirect, url_for
from flask_login import login_required, current_user

from .. import db, socketio
from ..models import (
    Event,
    EventStatus,
    Role,
    StockNode,
    NodeType,
    event_stock,             # association évènement <-> parents racine
    EventShareLink,          # lien public
    EventNodeStatus,         # statut par parent (chargé, etc.)
    VerificationRecord,      # vérifications
)
from ..tree_query import build_event_tree

bp = Blueprint("events", __name__)


# ---------- Helpers ----------
def _json_or_form() -> Dict[str, Any]:
    """Récupère la payload soit en JSON, soit en form-urlencoded (fallback)."""
    data = request.get_json(silent=True)
    if data is None:
        data = request.form.to_dict(flat=False) if request.form else {}
        flat: Dict[str, Any] = {}
        for k, v in data.items():
            flat[k] = v[0] if isinstance(v, list) and len(v) == 1 else v
        data = flat
    return data


def _as_int_list(value: Any) -> List[int]:
    """Transforme '1,2' / ['1','2'] / [1,2] en liste d'int."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        raw = value
    else:
        raw = str(value).split(",")
    out: List[int] = []
    for x in raw:
        s = str(x).strip()
        if s.isdigit():
            out.append(int(s))
    return out


def _require_admin() -> None:
    if not current_user.is_authenticated or current_user.role != Role.ADMIN:
        abort(403)


def _require_can_manage_event(ev: Event | None = None) -> None:
    """Autorise ADMIN & CHEF, et exige que l'événement soit OPEN quand un évènement est fourni."""
    if not current_user.is_authenticated:
        abort(401)
    if current_user.role not in (Role.ADMIN, Role.CHEF):
        abort(403)
    if ev is not None and ev.status != EventStatus.OPEN:
        abort(403)


def _require_can_view_event(ev: Event) -> None:
    if not current_user.is_authenticated:
        abort(401)
    if current_user.role not in (Role.ADMIN, Role.CHEF, Role.VIEWER):
        abort(403)


def _delete_event_rows(ev: Event) -> None:
    """Nettoyage (si les relations ne sont pas en cascade côté modèle)."""
    db.session.query(VerificationRecord).filter_by(event_id=ev.id).delete(synchronize_session=False)
    db.session.query(EventNodeStatus).filter_by(event_id=ev.id).delete(synchronize_session=False)
    db.session.query(EventShareLink).filter_by(event_id=ev.id).delete(synchronize_session=False)
    db.session.execute(event_stock.delete().where(event_stock.c.event_id == ev.id))
    db.session.delete(ev)


# ---------- CREATE ----------
@bp.post("/events")
@login_required
def create_event():
    """
    Crée un évènement.
    Attend:
      - name: str
      - date: "YYYY-MM-DD" (optionnel)
      - root_ids: liste d'ids (checkbox) -> [1,2] ou "1,2" ou champs répétés.
    """
    _require_can_manage_event()

    payload = _json_or_form()
    name = (payload.get("name") or "").strip()
    date_str = (payload.get("date") or "").strip()
    # accepte 'root_ids' ou 'root_ids[]'
    root_ids = _as_int_list(payload.get("root_ids") or payload.get("root_ids[]"))

    if not name:
        abort(400, description="Paramètre 'name' requis")
    if not root_ids:
        abort(400, description="Sélectionne au moins un parent (root_ids)")

    ev_date: date | None = None
    if date_str:
        try:
            ev_date = date.fromisoformat(date_str)
        except Exception:
            ev_date = None

    ev = Event(name=name, date=ev_date, status=EventStatus.OPEN, created_by_id=current_user.id)
    db.session.add(ev)
    db.session.flush()  # pour ev.id

    added = 0
    for rid in sorted(set(root_ids)):
        root = db.session.get(StockNode, rid)
        # ✅ racine = parent_id is None (et de type GROUP)
        if not root or root.type != NodeType.GROUP or root.parent_id is not None:
            continue
        db.session.execute(event_stock.insert().values(event_id=ev.id, node_id=root.id))
        added += 1
    if not added:
        db.session.rollback()
        abort(400, description="Aucun parent racine valide trouvé")

    db.session.commit()

    if request.is_json:
        return jsonify({"ok": True, "id": ev.id, "url": url_for("pages.event_page", event_id=ev.id)}), 201
    return redirect(url_for("pages.event_page", event_id=ev.id), code=303)


# ---------- READ TREE (polling) ----------
@bp.get("/events/<int:event_id>/tree")
@login_required
def get_event_tree(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    _require_can_view_event(ev)
    tree = build_event_tree(event_id)
    return jsonify(tree)


# ---------- STOCK ROOTS LIST ----------
@bp.get("/events/<int:event_id>/stock-roots")
@login_required
def get_event_stock_roots(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    _require_can_view_event(ev)
    q = (
        db.session.query(StockNode)
        .join(event_stock, event_stock.c.node_id == StockNode.id)
        .filter(event_stock.c.event_id == event_id)
        .order_by(StockNode.name.asc())
    )
    roots = [{"id": n.id, "name": n.name} for n in q.all()]
    return jsonify(roots)


# ---------- SHARE LINK ----------
@bp.post("/events/<int:event_id>/share-link")
@login_required
def create_share_link(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    _require_can_manage_event(ev)

    link = EventShareLink.query.filter_by(event_id=event_id, active=True).first()
    if not link:
        token = uuid.uuid4().hex
        link = EventShareLink(event_id=event_id, token=token, active=True)
        db.session.add(link)
        db.session.commit()
    return jsonify({"ok": True, "token": link.token, "url": f"/public/event/{link.token}"}), 201


# ---------- STATUS (CLOSE / RE-OPEN) ----------
@bp.patch("/events/<int:event_id>/status")
@login_required
def update_event_status(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    data = _json_or_form()
    status_str = (data.get("status") or "").upper()

    if status_str == "CLOSED":
        _require_can_manage_event(ev)
        ev.status = EventStatus.CLOSED
        db.session.commit()
        try:
            socketio.emit("event_update", {"type": "event_closed", "event_id": ev.id}, room=f"event_{ev.id}")
        except Exception:
            pass
        return jsonify({"ok": True, "status": "CLOSED"})

    if status_str == "OPEN":
        _require_admin()  # réouverture réservée ADMIN
        ev.status = EventStatus.OPEN
        db.session.commit()
        try:
            socketio.emit("event_update", {"type": "event_opened", "event_id": ev.id}, room=f"event_{ev.id}")
        except Exception:
            pass
        return jsonify({"ok": True, "status": "OPEN"})

    abort(400, description="Statut invalide")


# ---------- PARENT CHARGED ----------
@bp.post("/events/<int:event_id>/parent-status")
@login_required
def update_parent_status(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    _require_can_manage_event(ev)

    data = _json_or_form()
    node_id = int(data.get("node_id") or 0)

    # parse robuste du booléen
    val = data.get("charged_vehicle")
    charged = False
    if isinstance(val, bool):
        charged = val
    elif isinstance(val, (int, float)):
        charged = bool(val)
    elif isinstance(val, str):
        charged = val.strip().lower() in {"1", "true", "on", "yes"}

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


# ---------- VERIFY ITEM ----------
@bp.post("/events/<int:event_id>/verify")
@login_required
def verify_item(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    _require_can_manage_event(ev)

    data = _json_or_form()
    node_id = int(data.get("node_id") or 0)
    status = (data.get("status") or "").upper()   # "OK" | "NOT_OK"
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


# ---------- STATS ----------
@bp.get("/events/<int:event_id>/stats")
@login_required
def event_stats(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    _require_can_view_event(ev)
    total_ok = db.session.query(VerificationRecord).filter_by(event_id=event_id, status="OK").count()
    total_all = db.session.query(VerificationRecord).filter_by(event_id=event_id).count()
    return jsonify({"ok": True, "verified_ok": total_ok, "verified_total": total_all})


# ---------- DELETE (API DELETE + fallback POST) ----------
@bp.delete("/events/<int:event_id>")
@login_required
def delete_event_api(event_id: int):
    """Suppression autorisée même si CLOSED (ADMIN uniquement)."""
    ev = db.session.get(Event, event_id) or abort(404)
    _require_admin()  # 👈 suppression toujours possible pour ADMIN
    _delete_event_rows(ev)
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/events/<int:event_id>/delete", methods=["POST"])
@login_required
def delete_event_form(event_id: int):
    """Fallback formulaire (POST)."""
    ev = db.session.get(Event, event_id) or abort(404)
    _require_admin()  # 👈 suppression toujours possible pour ADMIN
    _delete_event_rows(ev)
    db.session.commit()
    if request.is_json:
        return jsonify({"ok": True})
    return redirect(url_for("pages.dashboard"))
