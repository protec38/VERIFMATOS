# app/stock/views.py — API hiérarchie de stock + péremptions multiples
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from flask import Blueprint, request, jsonify, Response, render_template, abort
from flask_login import login_required, current_user

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError, OperationalError

from .. import db
from ..models import Role, NodeType, StockNode
from .service import (
    create_node,
    update_node,
    delete_node,
    duplicate_subtree,
    serialize_tree,
    list_roots,
)

# --- modèle optionnel (si présent dans app.models) ---
try:
    # Nouveau modèle pour lots/ dates multiples
    from ..models import StockItemExpiry  # type: ignore
    HAS_EXP_MODEL = True
except Exception:
    StockItemExpiry = None  # type: ignore
    HAS_EXP_MODEL = False


def _sync_item_legacy_expiry(item: Optional[StockNode]) -> Dict[str, Any]:
    """Synchronise la colonne héritée ``expiry_date`` avec les lots multiples.

    Retourne également un petit résumé (compte, prochaine date) pour éviter de
    recalculer ces informations plusieurs fois dans les routes.
    """

    if not HAS_EXP_MODEL or not item or item.type != NodeType.ITEM:
        return {"count": 0, "next": None}

    rows: List[StockItemExpiry] = (  # type: ignore[misc]
        StockItemExpiry.query
        .filter_by(node_id=item.id)
        .order_by(StockItemExpiry.expiry_date.asc(), StockItemExpiry.id.asc())
        .all()
    )

    next_date: Optional[date] = rows[0].expiry_date if rows else None
    item.expiry_date = next_date
    # Flush pour s'assurer que l'UI (tree JSON) voit la mise à jour.
    db.session.flush()
    return {"count": len(rows), "next": next_date}

bp = Blueprint("stock", __name__)


# -------------------------------------------------
# Droits
# -------------------------------------------------
def _can_read_stock() -> bool:
    # ✅ toute personne connectée peut LIRE (utile pour "Créer évènement")
    return current_user.is_authenticated


def _can_write_stock() -> bool:
    # ✍️ seules ces personnes peuvent MODIFIER
    return current_user.is_authenticated and current_user.role in (Role.ADMIN, Role.CHEF)


def _bad_request(msg: str, code: int = 400):
    return jsonify(error=msg), code


def _parse_node_type(x: str) -> NodeType:
    x = (x or "").strip().upper()
    if x not in ("GROUP", "ITEM"):
        raise ValueError("type must be GROUP or ITEM")
    return NodeType[x]


def _parse_iso_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    return date.fromisoformat(s)


# -------------------------------------------------
# Sécurité: créer la table des péremptions si manquante (lors 1er accès)
# -------------------------------------------------
def _ensure_expiry_table() -> bool:
    """
    Évite les 500 "relation stock_item_expiries does not exist" si la migration n’a
    pas été jouée. On crée la table minimale côté Postgres si besoin.
    """
    if not HAS_EXP_MODEL:
        return False
    try:
        db.session.execute(text("SELECT 1 FROM stock_item_expiries LIMIT 1"))
        return True
    except (ProgrammingError, OperationalError):
        # Table absente → on la crée
        db.session.rollback()
        ddl = """
        CREATE TABLE IF NOT EXISTS stock_item_expiries (
            id SERIAL PRIMARY KEY,
            node_id INTEGER NOT NULL REFERENCES stock_nodes(id) ON DELETE CASCADE,
            expiry_date DATE NOT NULL,
            quantity INTEGER NULL,
            lot VARCHAR(64) NULL,
            note TEXT NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW() NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_stock_item_expiries_node ON stock_item_expiries(node_id);
        CREATE INDEX IF NOT EXISTS ix_stock_item_expiries_date ON stock_item_expiries(expiry_date);
        """
        for stmt in ddl.strip().split(";"):
            if stmt.strip():
                db.session.execute(text(stmt))
        db.session.commit()
        return True
    except Exception:
        db.session.rollback()
        return False


# -------------------------------------------------
# ROOTS (lecture ouverte aux connectés)
# -------------------------------------------------
@bp.get("/stock/roots")
@login_required
def get_roots():
    if not _can_read_stock():
        return _bad_request("Forbidden", 403)
    roots = list_roots()
    return jsonify([
        {"id": r.id, "name": r.name, "type": r.type.name, "level": r.level}
        for r in roots
    ])


