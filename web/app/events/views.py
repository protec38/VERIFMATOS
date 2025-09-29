# app/events/views.py — API JSON pour les événements (création, suppression, opérations)
from __future__ import annotations
import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Iterable, Tuple

from flask import Blueprint, jsonify, request, abort, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import text, func, select

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

def _require_role_admin_or_chef() -> None:
    if not current_user.is_authenticated:
        abort(401)
    if current_user.role not in (Role.ADMIN, Role.CHEF):
        abort(403)

def _delete_event_rows(ev: Event) -> None:
    # nettoyage “soft” si les relations ne sont pas en cascade
    db.session.query(VerificationRecord).filter_by(event_id=ev.id).delete(synchronize_session=False)
    db.session.query(EventNodeStatus).filter_by(event_id=ev.id).delete(synchronize_session=False)
    db.session.query(EventShareLink).filter_by(event_id=ev.id).delete(synchronize_session=False)
    db.session.execute(event_stock.delete().where(event_stock.c.event_id == ev.id))
    db.session.delete(ev)

# ---------- Descendants utils (PostgreSQL CTE) ----------
def _descendant_item_ids(parent_id: int) -> List[int]:
    """
    Renvoie la liste des ids d'ITEM sous un parent (incl. profondeur).
    Ne filtre pas par évènement : l’arbre stock est global.
    """
    sql = text("""
        WITH RECURSIVE r AS (
            SELECT id, parent_id, type
            FROM stock_nodes
            WHERE id = :pid
          UNION ALL
            SELECT s.id, s.parent_id, s.type
            FROM stock_nodes s
            JOIN r ON s.parent_id = r.id
        )
        SELECT id FROM r WHERE type = 'ITEM'
    """)
    rows = db.session.execute(sql, {"pid": parent_id}).fetchall()
    return [int(r[0]) for r in rows]

def _latest_statuses(event_id: int, item_ids: Iterable[int]) -> Dict[int, str]:
    """
    Map {item_id: 'OK'|'NOT_OK'|'PENDING'} basé sur le dernier VerificationRecord par item.
    """
    item_ids = list(set(int(i) for i in item_ids))
    if not item_ids:
        return {}
    # Dernier record par (event_id, node_id)
    sub = (
        db.session.query(
            VerificationRecord.node_id.label("node_id"),
            func.max(VerificationRecord.created_at).label("max_ts")
        )
        .filter(VerificationRecord.event_id == event_id,
                VerificationRecord.node_id.in_(item_ids))
        .group_by(VerificationRecord.node_id)
        .subquery()
    )
    q = (
        db.session.query(VerificationRecord.node_id, VerificationRecord.status)
        .join(sub,
              (VerificationRecord.node_id == sub.c.node_id) &
              (VerificationRecord.created_at == sub.c.max_ts))
    )
    out = {i: "PENDING" for i in item_ids}
    for nid, st in q.all():
        out[int(nid)] = (st or "PENDING").upper()
    return out

def _all_items_ok(event_id: int, parent_id: int) -> bool:
    item_ids = _descendant_item_ids(parent_id)
    if not item_ids:
        return False
    last = _latest_statuses(event_id, item_ids)
    return all(v == "OK" for v in last.values())

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
        if not root or root.type != NodeType.GROUP or getattr(root, "level", None) not in (None, 0):
            # level peut ne pas exister selon ton modèle ; on vérifie juste type=GROUP
            pass
        db.session.execute(event_stock.insert().values(event_id=ev.id, node_id=rid))
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

# ---------- STATUS (close / reopen) ----------
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
        # ⬇️ Autoriser ADMIN **et** CHEF à rouvrir
        _require_role_admin_or_chef()
        ev.status = EventStatus.OPEN
        db.session.commit()
        try:
            socketio.emit("event_update", {"type": "event_opened", "event_id": ev.id}, room=f"event_{ev.id}")
        except Exception:
            pass
        return jsonify({"ok": True, "status": "OPEN"})

    abort(400, description="Statut invalide")

# ---------- PARENT CHARGED (avec véhicule & contrôle 'tout OK') ----------
@bp.post("/events/<int:event_id>/parent-status")
@login_required
def update_parent_status(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    _require_can_manage_event(ev)

    data = _json_or_form()
    node_id = int(data.get("node_id") or 0)
    charged = bool(data.get("charged_vehicle"))
    # accepter vehicle_label | vehicle | vehicle_name
    vehicle_label = (data.get("vehicle_label") or data.get("vehicle") or data.get("vehicle_name") or "").strip()

    if not node_id:
        abort(400, description="node_id manquant")

    if charged:
        # Vérifier que tous les items du parent sont OK
        if not _all_items_ok(event_id, node_id):
            abort(400, description="Impossible de marquer 'chargé' : tous les items ne sont pas OK.")
        # Exiger un libellé véhicule non vide côté serveur (optionnel mais recommandé)
        if not vehicle_label:
            abort(400, description="Merci d’indiquer le véhicule (ex. 'VSAV 1').")

    ens = (
        EventNodeStatus.query.filter_by(event_id=event_id, node_id=node_id).first()
        or EventNodeStatus(event_id=event_id, node_id=node_id)
    )
    ens.charged_vehicle = charged

    # Optionnel: si le modèle a la colonne vehicle_label, on l’utilise, sinon on ignore silencieusement.
    if hasattr(ens, "vehicle_label"):
        ens.vehicle_label = vehicle_label if charged else None

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
                "vehicle_label": getattr(ens, "vehicle_label", None),
            },
            room=f"event_{ev.id}",
        )
    except Exception:
        pass
    return jsonify({"ok": True, "node_id": node_id, "charged_vehicle": charged, "vehicle_label": getattr(ens, "vehicle_label", None)})

