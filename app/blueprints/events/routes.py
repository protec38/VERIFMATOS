import secrets
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from ...models import Event, EventItem, InventoryNode, ActivityLog, Role
from ...extensions import db, socketio
from flask_socketio import join_room, leave_room

bp = Blueprint('events', __name__)

def can_manage():
    return current_user.is_authenticated and current_user.role in (Role.ADMIN, Role.CHEF)

@bp.get('/')
@login_required
def list_events():
    events = Event.query.order_by(Event.created_at.desc()).all()
    return render_template('events/list.html', events=events, can_manage=can_manage())

@bp.post('/')
@login_required
def create_event():
    if not can_manage():
        flash("Accès refusé", "danger")
        return redirect(url_for('events.list_events'))
    title = request.form['title']
    location = request.form.get('location')
    status = request.form.get('status', 'draft')
    share_token = secrets.token_hex(16)
    e = Event(title=title, location=location, status=status, share_token=share_token, created_by=current_user.id)
    db.session.add(e); db.session.commit()

    # Include all leaves by default
    leaves = InventoryNode.query.filter_by(is_leaf=True).all()
    db.session.add_all([EventItem(event_id=e.id, node_id=l.id, include=True, required_qty=l.expected_qty) for l in leaves])
    db.session.commit()

    flash("Événement créé", "success")
    return redirect(url_for('events.list_events'))

@bp.get('/<int:event_id>')
@login_required
def detail(event_id):
    e = Event.query.get_or_404(event_id)
    items = db.session.query(EventItem, InventoryNode).join(InventoryNode, EventItem.node_id==InventoryNode.id)            .filter(EventItem.event_id==event_id).all()
    return render_template('events/detail.html', event=e, items=items)

# Socket.IO namespace for rooms
@bp.get('/join/<int:event_id>')
@login_required
def join(event_id):
    # Room join done client-side via socket.io; here just serve page
    e = Event.query.get_or_404(event_id)
    return render_template('events/join.html', event=e)
