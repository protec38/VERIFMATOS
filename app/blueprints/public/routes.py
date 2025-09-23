
from flask import Blueprint, jsonify, abort
from app.models import Event
from app.services.tree import build_event_tree

bp = Blueprint('public', __name__)

@bp.get('/<string:token>')
def public_view(token):
    e = Event.query.filter_by(share_token=token).first()
    if not e:
        return abort(404)
    tree = build_event_tree(e.id)
    # read-only public view for V1
    return jsonify({'event': {'id': e.id, 'title': e.title, 'status': e.status}, 'tree': tree})
