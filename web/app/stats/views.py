# app/stats/views.py — Endpoints de statistiques d'événement
from __future__ import annotations
from flask import Blueprint, jsonify
from flask_login import login_required, current_user
from ..models import Role
from ..reports.utils import compute_summary, build_event_tree, latest_verifications

bp = Blueprint("stats", __name__)

def require_view():
    return current_user.is_authenticated and current_user.role in (Role.ADMIN, Role.CHEF, Role.VIEWER)

@bp.get("/events/<int:event_id>/stats")
@login_required
def event_stats(event_id: int):
    if not require_view():
        return jsonify(error="Forbidden"), 403
    return jsonify(compute_summary(event_id))

@bp.get("/events/<int:event_id>/latest")
@login_required
def event_latest(event_id: int):
    if not require_view():
        return jsonify(error="Forbidden"), 403
    data = latest_verifications(event_id)
    # jsonify friendly
    out = {nid: {
        "status": v["status"],
        "verifier_name": v["verifier_name"],
        "comment": v["comment"],
        "created_at": v["created_at"].isoformat() if v.get("created_at") else None
    } for nid, v in data.items()}
    return jsonify(out)