# -------------------------------------------------
# TREE (accepte id racine OU enfant, remonte à la racine) — lecture
# -------------------------------------------------
@bp.get("/stock/tree")
@login_required
def get_tree():
    if not _can_read_stock():
        return _bad_request("Forbidden", 403)
    try:
        node_id = int(request.args.get("root_id") or 0)
    except Exception:
        return _bad_request("root_id invalid")

    node = db.session.get(StockNode, node_id)
    if not node:
        return _bad_request("Root not found", 404)

    # si l'id n'est pas une racine, on remonte jusqu'à la vraie racine
    while node.parent_id is not None:
        node = node.parent

    return jsonify(serialize_tree(node))


# -------------------------------------------------
# CREATE (root ou enfant) — écriture
# -------------------------------------------------
@bp.post("/stock")
@login_required
def create_node_api():
    if not _can_write_stock():
        return _bad_request("Forbidden", 403)

    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    type_str = (data.get("type") or "").strip()
    parent_id = data.get("parent_id")
    quantity = data.get("quantity")

    if not name:
        return _bad_request("name required")
    try:
        type_ = _parse_node_type(type_str)
        if parent_id is not None:
            parent_id = int(parent_id)
        if type_ == NodeType.ITEM:
            quantity = int(quantity or 0)
        else:
            quantity = None

        node = create_node(name=name, type_=type_, parent_id=parent_id, quantity=quantity)
        node = db.session.get(StockNode, node.id)

        needs_commit = False
        # rétro compat: single expiry_date (facultatif)
        expiry = _parse_iso_date(data.get("expiry_date"))
        if type_ == NodeType.ITEM and expiry:
            node.expiry_date = expiry
            needs_commit = True

        # nouveau: tableau "expiries" [{expiry_date, quantity?, lot?, note?}]
        expiries = data.get("expiries")
        if type_ == NodeType.ITEM and isinstance(expiries, list) and _ensure_expiry_table():
            for e in expiries:
                ed = _parse_iso_date((e or {}).get("expiry_date"))
                if not ed:
                    continue
                qty = e.get("quantity")
                if qty is not None:
                    qty = int(qty)
                    if qty < 0:
                        qty = 0
                db.session.add(StockItemExpiry(  # type: ignore[misc]
                    node_id=node.id,
                    expiry_date=ed,
                    quantity=qty,
                    lot=(e.get("lot") or None),
                    note=(e.get("note") or None),
                ))
            _sync_item_legacy_expiry(node)
            needs_commit = True

        if needs_commit:
            db.session.commit()

        return jsonify({
            "id": node.id, "name": node.name, "level": node.level, "type": node.type.name
        }), 201
    except ValueError as e:
        return _bad_request(str(e))
    except Exception as e:
        return _bad_request(str(e))


# -------------------------------------------------
# UPDATE (rename, reparent, qty, expiry) — écriture
# -------------------------------------------------
@bp.patch("/stock/<int:node_id>")
@login_required
def update_node_api(node_id: int):
    if not _can_write_stock():
        return _bad_request("Forbidden", 403)

    data = request.get_json() or {}
    try:
        node = db.session.get(StockNode, node_id)
        if not node:
            return _bad_request("Not found", 404)

        name = (data.get("name") or node.name).strip()
        parent_id = data.get("parent_id", node.parent_id)
        if parent_id is not None:
            parent_id = int(parent_id)

        # qty only for ITEM
        qty = data.get("quantity", node.quantity)
        if node.type == NodeType.ITEM and qty is not None:
            qty = int(qty)
        else:
            qty = None if node.type != NodeType.ITEM else node.quantity

        node = update_node(node_id=node_id, name=name, parent_id=parent_id, quantity=qty)

        needs_commit = False

        # rétro compat: single expiry_date (ITEM uniquement)
        if node.type == NodeType.ITEM and "expiry_date" in data:
            node.expiry_date = _parse_iso_date(data.get("expiry_date"))
            needs_commit = True

        # NOUVEAU (optionnel): remplacement total des expiries via "expiries"
        if node.type == NodeType.ITEM and isinstance(data.get("expiries"), list) and _ensure_expiry_table():
            # purge & recréation (simple et explicite)
            db.session.execute(text("DELETE FROM stock_item_expiries WHERE node_id = :nid"), {"nid": node.id})
            for e in data["expiries"]:
                ed = _parse_iso_date((e or {}).get("expiry_date"))
                if not ed:
                    continue
                qty = e.get("quantity")
                if qty is not None:
                    qty = int(qty)
                    if qty < 0:
                        qty = 0
                db.session.add(StockItemExpiry(  # type: ignore[misc]
                    node_id=node.id,
                    expiry_date=ed,
                    quantity=qty,
                    lot=(e.get("lot") or None),
                    note=(e.get("note") or None),
                ))
            _sync_item_legacy_expiry(node)
            needs_commit = True

        if needs_commit:
            db.session.commit()

        node = db.session.get(StockNode, node_id)  # refresh
        return jsonify({
            "id": node.id, "name": node.name, "level": node.level, "type": node.type.name
        })
    except ValueError as e:
        return _bad_request(str(e))
    except Exception as e:
        return _bad_request(str(e))


