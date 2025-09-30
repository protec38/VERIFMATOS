# app/events/views.py — API JSON pour les événements (privé + public)
from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request, abort, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import desc

from .. import db, socketio
from ..models import (
    Event,
    EventStatus,
    Role,
    StockNode,
    NodeType,
    event_stock,             # association évènement <-> parents racine
    EventShareLink,          # lien public
    EventNodeStatus,         # statut par parent (chargé, véhicule, etc.)
    VerificationRecord,      # vérifications item
)
from ..tree_query import build_event_tree

bp = Blueprint("events", __name__)


# ---------- Helpers communs ----------
def _json_or_form() -> Dict[str, Any]:
    data = request.get_json(silent=True)
    if data is None:
        data = request.form.to_dict(flat=False) if request.form else {}
        flat: Dict[str, Any] = {}
        for k, v in data.items():
            flat[k] = v[0] if isinstance(v, list) and len(v) == 1 else v
        data = flat
    return data


def _as_int_list(value: Any) -> List[int]:
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
    db.session.query(VerificationRecord).filter_by(event_id=ev.id).delete(synchronize_session=False)
    db.session.query(EventNodeStatus).filter_by(event_id=ev.id).delete(synchronize_session=False)
    db.session.query(EventShareLink).filter_by(event_id=ev.id).delete(synchronize_session=False)
    db.session.execute(event_stock.delete().where(event_stock.c.event_id == ev.id))
    db.session.delete(ev)


def _norm_status(s: Optional[str]) -> str:
    if not s:
        return "PENDING"
    s = s.upper()
    if s in {"NOT_OK", "NOK", "KO", "NOT-OK", "NOTOK"}:
        return "NOT_OK"
    if s == "OK":
        return "OK"
    return "PENDING"


def _latest_map_for_items(event_id: int, item_ids: List[int]) -> Dict[int, str]:
    """
    Renvoie {item_id: 'OK'|'NOT_OK'|'PENDING'} pour le dernier enregistrement.
    """
    if not item_ids:
        return {}
    q = (
        db.session.query(VerificationRecord)
        .filter(VerificationRecord.event_id == event_id, VerificationRecord.node_id.in_(item_ids))
        .order_by(desc(VerificationRecord.created_at), desc(VerificationRecord.id))
        .all()
    )
    seen = set()
    res: Dict[int, str] = {}
    for r in q:
        if r.node_id in seen:
            continue
        seen.add(r.node_id)
        res[r.node_id] = _norm_status(r.status)
    # items sans verif -> PENDING
    for iid in item_ids:
        if iid not in res:
            res[iid] = "PENDING"
    return res


def _collect_items_ids(n: StockNode, acc: List[int]):
    if n.type == NodeType.ITEM:
        acc.append(n.id)
    for c in n.children:
        _collect_items_ids(c, acc)


def _root_belongs_to_event(event_id: int, node_id: int) -> bool:
    row = db.session.execute(
        event_stock.select().where(
            event_stock.c.event_id == event_id,
            event_stock.c.node_id == node_id,
        )
    ).first()
    return bool(row)


def _all_descendant_items_ok(event_id: int, root: StockNode) -> bool:
    """
    Tous les ITEMS sous 'root' ont leur dernier statut à OK (au moins une vérification).
    Les items sans vérif sont considérés 'PENDING' -> retourne False.
    """
    items: List[int] = []
    _collect_items_ids(root, items)
    if not items:
        return False  # pas d'items -> on refuse de "charger"
    last = _latest_map_for_items(event_id, items)
    return all(st == "OK" for st in last.values())


def _token_to_event(token: str) -> Event:
    link = EventShareLink.query.filter_by(token=token, active=True).first()
    if not link or not link.event:
        abort(404)
    ev = link.event
    if ev.status != EventStatus.OPEN:
        abort(403, description="Événement fermé")
    return ev


# ---------- CREATE (privé) ----------
@bp.post("/events")
@login_required
def create_event():
    _require_can_manage_event()

    payload = _json_or_form()
    name = (payload.get("name") or "").strip()
    date_str = (payload.get("date") or "").strip()
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
    db.session.flush()

    added = 0
    for rid in sorted(set(root_ids)):
        root = db.session.get(StockNode, rid)
        # ✅ racine = parent_id is None (GROUP)
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


