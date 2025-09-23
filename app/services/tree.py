
from app.models import InventoryNode, EventItem

def build_event_tree(event_id: int):
    # Fetch all nodes linked in EventItem (both leaves and parents may exist, but we compute from inventory tree)
    nodes = InventoryNode.query.order_by(InventoryNode.position).all()
    items = { (ei.node_id): ei for ei in EventItem.query.filter_by(event_id=event_id).all() }

    # Build adjacency list
    by_parent = {}
    for n in nodes:
        by_parent.setdefault(n.parent_id, []).append(n)

    def serialize(node):
        ei = items.get(node.id)
        data = {
            'id': node.id,
            'name': node.name,
            'icon': node.icon,
            'is_leaf': node.is_leaf,
            'path': node.path,
            'position': node.position,
            'included': (ei.include if ei else False),
        }
        if node.is_leaf:
            data.update({
                'expected_qty': node.expected_qty,
                'required_qty': (ei.required_qty if ei else None),
                'state': (ei.state if ei else 'pending'),
                'checked_by': (ei.checked_by if ei else None),
                'checked_at': (ei.checked_at.isoformat() if (ei and ei.checked_at) else None),
            })
        else:
            # children recursively
            children = by_parent.get(node.id, [])
            data['children'] = [serialize(c) for c in children]
        return data

    roots = by_parent.get(None, [])
    return [serialize(r) for r in roots]