# -------------------------------------------------
# DELETE (subtree) — écriture
# -------------------------------------------------
@bp.delete("/stock/<int:node_id>")
@login_required
def delete_node_api(node_id: int):
    if not _can_write_stock():
        return _bad_request("Forbidden", 403)
    try:
        delete_node(node_id)
        return jsonify({"ok": True})
    except LookupError:
        return _bad_request("Not found", 404)
    except Exception as e:
        return _bad_request(str(e))


# -------------------------------------------------
# DUPLICATE SUBTREE — écriture
# -------------------------------------------------
@bp.post("/stock/<int:node_id>/duplicate")
@login_required
def duplicate_node_api(node_id: int):
    if not _can_write_stock():
        return _bad_request("Forbidden", 403)

    data = request.get_json() or {}
    new_name = (data.get("new_name") or "").strip()
    new_parent_id = data.get("new_parent_id")
    if not new_name:
        return _bad_request("new_name required")
    try:
        new_root = duplicate_subtree(node_id, new_name=new_name, new_parent_id=new_parent_id)
        return jsonify(
            {"id": new_root.id, "name": new_root.name, "level": new_root.level, "type": new_root.type.name}
        ), 201
    except LookupError:
        return _bad_request("Not found", 404)
    except Exception as e:
        return _bad_request(str(e))


# -------------------------------------------------
# EXPORT (JSON) — lecture
# -------------------------------------------------
@bp.get("/stock/export.json")
@login_required
def export_stock_json():
    if not _can_read_stock():
        return _bad_request("Forbidden", 403)

    roots = list_roots()

    def _serialize_tree_full(n: StockNode) -> Dict[str, Any]:
        out = {
            "name": n.name,
            "type": n.type.name,
            "quantity": n.quantity if n.type == NodeType.ITEM else None,
            # rétro compat: garde l’ancienne colonne si elle existe
            "expiry_date": n.expiry_date.isoformat() if getattr(n, "expiry_date", None) else None,
            "children": [],
        }
        # (Optionnel) tu peux ajouter ici "expiries": [...] si tu veux exporter les lots
        return out

    payload = {
        "version": "1",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "roots": [_serialize_tree_full(r) for r in roots],
    }
    return Response(
        json.dumps(payload, ensure_ascii=False, indent=2),
        mimetype="application/json; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="stock_export.json"'},
    )