# ---------- READ TREE (privé) ----------
@bp.get("/events/<int:event_id>/tree")
@login_required
def get_event_tree(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    _require_can_view_event(ev)
    tree = build_event_tree(event_id)
    return jsonify(tree)


# ---------- STOCK ROOTS LIST (privé) ----------
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


# ---------- SHARE LINK (privé) ----------
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


# ---------- STATUS (privé) ----------
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
        _require_admin()
        ev.status = EventStatus.OPEN
        db.session.commit()
        try:
            socketio.emit("event_update", {"type": "event_opened", "event_id": ev.id}, room=f"event_{ev.id}")
        except Exception:
            pass
        return jsonify({"ok": True, "status": "OPEN"})

    abort(400, description="Statut invalide")


# ---------- PARENT STATUS (privé) ----------
@bp.post("/events/<int:event_id>/parent-status")
@login_required
def update_parent_status(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    _require_can_manage_event(ev)

    data = _json_or_form()
    node_id = int(data.get("node_id") or 0)

    val = data.get("charged_vehicle")
    charged = False
    if isinstance(val, bool):
        charged = val
    elif isinstance(val, (int, float)):
        charged = bool(val)
    elif isinstance(val, str):
        charged = val.strip().lower() in {"1", "true", "on", "yes"}

    vehicle_name = (data.get("vehicle_name") or "").strip() or None

    if not node_id:
        abort(400, description="node_id manquant")

    ens = (
        EventNodeStatus.query.filter_by(event_id=event_id, node_id=node_id).first()
        or EventNodeStatus(event_id=event_id, node_id=node_id)
    )
    ens.charged_vehicle = charged
    if vehicle_name is not None:
        ens.vehicle_name = vehicle_name
    db.session.add(ens)
    db.session.commit()

    try:
        socketio.emit(
            "event_update",
            {
                "type": "parent_charged",
                "event_id": ev.id,
                "node_id": node_id,
                "charged": charged,
                "vehicle_name": ens.vehicle_name or None,
            },
            room=f"event_{ev.id}",
        )
    except Exception:
        pass
    return jsonify({"ok": True, "node_id": node_id, "charged_vehicle": charged, "vehicle_name": ens.vehicle_name or None})


# ---------- VERIFY ITEM (privé) ----------
@bp.post("/events/<int:event_id>/verify")
@login_required
def verify_item(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    _require_can_manage_event(ev)

    data = _json_or_form()
    node_id = int(data.get("node_id") or 0)
    status_raw = (data.get("status") or "").upper()
    status = "OK" if status_raw == "OK" else ("NOT_OK" if status_raw in {"NOT_OK", "NOK", "KO", "NOT-OK", "NOTOK"} else "")
    verifier_name = (data.get("verifier_name") or "").strip()
    if not node_id or not status or not verifier_name:
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


# ---------- STATS (privé) ----------
@bp.get("/events/<int:event_id>/stats")
@login_required
def event_stats(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    _require_can_view_event(ev)
    total_ok = db.session.query(VerificationRecord).filter_by(event_id=event_id, status="OK").count()
    total_all = db.session.query(VerificationRecord).filter_by(event_id=event_id).count()
    return jsonify({"ok": True, "verified_ok": total_ok, "verified_total": total_all})


# ---------- DELETE (privé) ----------
@bp.delete("/events/<int:event_id>")
@login_required
def delete_event_api(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    _require_admin()
    _delete_event_rows(ev)
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/events/<int:event_id>/delete", methods=["POST"])
@login_required
def delete_event_form(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    _require_admin()
    _delete_event_rows(ev)
    db.session.commit()
    if request.is_json:
        return jsonify({"ok": True})
    return redirect(url_for("pages.dashboard"))


# =====================================================================
# ======================== Endpoints PUBLICS ===========================
# =====================================================================

@bp.get("/public/event/<token>/tree")
def public_tree(token: str):
    ev = _token_to_event(token)
    return jsonify(build_event_tree(ev.id))


@bp.post("/public/event/<token>/verify")
def public_verify(token: str):
    """
    Vérification publique d'un ITEM (OK / NOT_OK), opérateur requis.
    """
    ev = _token_to_event(token)
    data = _json_or_form()
    node_id = int(data.get("node_id") or 0)
    status = _norm_status(data.get("status"))  # OK | NOT_OK | PENDING
    operator = (data.get("operator_name") or data.get("verifier_name") or "").strip()

    if not node_id or status not in {"OK", "NOT_OK"} or not operator:
        abort(400, description="Paramètres invalides (node_id, status, operator_name)")

    # sécuriser: le node doit exister et être un ITEM
    node = db.session.get(StockNode, node_id)
    if not node or node.type != NodeType.ITEM:
        abort(400, description="Nœud non valide")

    rec = VerificationRecord(event_id=ev.id, node_id=node_id, status=status, verifier_name=operator)
    db.session.add(rec)
    db.session.commit()

    try:
        socketio.emit(
            "event_update",
            {"type": "item_verified", "event_id": ev.id, "node_id": node_id, "status": status, "by": operator},
            room=f"event_{ev.id}",
        )
    except Exception:
        pass
    return jsonify({"ok": True})


@bp.post("/public/event/<token>/charge")
def public_charge(token: str):
    """
    Marque un parent RACINE comme 'chargé' avec le nom de véhicule.
    Conditions:
      - le node_id appartient à l'évènement (table event_stock),
      - le node est une racine (parent_id is None) et de type GROUP,
      - tous les items descendants ont dernier statut OK.
    """
    ev = _token_to_event(token)
    data = _json_or_form()
    node_id = int(data.get("node_id") or 0)
    vehicle_name = (data.get("vehicle_name") or "").strip()

    if not node_id or not vehicle_name:
        abort(400, description="node_id et vehicle_name requis")

    # le node doit être une racine de l'évènement
    node = db.session.get(StockNode, node_id)
    if not node or node.type != NodeType.GROUP or node.parent_id is not None:
        abort(400, description="Seuls les parents racines peuvent être chargés")
    if not _root_belongs_to_event(ev.id, node_id):
        abort(403, description="Parent non rattaché à cet événement")

    # tous les items doivent être OK
    if not _all_descendant_items_ok(ev.id, node):
        abort(400, description="Impossible de charger : tous les sous-éléments doivent être OK")

    ens = (
        EventNodeStatus.query.filter_by(event_id=ev.id, node_id=node_id).first()
        or EventNodeStatus(event_id=ev.id, node_id=node_id)
    )
    ens.charged_vehicle = True
    ens.vehicle_name = vehicle_name
    db.session.add(ens)
    db.session.commit()

    try:
        socketio.emit(
            "event_update",
            {
                "type": "parent_charged",
                "event_id": ev.id,
                "node_id": node_id,
                "charged": True,
                "vehicle_name": vehicle_name,
            },
            room=f"event_{ev.id}",
        )
    except Exception:
        pass

    return jsonify({"ok": True, "node_id": node_id, "vehicle_name": vehicle_name})
