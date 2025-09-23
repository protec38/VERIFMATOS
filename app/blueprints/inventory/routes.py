from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from ...models import InventoryNode, Event, EventItem, ActivityLog, Role
from ...extensions import db, socketio
from sqlalchemy import or_
from datetime import datetime

bp = Blueprint('inventory', __name__)

@bp.get('/tree')
@login_required
def tree():
    roots = InventoryNode.query.filter_by(parent_id=None).order_by(InventoryNode.position).all()
    return render_template('inventory/tree.html', roots=roots)

def _serialize_node(n):
    return {
        "id": n.id, "name": n.name, "is_leaf": n.is_leaf, "expected_qty": n.expected_qty,
        "icon": n.icon, "parent_id": n.parent_id, "position": n.position
    }

@bp.post('/nodes')
@login_required
def create_node():
    name = request.form['name']
    parent_id = request.form.get('parent_id')
    is_leaf = bool(request.form.get('is_leaf'))
    expected_qty = request.form.get('expected_qty')
    node = InventoryNode(
        name=name, parent_id=parent_id or None, is_leaf=is_leaf,
        expected_qty=int(expected_qty) if expected_qty else None
    )
    db.session.add(node); db.session.commit()
    flash("Noeud créé", "success")
    return redirect(url_for('inventory.tree'))

@bp.get('/event/<int:event_id>')
@login_required
def event_inventory(event_id):
    event = Event.query.get_or_404(event_id)
    # Fetch items for the event; include nodes
    items = db.session.query(EventItem, InventoryNode).join(InventoryNode, EventItem.node_id==InventoryNode.id)            .filter(EventItem.event_id==event_id, EventItem.include==True).all()
    return render_template('inventory/event_check.html', event=event, items=items)

@bp.post('/event/<int:event_id>/check')
@login_required
def check_item(event_id):
    item_id = int(request.form['item_id'])
    state = request.form.get('state', 'checked')
    ei = EventItem.query.get_or_404(item_id)
    ei.state = state
    ei.checked_by = current_user.id
    ei.checked_at = datetime.utcnow()
    db.session.add(ei)
    db.session.add(ActivityLog(user_id=current_user.id, event_id=event_id, action="item_checked",
                               target_node_id=ei.node_id, details={"state": state}))
    db.session.commit()
    payload = {"item_id": ei.id, "state": ei.state, "checked_by": current_user.display_name or current_user.email}
    socketio.emit("item_update", payload, to=f"event_{event_id}")
    return jsonify({"ok": True, **payload})