# -------------------------------------------------
# IMPORT (JSON) — écriture
# -------------------------------------------------
@bp.post("/stock/import")
@login_required
def import_stock():
    if not _can_write_stock():
        return _bad_request("Forbidden", 403)

    mode = (request.args.get("mode") or request.form.get("mode") or "merge").lower().strip()

    # Récup JSON via file upload OU via body JSON
    data_obj: Optional[Dict[str, Any]] = None
    if "file" in request.files:
        try:
            data_obj = json.load(request.files["file"].stream)
        except Exception:
            return _bad_request("Invalid JSON file")
    else:
        payload = request.get_json(silent=True)
        if isinstance(payload, dict):
            data_obj = payload
        elif isinstance(payload, list):
            data_obj = {"roots": payload}
        else:
            return _bad_request("JSON body expected")

    roots = data_obj.get("roots")
    if roots is None:
        return _bad_request("Missing 'roots' array")

    if mode not in ("merge", "replace"):
        return _bad_request("mode must be 'merge' or 'replace'")

    try:
        if mode == "replace":
            # suppression complète du stock
            all_nodes = db.session.query(StockNode).all()
            for n in reversed(all_nodes):
                db.session.delete(n)
            db.session.commit()

        def create_subtree(parent_id: Optional[int], node_dict: Dict[str, Any]) -> StockNode:
            name = (node_dict.get("name") or "").strip()
            if not name:
                raise ValueError("node name required")
            type_ = _parse_node_type(node_dict.get("type"))
            quantity = None
            if type_ == NodeType.ITEM:
                quantity = int(node_dict.get("quantity") or 0)
            node = create_node(name=name, type_=type_, parent_id=parent_id, quantity=quantity)

            needs_flush = False
            # rétro compat: single expiry_date
            if type_ == NodeType.ITEM and node_dict.get("expiry_date"):
                node.expiry_date = _parse_iso_date(node_dict.get("expiry_date"))
                needs_flush = True

            # (optionnel) si l’import fournit "expiries"
            exps = node_dict.get("expiries")
            if type_ == NodeType.ITEM and isinstance(exps, list) and _ensure_expiry_table():
                for e in exps:
                    ed = _parse_iso_date((e or {}).get("expiry_date"))
                    if not ed:
                        continue
                    qty = e.get("quantity")
                    if qty is not None:
                        qty = int(qty)
                        if qty < 0:
                            qty = 0
                    db.session.add(StockItemExpiry(  # type: ignore[misc]
                        node_id=node.id,
                        expiry_date=ed,
                        quantity=qty,
                        lot=(e.get("lot") or None),
                        note=(e.get("note") or None),
                    ))
                _sync_item_legacy_expiry(node)
                needs_flush = True

            if needs_flush:
                db.session.flush()

            for c in node_dict.get("children") or []:
                create_subtree(node.id, c)
            return node

        created_ids: List[int] = []
        for r in roots:
            new_root = create_subtree(None, r)
            created_ids.append(new_root.id)
        db.session.commit()

        return jsonify({"ok": True, "created_roots": created_ids, "mode": mode})
    except Exception as e:
        db.session.rollback()
        return _bad_request(str(e))


# -------------------------------------------------
# Stats péremptions — lecture (navbar)
# -------------------------------------------------
@bp.get("/stats/stock/expiry/counts")
@login_required
def expiry_counts():
    """
    Compte les lignes de péremption en alerte.
    - Si la table des lots existe → on compte par "lot" (stock_item_expiries).
    - Sinon → rétro compat sur StockNode.expiry_date.
    """
    if not _can_read_stock():
        return jsonify({"expired": 0, "j30": 0})

    from datetime import date as _date
    today = _date.today()

    if _ensure_expiry_table():
        try:
            rows = db.session.execute(
                text("SELECT expiry_date FROM stock_item_expiries")
            ).all()
            expired = 0
            j30 = 0
            for (ex,) in rows:
                if not ex:
                    continue
                delta = (ex - today).days
                if delta < 0:
                    expired += 1
                elif 0 <= delta <= 30:
                    j30 += 1
            return jsonify({"expired": expired, "j30": j30})
        except Exception:
            db.session.rollback()
            # fallback soft
            pass

    # rétro compat (colonne unique)
    items = db.session.query(StockNode).filter(
        StockNode.type == NodeType.ITEM,
        StockNode.expiry_date.isnot(None)
    ).all()
    expired = 0
    j30 = 0
    for it in items:
        ex = getattr(it, "expiry_date", None)
        if not ex:
            continue
        delta = (ex - today).days
        if delta < 0:
            expired += 1
        elif 0 <= delta <= 30:
            j30 += 1
    return jsonify({"expired": expired, "j30": j30})


# ===================================================================
# ==================  NOUVELLES ROUTES PÉREMPTIONS  =================
# ===================================================================

# -------- UI dédiée pour gérer les lots d’un ITEM (facultatif) -------
@bp.get("/stock/item/<int:item_id>/expiries")
@login_required
def stock_item_expiries_page(item_id: int):
    if not _can_write_stock():
        abort(403)
    item = db.session.get(StockNode, int(item_id))
    if not item or item.type != NodeType.ITEM:
        abort(404)
    return render_template("stock_item_expiries.html", item=item)


