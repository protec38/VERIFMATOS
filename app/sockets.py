
from datetime import datetime
from flask_login import current_user
from flask_socketio import join_room, emit
from app.extensions import socketio, db
from app.models import Presence
from app.services.validation import update_check

@socketio.on('join_event')
def join_event(data):
    event_id = data.get('event_id')
    if not event_id:
        return
    join_room(f'event:{event_id}')

@socketio.on('presence:ping')
def presence_ping(data):
    event_id = data.get('event_id')
    if not event_id or not getattr(current_user, 'id', None):
        return
    # upsert presence
    p = Presence.query.filter_by(event_id=event_id, user_id=current_user.id).first()
    if not p:
        p = Presence(event_id=event_id, user_id=current_user.id)
    p.last_seen_at = datetime.utcnow()
    db.session.add(p)
    db.session.commit()
    # broadcast simplified presence (for V1 we just tell that someone pinged)
    emit('presence:update', {'user_id': current_user.id, 'last_seen_at': p.last_seen_at.isoformat()}, to=f'event:{event_id}')

@socketio.on('item:check')
def ws_item_check(data):
    event_id = data.get('event_id')
    node_id = data.get('node_id')
    checked = bool(data.get('checked', True))
    progress = update_check(event_id, node_id, checked, current_user)
    emit('item:checked', {
        'node_id': node_id,
        'checked': checked,
        'checked_by': getattr(current_user,'display_name','unknown'),
        'progress': progress
    }, to=f'event:{event_id}')