# ---------- VERIFY ITEM ----------
@bp.post("/events/<int:event_id>/verify")
@login_required
def verify_item(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    _require_can_manage_event(ev)

    data = _json_or_form()
    node_id = int(data.get("node_id") or 0)
    status = (data.get("status") or "").upper()   # "OK" | "NOT_OK"
    verifier_name = (data.get("verifier_name") or current_user.username or "").strip()
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

# ---------- BULK VERIFY ("Tout OK") ----------
@bp.post("/events/<int:event_id>/parent/<int:parent_id>/verify-all")
@login_required
def verify_all_under_parent(event_id: int, parent_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    _require_can_manage_event(ev)

    payload = _json_or_form()
    status = (payload.get("status") or "OK").upper()
    if status not in ("OK", "NOT_OK"):
        abort(400, description="status doit être 'OK' ou 'NOT_OK'")

    verifier_name = (payload.get("verifier_name") or current_user.username or "").strip() or "Chef"
    item_ids = _descendant_item_ids(parent_id)
    if not item_ids:
        abort(404, description="Aucun item sous ce parent")

    # On ajoute UNE vérification par item
    now = datetime.utcnow()
    db.session.bulk_save_objects([
        VerificationRecord(event_id=event_id, node_id=i, status=status, verifier_name=verifier_name, created_at=now)
        for i in item_ids
    ])
    db.session.commit()

    try:
        socketio.emit(
            "event_update",
            {"type":"parent_verify_all","event_id":ev.id,"parent_id":parent_id,"status":status,"by":verifier_name},
            room=f"event_{ev.id}"
        )
    except Exception:
        pass

    return jsonify({"ok": True, "parent_id": parent_id, "items_updated": len(item_ids), "status": status})

# ---------- RESET ("Tout remettre en attente") ----------
@bp.post("/events/<int:event_id>/parent/<int:parent_id>/reset")
@login_required
def reset_parent_verifications(event_id: int, parent_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    _require_can_manage_event(ev)

    item_ids = _descendant_item_ids(parent_id)
    if not item_ids:
        abort(404, description="Aucun item sous ce parent")

    db.session.query(VerificationRecord)\
        .filter(VerificationRecord.event_id == event_id,
                VerificationRecord.node_id.in_(item_ids))\
        .delete(synchronize_session=False)
    # Si le parent avait été marqué "chargé", on le remet à non chargé.
    ens = EventNodeStatus.query.filter_by(event_id=event_id, node_id=parent_id).first()
    if ens:
        ens.charged_vehicle = False
        if hasattr(ens, "vehicle_label"):
            ens.vehicle_label = None
        db.session.add(ens)

    db.session.commit()

    try:
        socketio.emit(
            "event_update",
            {"type":"parent_reset","event_id":ev.id,"parent_id":parent_id},
            room=f"event_{ev.id}"
        )
    except Exception:
        pass

    return jsonify({"ok": True, "parent_id": parent_id, "reset": True})

# ---------- HISTORY ----------
@bp.get("/events/<int:event_id>/history")
@login_required
def event_history(event_id: int):
    """
    ?node_id=...  -> historique d’un item
    ?parent_id=... -> historique de tous les items sous le parent (tri décroissant)
    Optionnels:
      - limit (par défaut 200)
    """
    ev = db.session.get(Event, event_id) or abort(404)
    _require_can_view_event(ev)

    node_id = request.args.get("node_id", type=int)
    parent_id = request.args.get("parent_id", type=int)
    limit = request.args.get("limit", type=int) or 200

    q = db.session.query(VerificationRecord).filter(VerificationRecord.event_id == event_id)

    if node_id:
        q = q.filter(VerificationRecord.node_id == node_id)
    elif parent_id:
        item_ids = _descendant_item_ids(parent_id)
        if not item_ids:
            return jsonify([])
        q = q.filter(VerificationRecord.node_id.in_(item_ids))
    else:
        # Sans filtre, on renvoie l’historique global de l’évènement (limité)
        pass

    q = q.order_by(VerificationRecord.created_at.desc()).limit(limit)
    out = [{
        "id": r.id,
        "node_id": r.node_id,
        "status": r.status,
        "by": r.verifier_name,
        "at": r.created_at.isoformat() if getattr(r, "created_at", None) else None
    } for r in q.all()]
    return jsonify(out)

# ---------- STATS ----------
@bp.get("/events/<int:event_id>/stats")
@login_required
def event_stats(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    _require_can_view_event(ev)
    total_ok = db.session.query(VerificationRecord).filter_by(event_id=event_id, status="OK").count()
    total_all = db.session.query(VerificationRecord).filter_by(event_id=event_id).count()
    return jsonify({"ok": True, "verified_ok": total_ok, "verified_total": total_all})

# ---------- DELETE (autoriser même si fermé) ----------
@bp.delete("/events/<int:event_id>")
@login_required
def delete_event_api(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    # ⬇️ rôles uniquement, pas de contrainte statut
    _require_role_admin_or_chef()
    _delete_event_rows(ev)
    db.session.commit()
    return jsonify({"ok": True})

@bp.route("/events/<int:event_id>/delete", methods=["POST"])
@login_required
def delete_event_form(event_id: int):
    ev = db.session.get(Event, event_id) or abort(404)
    # ⬇️ rôles uniquement, pas de contrainte statut
    _require_role_admin_or_chef()
    _delete_event_rows(ev)
    db.session.commit()
    if request.is_json:
        return jsonify({"ok": True})
    # Redirection pour les formulaires classiques
    return redirect(url_for("pages.dashboard"))
