"""Periodic verification endpoints."""
from __future__ import annotations

from datetime import date, datetime
import secrets
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request, abort, render_template, url_for
from flask_login import current_user, login_required

from .. import db
from ..models import (
    Role,
    StockNode,
    NodeType,
    PeriodicVerificationRecord,
    PeriodicVerificationSession,
    PeriodicVerificationLink,
    ItemStatus,
    IssueCode,
    ReassortItem,
    ReassortBatch,
)
from ..tree_query import tree_stats
from sqlalchemy import or_

try:  # Optional table depending on migrations
    from ..models import StockItemExpiry
    HAS_EXP_MODEL = True
except Exception:  # pragma: no cover - fallback when table missing
    StockItemExpiry = None  # type: ignore
    HAS_EXP_MODEL = False

bp = Blueprint("verification_periodique", __name__, url_prefix="/verification-periodique")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _can_access() -> bool:
    return current_user.is_authenticated and current_user.role in (
        Role.ADMIN,
        Role.CHEF,
        Role.VERIFICATIONPERIODIQUE,
    )


def _ensure_table() -> None:
    try:
        PeriodicVerificationRecord.__table__.create(bind=db.engine, checkfirst=True)
    except Exception:
        db.session.rollback()


def _ensure_reassort_tables() -> None:
    try:
        ReassortItem.__table__.create(bind=db.engine, checkfirst=True)
        ReassortBatch.__table__.create(bind=db.engine, checkfirst=True)
    except Exception:
        db.session.rollback()


def _ensure_expiry_table() -> None:
    if not HAS_EXP_MODEL:
        return
    try:
        StockItemExpiry.__table__.create(bind=db.engine, checkfirst=True)  # type: ignore[union-attr]
    except Exception:
        db.session.rollback()


def _ensure_session_table() -> None:
    try:
        PeriodicVerificationSession.__table__.create(bind=db.engine, checkfirst=True)
    except Exception:
        db.session.rollback()


def _ensure_link_table() -> None:
    try:
        PeriodicVerificationLink.__table__.create(bind=db.engine, checkfirst=True)
    except Exception:
        db.session.rollback()


def _resolve_root(node_id: int) -> Optional[StockNode]:
    node = db.session.get(StockNode, node_id)
    if not node:
        return None
    while node.parent_id is not None:
        node = node.parent
    return node


def _sync_item_expiry(node_id: int) -> Optional[date]:
    if not HAS_EXP_MODEL:
        return None
    try:
        _ensure_expiry_table()
        rows: List[StockItemExpiry] = (  # type: ignore[misc]
            StockItemExpiry.query  # type: ignore[union-attr]
            .filter_by(node_id=node_id)  # type: ignore[union-attr]
            .order_by(  # type: ignore[union-attr]
                StockItemExpiry.expiry_date.asc(),  # type: ignore[union-attr]
                StockItemExpiry.id.asc(),  # type: ignore[union-attr]
            )
            .all()
        )
    except Exception:
        db.session.rollback()
        return None

    next_date = rows[0].expiry_date if rows else None
    node = db.session.get(StockNode, node_id)
    if node is not None:
        node.expiry_date = next_date
        db.session.add(node)
    return next_date


def _serialize_reassort_batch(batch: ReassortBatch, node_id: int) -> Dict[str, Any]:
    preferred = batch.item.target_node_id == node_id if batch.item else False
    return {
        "batch_id": batch.id,
        "item_id": batch.item_id,
        "item_name": batch.item.name if batch.item else None,
        "quantity": batch.quantity,
        "expiry_date": batch.expiry_date.isoformat() if batch.expiry_date else None,
        "lot": batch.lot,
        "note": batch.note,
        "preferred": preferred,
    }


def _norm_status(value: Any) -> str:
    if value is None:
        return "TODO"
    if hasattr(value, "name"):
        try:
            return str(value.name).upper()
        except Exception:  # pragma: no cover - defensive
            pass
    return str(value).upper()


