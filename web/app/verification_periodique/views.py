"""Periodic verification endpoints."""
from __future__ import annotations

from typing import Any, Dict, List

from flask import Blueprint, jsonify, request, abort
from flask_login import current_user, login_required

from .. import db
from ..models import (
    Role,
    StockNode,
    NodeType,
    PeriodicVerificationRecord,
    ItemStatus,
    IssueCode,
)
from ..tree_query import tree_stats

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