# -------- API: lister les lots / dates d’un ITEM ---------------------
@bp.get("/stock/api/item/<int:item_id>/expiries")
@login_required
def api_list_expiries(item_id: int):
    if not _can_write_stock():
        return _bad_request("Forbidden", 403)
    if not _ensure_expiry_table():
        return jsonify([])

    item = db.session.get(StockNode, int(item_id))
    if not item or item.type != NodeType.ITEM:
        return _bad_request("Item not found", 404)

    try:
        rows: List[StockItemExpiry] = (  # type: ignore[misc]
            StockItemExpiry.query
            .filter_by(node_id=item.id)
            .order_by(StockItemExpiry.expiry_date.asc(), StockItemExpiry.id.asc())
            .all()
        )
        out = [
            {
                "id": r.id,
                "expiry_date": r.expiry_date.isoformat(),
                "quantity": r.quantity,
                "lot": r.lot,
                "note": r.note,
            }
            for r in rows
        ]
        return jsonify(out)
    except Exception as e:
        return _bad_request(str(e))


# -------- API: ajouter un lot / date sur un ITEM ---------------------
@bp.post("/stock/api/item/<int:item_id>/expiries")
@login_required
def api_add_expiry(item_id: int):
    if not _can_write_stock():
        return _bad_request("Forbidden", 403)
    if not _ensure_expiry_table():
        return _bad_request("Expiries table not available", 500)

    item = db.session.get(StockNode, int(item_id))
    if not item or item.type != NodeType.ITEM:
        return _bad_request("Item not found", 404)

    payload = request.get_json(silent=True) or {}
    date_raw = (payload.get("expiry_date") or "").strip()
    if not date_raw:
        return _bad_request("expiry_date required (YYYY-MM-DD)")

    try:
        ed = date.fromisoformat(date_raw)
    except Exception:
        return _bad_request("invalid expiry_date (YYYY-MM-DD)")

    try:
        qty = payload.get("quantity", None)
        if qty is not None:
            qty = int(qty)
            if qty < 0:
                qty = 0

        rec = StockItemExpiry(  # type: ignore[misc]
            node_id=item.id,
            expiry_date=ed,
            quantity=qty,
            lot=(payload.get("lot") or None),
            note=(payload.get("note") or None),
        )
        db.session.add(rec)
        summary = _sync_item_legacy_expiry(item)
        db.session.commit()
        next_iso = summary["next"].isoformat() if summary.get("next") else None
        return jsonify({
            "ok": True,
            "id": rec.id,
            "next_expiry": next_iso,
            "lots": summary.get("count", 0),
        })
    except Exception as e:
        db.session.rollback()
        return _bad_request(str(e))


# -------- API: supprimer un lot / date --------------------------------
@bp.delete("/stock/api/expiry/<int:exp_id>")
@login_required
def api_delete_expiry(exp_id: int):
    if not _can_write_stock():
        return _bad_request("Forbidden", 403)
    if not _ensure_expiry_table():
        return _bad_request("Expiries table not available", 500)
    try:
        rec = db.session.get(StockItemExpiry, int(exp_id))  # type: ignore[misc]
        if not rec:
            return _bad_request("Not found", 404)
        item = rec.item
        db.session.delete(rec)
        summary = _sync_item_legacy_expiry(item)
        db.session.commit()
        next_iso = summary["next"].isoformat() if summary.get("next") else None
        return jsonify({
            "ok": True,
            "next_expiry": next_iso,
            "lots": summary.get("count", 0),
        })
    except Exception as e:
        db.session.rollback()
        return _bad_request(str(e))


# -------- API: prochaine date qui expire pour un ITEM (optionnel) -----
@bp.get("/stock/api/item/<int:item_id>/next-expiry")
@login_required
def api_next_expiry(item_id: int):
    if not _can_read_stock():
        return _bad_request("Forbidden", 403)
    if not _ensure_expiry_table():
        return jsonify({"date": None, "quantity": None, "lot": None, "note": None})

    item = db.session.get(StockNode, int(item_id))
    if not item or item.type != NodeType.ITEM:
        return _bad_request("Item not found", 404)

    try:
        row = (
            StockItemExpiry.query  # type: ignore[misc]
            .filter_by(node_id=item.id)
            .order_by(StockItemExpiry.expiry_date.asc(), StockItemExpiry.id.asc())
            .first()
        )
        if not row:
            return jsonify({"date": None, "quantity": None, "lot": None, "note": None})
        return jsonify({
            "date": row.expiry_date.isoformat(),
            "quantity": row.quantity,
            "lot": row.lot,
            "note": row.note,
        })
    except Exception:
        return jsonify({"date": None, "quantity": None, "lot": None, "note": None})