def _latest_map(node_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    if not node_ids:
        return {}

    rows = (
        PeriodicVerificationRecord.query
        .filter(PeriodicVerificationRecord.node_id.in_(node_ids))
        .order_by(
            PeriodicVerificationRecord.node_id.asc(),
            PeriodicVerificationRecord.created_at.desc(),
            PeriodicVerificationRecord.id.desc(),
        )
        .all()
    )

    latest: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        nid = int(row.node_id)
        if nid in latest:
            continue
        latest[nid] = {
            "status": _norm_status(getattr(row, "status", None)),
            "by": row.verifier_name or getattr(getattr(row, "verifier", None), "username", None),
            "at": (getattr(row, "updated_at", None) or getattr(row, "created_at", None)),
            "comment": getattr(row, "comment", None),
            "issue_code": _norm_status(getattr(row, "issue_code", None)) if getattr(row, "issue_code", None) else None,
            "observed_qty": getattr(row, "observed_qty", None),
            "missing_qty": getattr(row, "missing_qty", None),
        }
        if latest[nid]["at"]:
            latest[nid]["at"] = latest[nid]["at"].isoformat()
    return latest


def _expiries_for_items(item_ids: List[int]) -> Dict[int, List[StockItemExpiry]]:  # type: ignore[name-defined]
    if not HAS_EXP_MODEL or not item_ids:
        return {}
    try:
        rows = (
            StockItemExpiry.query  # type: ignore[union-attr]
            .filter(StockItemExpiry.node_id.in_(item_ids))  # type: ignore[union-attr]
            .order_by(
                StockItemExpiry.node_id.asc(),  # type: ignore[union-attr]
                StockItemExpiry.expiry_date.asc(),  # type: ignore[union-attr]
                StockItemExpiry.id.asc(),  # type: ignore[union-attr]
            )
            .all()
        )
    except Exception:
        db.session.rollback()
        return {}

    out: Dict[int, List[StockItemExpiry]] = {}
    for row in rows:
        out.setdefault(int(row.node_id), []).append(row)
    return out


def _serialize(node: StockNode, latest: Dict[int, Dict[str, Any]], exp_map: Dict[int, List[StockItemExpiry]]) -> Dict[str, Any]:  # type: ignore[name-defined]
    base: Dict[str, Any] = {
        "id": node.id,
        "name": node.name,
        "type": node.type.name if hasattr(node.type, "name") else str(node.type),
    }

    if node.type == NodeType.ITEM:
        info = latest.get(int(node.id), {})
        expiries_payload: List[Dict[str, Any]] = []
        if HAS_EXP_MODEL:
            for e in exp_map.get(int(node.id), []):
                expiries_payload.append(
                    {
                        "date": e.expiry_date.isoformat(),
                        "quantity": e.quantity,
                        "lot": e.lot,
                        "note": e.note,
                        "id": e.id,
                    }
                )
        legacy_expiry = None
        if expiries_payload:
            legacy_expiry = expiries_payload[0]["date"]
        elif getattr(node, "expiry_date", None):
            legacy_expiry = node.expiry_date.isoformat()

        base.update(
            {
                "last_status": info.get("status", "TODO"),
                "last_by": info.get("by"),
                "last_at": info.get("at"),
                "comment": info.get("comment"),
                "issue_code": info.get("issue_code"),
                "observed_qty": info.get("observed_qty"),
                "missing_qty": info.get("missing_qty"),
                "quantity": node.quantity,
                "expiry_date": legacy_expiry,
                "expiries": expiries_payload,
                "children": [],
            }
        )
        return base

    is_unique = bool(getattr(node, "unique_item", False))
    children: List[Dict[str, Any]] = []
    if is_unique:
        info = latest.get(int(node.id), {})
        qty = getattr(node, "unique_quantity", None)
        base.update(
            {
                "unique_item": True,
                "unique_parent": True,
                "unique_quantity": qty,
                "quantity": qty,
                "selected_quantity": qty,
                "last_status": info.get("status", "TODO"),
                "last_by": info.get("by"),
                "last_at": info.get("at"),
                "comment": info.get("comment"),
                "issue_code": info.get("issue_code"),
                "observed_qty": info.get("observed_qty"),
                "missing_qty": info.get("missing_qty"),
                "children": [],
            }
        )
    else:
        ordered_children = sorted(node.children, key=lambda c: (c.level, c.id)) if hasattr(node, "children") else []
        for child in ordered_children:
            children.append(_serialize(child, latest, exp_map))
        base["children"] = children

    base["unique_item"] = is_unique
    if is_unique:
        base.setdefault("unique_quantity", getattr(node, "unique_quantity", None))
    return base


def _collect_item_ids(node: StockNode, collector: List[int]) -> None:
    if node.type == NodeType.ITEM or getattr(node, "unique_item", False):
        collector.append(int(node.id))
        return
    for child in getattr(node, "children", []) or []:
        _collect_item_ids(child, collector)


def _build_tree(root: StockNode) -> List[Dict[str, Any]]:
    items: List[int] = []
    _collect_item_ids(root, items)
    latest = _latest_map(items)
    exp_map = _expiries_for_items(items)
    return [_serialize(root, latest, exp_map)]


def _build_forest(roots: List[StockNode]) -> List[Dict[str, Any]]:
    forest: List[Dict[str, Any]] = []
    for root in roots:
        try:
            tree = _build_tree(root)
        except Exception:
            db.session.rollback()
            continue
        if tree:
            forest.extend(tree)
    return forest


def _safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        ivalue = int(value)
    except Exception:
        return None
    if ivalue < 0:
        return 0
    return ivalue


def _reset_items_to_todo(
    root: StockNode,
    *,
    actor_id: Optional[int],
    actor_name: Optional[str],
) -> int:
    item_ids: List[int] = []
    _collect_item_ids(root, item_ids)

    if not item_ids:
        return 0

    latest = _latest_map(item_ids)
    updated = 0
    for item_id in item_ids:
        last_status = (latest.get(item_id, {}).get("status") or "TODO").upper()
        if last_status == "TODO":
            continue
        rec = PeriodicVerificationRecord(
            node_id=item_id,
            status=ItemStatus.TODO,
            verifier_id=actor_id,
            verifier_name=actor_name,
            comment=None,
            issue_code=None,
            observed_qty=None,
            missing_qty=None,
        )
        db.session.add(rec)
        updated += 1
    return updated


def _share_payload(link: PeriodicVerificationLink) -> Dict[str, Any]:
    return {
        "id": link.id,
        "token": link.token,
        "url": url_for("verification_periodique.public_share", token=link.token, _external=True),
        "created_at": link.created_at.isoformat() if link.created_at else None,
        "last_used_at": link.last_used_at.isoformat() if link.last_used_at else None,
        "active": link.active,
    }


def _generate_share_token() -> str:
    for _ in range(10):
        token = secrets.token_urlsafe(16)
        if not PeriodicVerificationLink.query.filter_by(token=token).first():
            return token
    raise RuntimeError("Impossible de générer un lien unique")


def _get_or_create_public_link(
    root: StockNode,
    *,
    created_by_id: Optional[int],
) -> Optional[PeriodicVerificationLink]:
    query = (
        PeriodicVerificationLink.query
        .filter_by(root_id=root.id, active=True)
        .order_by(PeriodicVerificationLink.created_at.desc())
    )
    active_links = query.all()
    if active_links:
        primary = active_links[0]
        extras = active_links[1:]
        if extras:
            for entry in extras:
                entry.active = False
                db.session.add(entry)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
        return primary

    try:
        token = _generate_share_token()
    except RuntimeError:
        return None

    link = PeriodicVerificationLink(
        token=token,
        root_id=root.id,
        active=True,
        created_by_id=created_by_id,
    )
    db.session.add(link)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return None
    return link


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@bp.get("/roots")
@login_required
def list_roots():
    if not _can_access():
        return jsonify(error="Forbidden"), 403

    roots = (
        StockNode.query
        .filter(StockNode.parent_id.is_(None))
        .order_by(StockNode.name.asc())
        .all()
    )
    return jsonify([{"id": r.id, "name": r.name} for r in roots])


@bp.get("/tree/<int:root_id>")
@login_required
def tree(root_id: int):
    if not _can_access():
        return jsonify(error="Forbidden"), 403

    _ensure_table()

    node = db.session.get(StockNode, root_id)
    if not node:
        return jsonify(error="Parent introuvable"), 404

    while node.parent_id is not None:
        node = node.parent

    tree_payload = _build_tree(node)
    stats = tree_stats(tree_payload)

    return jsonify({
        "root": {"id": node.id, "name": node.name},
        "tree": tree_payload,
        "stats": stats,
    })


@bp.get("/public")
def public_catalog():
    _ensure_link_table()
    _ensure_session_table()
    _ensure_table()
    _ensure_expiry_table()

    roots = (
        StockNode.query
        .filter(StockNode.parent_id.is_(None))
        .order_by(StockNode.name.asc())
        .all()
    )

    forest = _build_forest(roots)

    return render_template(
        "verification_public.html",
        root=None,
        link=None,
        error=None,
        success=False,
        recorded_name=None,
        tree_data=forest,
        token=None,
        first_prefill="",
        last_prefill="",
        comment_prefill="",
        public_submit_url=url_for("verification_periodique.public_catalog_submit"),
    )


@bp.post("/public/submit")
def public_catalog_submit():
    _ensure_session_table()
    _ensure_table()
    _ensure_expiry_table()

    payload = request.get_json(silent=True) or {}
    try:
        root_id = int(payload.get("root_id") or 0)
    except Exception:
        return jsonify(error="root_id invalide"), 400

    if not root_id:
        return jsonify(error="root_id manquant"), 400

    root = _resolve_root(root_id)
    if not root:
        return jsonify(error="Parent introuvable"), 404

    items_payload = payload.get("items") or []
    if not isinstance(items_payload, list) or not items_payload:
        return jsonify(error="Aucun item fourni"), 400

    first = (payload.get("first_name") or "").strip()
    last = (payload.get("last_name") or "").strip()
    comment_raw = (payload.get("comment") or "").strip()
    full_name = " ".join(f for f in [first, last] if f).strip()

    if not first or not last:
        return jsonify(error="Merci d’indiquer un prénom et un nom."), 400

    allowed_ids: List[int] = []
    _collect_item_ids(root, allowed_ids)
    allowed_set = set(allowed_ids)

    created = 0
    missing_count = 0
    for entry in items_payload:
        if not isinstance(entry, dict):
            continue
        try:
            node_id = int(entry.get("node_id") or 0)
        except Exception:
            continue
        if node_id not in allowed_set:
            continue
        status_raw = (entry.get("status") or "").strip().upper()
        status = {"OK": ItemStatus.OK, "NOT_OK": ItemStatus.NOT_OK, "TODO": ItemStatus.TODO}.get(status_raw)
        if status is None:
            continue
        comment = (entry.get("comment") or "").strip() or None
        observed_qty = _safe_int(entry.get("observed_qty"))
        missing_qty = _safe_int(entry.get("missing_qty"))
        issue_code = IssueCode.MISSING if missing_qty not in (None, 0) else None
        if status == ItemStatus.NOT_OK:
            missing_count += 1
        rec = PeriodicVerificationRecord(
            node_id=node_id,
            status=status,
            verifier_name=full_name or None,
            comment=comment,
            issue_code=issue_code,
            observed_qty=observed_qty,
            missing_qty=missing_qty,
        )
        db.session.add(rec)
        created += 1

    session = PeriodicVerificationSession(
        root_id=root.id,
        verifier_name=full_name or None,
        verifier_first_name=first or None,
        verifier_last_name=last or None,
        comment=comment_raw or None,
        source="public_catalog",
    )
    db.session.add(session)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify(error="Impossible d’enregistrer la vérification. Merci de réessayer."), 500

    return jsonify(
        {
            "ok": True,
            "created": created,
            "session": {
                "id": session.id,
                "verifier": full_name or "Inconnu",
                "missing_items": missing_count,
            },
            "root": {"id": root.id, "name": root.name},
        }
    )


@bp.get("/history/<int:root_id>")
@login_required
def history(root_id: int):
    if not _can_access():
        return jsonify(error="Forbidden"), 403

    _ensure_session_table()

    root = _resolve_root(root_id)
    if not root:
        return jsonify(error="Parent introuvable"), 404

    sessions = (
        PeriodicVerificationSession.query
        .filter_by(root_id=root.id)
        .order_by(PeriodicVerificationSession.created_at.desc())
        .limit(50)
        .all()
    )

    payload: List[Dict[str, Any]] = []
    for session in sessions:
        timestamp = session.created_at
        display_name = (
            session.verifier_name
            or (f"{(session.verifier_first_name or '').strip()} {(session.verifier_last_name or '').strip()}".strip())
            or getattr(getattr(session, "verifier", None), "username", None)
            or None
        )
        if display_name:
            display_name = " ".join(display_name.split())
        source = (session.source or "internal").lower()
        source_label = "Lien public" if source == "public" else "Interne"
        payload.append(
            {
                "id": session.id,
                "verifier": display_name or "Inconnu",
                "timestamp": timestamp.isoformat() if timestamp else None,
                "source": source,
                "source_label": source_label,
                "comment": session.comment,
            }
        )

    return jsonify({"root": {"id": root.id, "name": root.name}, "records": payload})


@bp.post("/verify")
@login_required
def verify_item():
    if not _can_access():
        return jsonify(error="Forbidden"), 403

    _ensure_table()

    payload = request.get_json(silent=True) or {}
    try:
        node_id = int(payload.get("node_id") or 0)
    except Exception:
        return jsonify(error="node_id invalide"), 400

    status_raw = (payload.get("status") or "").strip().upper()
    status_map = {"OK": ItemStatus.OK, "NOT_OK": ItemStatus.NOT_OK, "TODO": ItemStatus.TODO}
    status = status_map.get(status_raw)
    if not node_id or status is None:
        return jsonify(error="Paramètres invalides"), 400

    node = db.session.get(StockNode, node_id)
    if not node:
        return jsonify(error="Item introuvable"), 404
    if node.type != NodeType.ITEM and not getattr(node, "unique_item", False):
        return jsonify(error="Seuls les items sont vérifiables"), 400

    comment = (payload.get("comment") or "").strip() or None

    issue_code = None
    raw_issue = (payload.get("issue_code") or "").strip().upper()
    if raw_issue:
        issue_code = getattr(IssueCode, raw_issue, None)

    def _safe_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            ivalue = int(value)
        except Exception:
            return None
        if ivalue < 0:
            return 0
        return ivalue

    observed_qty = _safe_int(payload.get("observed_qty"))
    missing_qty = _safe_int(payload.get("missing_qty"))

    rec = PeriodicVerificationRecord(
        node_id=node.id,
        status=status,
        verifier_id=current_user.id,
        verifier_name=getattr(current_user, "username", None),
        comment=comment,
        issue_code=issue_code,
        observed_qty=observed_qty,
        missing_qty=missing_qty,
    )
    db.session.add(rec)
    db.session.commit()

    return jsonify({"ok": True, "record_id": rec.id})


@bp.post("/reset")
@login_required
def reset_root():
    """Mark every item under a root back to TODO."""
    if not _can_access():
        return jsonify(error="Forbidden"), 403

    _ensure_table()

    payload = request.get_json(silent=True) or {}
    try:
        root_id = int(payload.get("root_id") or 0)
    except Exception:
        return jsonify(error="root_id invalide"), 400

    if not root_id:
        return jsonify(error="root_id requis"), 400

    root = _resolve_root(root_id)
    if not root:
        return jsonify(error="Parent introuvable"), 404

    actor_id = getattr(current_user, "id", None)
    actor_name = getattr(current_user, "username", None)

    updated = _reset_items_to_todo(root, actor_id=actor_id, actor_name=actor_name)

    if updated <= 0:
        return jsonify(ok=True, updated=0)

    db.session.commit()

    return jsonify(ok=True, updated=updated)


@bp.post("/finish")
@login_required
def finish_root():
    if not _can_access():
        return jsonify(error="Forbidden"), 403

    _ensure_table()
    _ensure_session_table()

    payload = request.get_json(silent=True) or {}
    try:
        root_id = int(payload.get("root_id") or 0)
    except Exception:
        return jsonify(error="root_id invalide"), 400

    if not root_id:
        return jsonify(error="root_id requis"), 400

    root = _resolve_root(root_id)
    if not root:
        return jsonify(error="Parent introuvable"), 404

    actor_id = getattr(current_user, "id", None)
    actor_name = getattr(current_user, "username", None)
    comment_raw = (payload.get("comment") or "").strip()
    reset_requested = payload.get("reset", True)

    session = PeriodicVerificationSession(
        root_id=root.id,
        verifier_id=actor_id,
        verifier_name=actor_name,
        comment=comment_raw or None,
        source="internal",
    )
    db.session.add(session)

    updated = 0
    if reset_requested:
        updated = _reset_items_to_todo(root, actor_id=actor_id, actor_name=actor_name)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify(error="Enregistrement impossible"), 500

    timestamp = session.created_at.isoformat() if session.created_at else None
    display_name = session.verifier_name or "Inconnu"
    return jsonify(
        {
            "ok": True,
            "session": {
                "id": session.id,
                "verifier": display_name,
                "timestamp": timestamp,
                "source": session.source,
                "comment": session.comment,
            },
            "reset": updated,
        }
    )


@bp.get("/share/<int:root_id>")
@login_required
def get_share(root_id: int):
    if not _can_access():
        return jsonify(error="Forbidden"), 403

    _ensure_link_table()

    root = _resolve_root(root_id)
    if not root:
        return jsonify(error="Parent introuvable"), 404

    link = _get_or_create_public_link(root, created_by_id=getattr(current_user, "id", None))
    if not link:
        return jsonify(error="Impossible de générer le lien public"), 500

    payload = _share_payload(link)
    return jsonify({"root": {"id": root.id, "name": root.name}, "link": payload})


@bp.post("/share/<int:root_id>")
@login_required
def create_or_rotate_share(root_id: int):
    if not _can_access():
        return jsonify(error="Forbidden"), 403

    _ensure_link_table()

    root = _resolve_root(root_id)
    if not root:
        return jsonify(error="Parent introuvable"), 404

    payload = request.get_json(silent=True) or {}
    if payload.get("rotate"):
        return jsonify(error="La rotation du lien public est désactivée."), 400

    link = _get_or_create_public_link(root, created_by_id=getattr(current_user, "id", None))
    if not link:
        return jsonify(error="Impossible de générer le lien public"), 500

    return jsonify({"root": {"id": root.id, "name": root.name}, "link": _share_payload(link)})


@bp.route("/public/<token>", methods=["GET", "POST"])
def public_share(token: str):
    if not token:
        abort(404)

    _ensure_link_table()
    _ensure_session_table()
    _ensure_table()
    _ensure_expiry_table()

    link = (
        PeriodicVerificationLink.query
        .filter_by(token=token, active=True)
        .first()
    )
    if not link or not link.active or not link.root:
        abort(404)

    root = link.root
    error: Optional[str] = None
    success = False
    recorded_name: Optional[str] = None

    if request.method == "POST" and request.is_json:
        payload = request.get_json(silent=True) or {}
        first = (payload.get("first_name") or "").strip()
        last = (payload.get("last_name") or "").strip()
        comment_raw = (payload.get("comment") or "").strip()
        full_name = " ".join(f for f in [first, last] if f).strip()
        items_payload = payload.get("items") or []
        if not isinstance(items_payload, list) or not items_payload:
            return jsonify(error="Aucun item fourni"), 400

        allowed_ids: List[int] = []
        _collect_item_ids(root, allowed_ids)
        allowed_set = set(allowed_ids)

        created = 0
        missing_count = 0
        for entry in items_payload:
            if not isinstance(entry, dict):
                continue
            try:
                node_id = int(entry.get("node_id") or 0)
            except Exception:
                continue
            if node_id not in allowed_set:
                continue
            status_raw = (entry.get("status") or "").strip().upper()
            status = {"OK": ItemStatus.OK, "NOT_OK": ItemStatus.NOT_OK, "TODO": ItemStatus.TODO}.get(status_raw)
            if status is None:
                continue
            comment = (entry.get("comment") or "").strip() or None
            observed_qty = _safe_int(entry.get("observed_qty"))
            missing_qty = _safe_int(entry.get("missing_qty"))
            issue_code = IssueCode.MISSING if missing_qty not in (None, 0) else None
            if status == ItemStatus.NOT_OK:
                missing_count += 1
            rec = PeriodicVerificationRecord(
                node_id=node_id,
                status=status,
                verifier_name=full_name or None,
                comment=comment,
                issue_code=issue_code,
                observed_qty=observed_qty,
                missing_qty=missing_qty,
            )
            db.session.add(rec)
            created += 1

        session = PeriodicVerificationSession(
            root_id=root.id,
            verifier_name=full_name or None,
            verifier_first_name=first or None,
            verifier_last_name=last or None,
            comment=comment_raw or None,
            source="public",
            link_id=link.id,
        )
        db.session.add(session)

        try:
            link.last_used_at = datetime.utcnow()
        except Exception:
            pass

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            return jsonify(error="Impossible d’enregistrer la vérification. Merci de réessayer."), 500

        return jsonify(
            {
                "ok": True,
                "created": created,
                "session": {
                    "id": session.id,
                    "verifier": full_name or "Inconnu",
                    "missing_items": missing_count,
                },
                "root": {"id": root.id, "name": root.name},
            }
        )

    if request.method == "POST":
        first = (request.form.get("first_name") or "").strip()
        last = (request.form.get("last_name") or "").strip()
        comment_raw = (request.form.get("comment") or "").strip()
        if not first or not last:
            error = "Merci de renseigner votre prénom et votre nom."
        else:
            full_name = " ".join(f for f in [first, last] if f)
            session = PeriodicVerificationSession(
                root_id=root.id,
                verifier_name=full_name,
                verifier_first_name=first,
                verifier_last_name=last,
                comment=comment_raw or None,
                source="public",
                link_id=link.id,
            )
            db.session.add(session)
            try:
                link.last_used_at = datetime.utcnow()
            except Exception:
                pass
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                error = "Impossible d’enregistrer la vérification. Merci de réessayer."
            else:
                success = True
                recorded_name = full_name

    tree_payload = _build_tree(root)

    first_prefill = (request.form.get("first_name") or "") if request.method == "POST" else ""
    last_prefill = (request.form.get("last_name") or "") if request.method == "POST" else ""
    comment_prefill = (request.form.get("comment") or "") if request.method == "POST" else ""

    return render_template(
        "verification_public.html",
        root=root,
        link=link,
        error=error,
        success=success,
        recorded_name=recorded_name,
        tree_data=tree_payload,
        token=token,
        first_prefill=first_prefill,
        last_prefill=last_prefill,
        comment_prefill=comment_prefill,
        public_submit_url=url_for("verification_periodique.public_share", token=token),
    )


@bp.get("/reassort/<int:node_id>")
@login_required
def reassort_options(node_id: int):
    if not _can_access():
        return jsonify(error="Forbidden"), 403

    _ensure_reassort_tables()

    batches = (
        ReassortBatch.query
        .join(ReassortItem)
        .filter(ReassortBatch.quantity > 0)
        .filter(or_(ReassortItem.target_node_id == node_id, ReassortItem.target_node_id.is_(None)))
        .all()
    )
    batches.sort(
        key=lambda b: (
            b.item.target_node_id != node_id if b.item else True,
            (b.item.name.lower() if b.item and b.item.name else ""),
            b.expiry_date or date.max,
            b.id,
        )
    )

    payload = [_serialize_reassort_batch(b, node_id) for b in batches]
    return jsonify({"node_id": node_id, "items": payload})


@bp.post("/replace")
@login_required
def replace_from_reassort():
    if not _can_access():
        return jsonify(error="Forbidden"), 403

    _ensure_table()
    _ensure_reassort_tables()

    payload = request.get_json(silent=True) or {}

    try:
        node_id = int(payload.get("node_id") or 0)
    except Exception:
        return jsonify(error="node_id invalide"), 400

    try:
        batch_id = int(payload.get("batch_id") or 0)
    except Exception:
        return jsonify(error="batch_id invalide"), 400

    try:
        quantity = int(payload.get("quantity") or 1)
    except Exception:
        quantity = 1
    if quantity <= 0:
        quantity = 1

    node = db.session.get(StockNode, node_id)
    if not node:
        return jsonify(error="Item introuvable"), 404
    if node.type != NodeType.ITEM and not getattr(node, "unique_item", False):
        return jsonify(error="Seuls les items peuvent être remplacés"), 400

    batch = db.session.get(ReassortBatch, batch_id)
    if not batch or batch.quantity <= 0:
        return jsonify(error="Lot de réassort indisponible"), 404

    use_qty = min(quantity, batch.quantity)
    if use_qty <= 0:
        return jsonify(error="Quantité de réassort insuffisante"), 400

    batch.quantity -= use_qty
    batch.updated_at = datetime.utcnow()
    db.session.add(batch)

    removed_expiry: Optional[date] = None
    expiry_id = payload.get("expiry_id")
    expiry_date_raw = payload.get("expiry_date")

    if HAS_EXP_MODEL:
        _ensure_expiry_table()
        if expiry_id:
            try:
                exp = db.session.get(StockItemExpiry, int(expiry_id))  # type: ignore[arg-type]
            except Exception:
                exp = None
            if exp and exp.node_id == node_id:
                if exp.quantity and exp.quantity > use_qty:
                    exp.quantity -= use_qty
                    removed_expiry = exp.expiry_date
                    db.session.add(exp)
                else:
                    removed_expiry = exp.expiry_date
                    db.session.delete(exp)
        elif expiry_date_raw:
            try:
                exp_date = date.fromisoformat(str(expiry_date_raw))
            except Exception:
                exp_date = None
            if exp_date is not None:
                exp = (
                    StockItemExpiry.query  # type: ignore[union-attr]
                    .filter_by(node_id=node_id, expiry_date=exp_date)  # type: ignore[union-attr]
                    .order_by(StockItemExpiry.id.asc())  # type: ignore[union-attr]
                    .first()
                )
                if exp:
                    if exp.quantity and exp.quantity > use_qty:
                        exp.quantity -= use_qty
                        removed_expiry = exp.expiry_date
                        db.session.add(exp)
                    else:
                        removed_expiry = exp.expiry_date
                        db.session.delete(exp)

    new_expiry = batch.expiry_date
    if HAS_EXP_MODEL:
        if new_expiry:
            entry = StockItemExpiry(  # type: ignore[call-arg]
                node_id=node_id,
                expiry_date=new_expiry,
                quantity=use_qty,
                lot=batch.lot,
                note=batch.note,
            )
            db.session.add(entry)
        elif node.expiry_date and removed_expiry and node.expiry_date == removed_expiry:
            node.expiry_date = None

        next_date = _sync_item_expiry(node_id)
        if next_date is None and new_expiry:
            node.expiry_date = new_expiry
            db.session.add(node)

    parts = ["Remplacement via réassort"]
    if batch.item and batch.item.name:
        parts.append(f"Article: {batch.item.name}")
    if batch.lot:
        parts.append(f"Lot réassort: {batch.lot}")
    if removed_expiry:
        parts.append(f"Lot retiré: {removed_expiry.isoformat()}")
    if new_expiry:
        parts.append(f"Nouvelle exp.: {new_expiry.isoformat()}")
    if use_qty > 1:
        parts.append(f"Quantité: {use_qty}")

    comment_extra = (payload.get("comment") or "").strip() or None
    if comment_extra:
        parts.append(comment_extra)

    rec = PeriodicVerificationRecord(
        node_id=node.id,
        status=ItemStatus.OK,
        verifier_id=current_user.id,
        verifier_name=getattr(current_user, "username", None),
        comment=" | ".join(parts),
    )
    db.session.add(rec)
    db.session.commit()

    return jsonify(
        {
            "ok": True,
            "node_id": node.id,
            "batch_id": batch.id,
            "quantity": use_qty,
            "new_expiry": new_expiry.isoformat() if new_expiry else None,
            "remaining_batch": batch.quantity,
        }
    )
