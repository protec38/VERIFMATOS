
from flask import Blueprint, request, jsonify
from flask_login import login_required
from app.extensions import db
from app.models import InventoryNode
from app.guards import roles_required

bp = Blueprint('inventory', __name__)

def _update_path(node):
    # recompute path from parent
    if node.parent_id:
        parent = InventoryNode.query.get(node.parent_id)
        prefix = (parent.path or '').rstrip('/')
        node.path = f"{prefix}/{node.id}"
    else:
        node.path = f"/{node.id}"

@bp.get('/')
@login_required
def list_root():
    parent_id = request.args.get('parent_id', type=int)
    if parent_id:
        nodes = InventoryNode.query.filter_by(parent_id=parent_id).order_by(InventoryNode.position).all()
    else:
        nodes = InventoryNode.query.filter_by(parent_id=None).order_by(InventoryNode.position).all()
    return jsonify([{
        'id': n.id, 'parent_id': n.parent_id, 'name': n.name, 'is_leaf': n.is_leaf,
        'expected_qty': n.expected_qty, 'icon': n.icon, 'path': n.path, 'position': n.position
    } for n in nodes])

@bp.post('/')
@roles_required('admin','chef')
def create_node():
    data = request.get_json() or {}
    node = InventoryNode(
        parent_id=data.get('parent_id'),
        name=data.get('name'),
        is_leaf=bool(data.get('is_leaf', False)),
        expected_qty=data.get('expected_qty'),
        icon=data.get('icon'),
        position=data.get('position', 0),
    )
    db.session.add(node)
    db.session.flush()  # to get id
    _update_path(node)
    db.session.commit()
    return jsonify(id=node.id, path=node.path), 201

@bp.patch('/<int:node_id>')
@roles_required('admin','chef')
def update_node(node_id):
    node = InventoryNode.query.get_or_404(node_id)
    data = request.get_json() or {}
    for attr in ['name','is_leaf','expected_qty','icon','position']:
        if attr in data:
            setattr(node, attr, data[attr])
    if 'parent_id' in data:
        node.parent_id = data['parent_id']
    db.session.flush()
    _update_path(node)
    db.session.commit()
    return jsonify(message='ok')

@bp.delete('/<int:node_id>')
@roles_required('admin','chef')
def delete_node(node_id):
    node = InventoryNode.query.get_or_404(node_id)
    # simple recursive delete
    def _delete(n):
        for c in list(n.children):
            _delete(c)
        db.session.delete(n)
    _delete(node)
    db.session.commit()
    return jsonify(message='deleted')
