
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Event, EventItem, InventoryNode, ActivityLog
from app.guards import roles_required
from app.services.logs import log_action
from app.services.validation import update_check, build_parent_progress
from app.services.tree import build_event_tree
from app.extensions import socketio

bp = Blueprint('events', __name__)

@bp.get('/')
@login_required
def list_events():
    events = Event.query.order_by(Event.created_at.desc()).all()
    return jsonify([{
        'id': e.id, 'title': e.title, 'date': e.event_date.isoformat() if e.event_date else None,
        'location': e.location, 'status': e.status, 'share_token': e.share_token
    } for e in events])

@bp.post('/')
@roles_required('admin','chef')
def create_event():
    data = request.get_json() or {}
    e = Event(
        title=data.get('title'),
        event_date=data.get('event_date'),
        location=data.get('location'),
        status='draft',
        share_token=data.get('share_token'),
        created_by=getattr(current_user,'id', None)
    )
    db.session.add(e)
    db.session.commit()
    return jsonify(id=e.id, share_token=e.share_token), 201

@bp.get('/<int:event_id>')
@login_required
def get_event(event_id):
    e = Event.query.get_or_404(event_id)
    return jsonify(id=e.id, title=e.title, date=e.event_date.isoformat() if e.event_date else None,
                   location=e.location, status=e.status, share_token=e.share_token)

@bp.patch('/<int:event_id>')
@roles_required('admin','chef')
def update_event(event_id):
    e = Event.query.get_or_404(event_id)
    data = request.get_json() or {}
    for k in ['title','event_date','location','status','share_token']:
        if k in data:
            setattr(e, k, data[k])
    db.session.commit()
    log_action('EVENT_UPDATE', user_id=getattr(current_user,'id', None), event_id=e.id, details={'fields': list(data.keys())})
    return jsonify(message='ok')

@bp.delete('/<int:event_id>')
@roles_required('admin','chef')
def delete_event(event_id):
    e = Event.query.get_or_404(event_id)
    db.session.delete(e)
    db.session.commit()
    return jsonify(message='deleted')

@bp.post('/<int:event_id>/select')
@roles_required('admin','chef')
def select_nodes(event_id):
    data = request.get_json() or {}
    node_ids = data.get('node_ids', [])
    include = bool(data.get('include', True))
    for nid in node_ids:
        item = EventItem.query.filter_by(event_id=event_id, node_id=nid).first()
        if not item:
            item = EventItem(event_id=event_id, node_id=nid)
        item.include = include
        # if leaf, default required_qty from inventory expected_qty
        node = InventoryNode.query.get(nid)
        if node and node.is_leaf and item.required_qty is None:
            item.required_qty = node.expected_qty
        db.session.add(item)
    db.session.commit()
    log_action('EVENT_SELECT_UPDATE', user_id=current_user.id, event_id=event_id, details={'node_ids': node_ids, 'include': include})
    return jsonify(message='ok')

@bp.get('/<int:event_id>/items')
@login_required
def get_items(event_id):
    tree = build_event_tree(event_id)
    return jsonify(tree)

@bp.post('/<int:event_id>/items/<int:node_id>/check')
@login_required
def check_item(event_id, node_id):
    data = request.get_json() or {}
    checked = bool(data.get('checked', True))
    progress = update_check(event_id, node_id, checked, current_user)
    # emit realtime update
    socketio.emit('item:checked', {
        'node_id': node_id,
        'checked': checked,
        'checked_by': getattr(current_user, 'display_name', 'unknown'),
        'progress': progress
    }, to=f'event:{event_id}')
    return jsonify(message='ok', progress=progress)

@bp.post('/<int:event_id>/status')
@roles_required('admin','chef')
def set_status(event_id):
    e = Event.query.get_or_404(event_id)
    data = request.get_json() or {}
    status = data.get('status')
    if status not in ('draft','preparing','validated'):
        return jsonify(error='invalid status'), 400
    e.status = status
    db.session.commit()
    socketio.emit('event:status_changed', {'status': status}, to=f'event:{event_id}')
    log_action('EVENT_STATUS_UPDATE', user_id=current_user.id, event_id=event_id, details={'status': status})
    return jsonify(message='ok')

@bp.get('/<int:event_id>/logs')
@login_required
def logs(event_id):
    logs = ActivityLog.query.filter_by(event_id=event_id).order_by(ActivityLog.created_at.desc()).limit(200).all()
    return jsonify([{
        'id': l.id, 'action': l.action, 'user_id': l.user_id, 'node_id': l.target_node_id,
        'details': l.details, 'created_at': l.created_at.isoformat() if l.created_at else None
    } for l in logs])
