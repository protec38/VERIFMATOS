
from datetime import datetime
from app.extensions import db
from app.models import EventItem, InventoryNode
from .logs import log_action

def update_check(event_id: int, node_id: int, checked: bool, current_user):
    item = EventItem.query.filter_by(event_id=event_id, node_id=node_id).first()
    if not item:
        raise ValueError('Item not linked to event')
    item.state = 'checked' if checked else 'pending'
    item.checked_by = getattr(current_user, 'id', None) if checked else None
    item.checked_at = datetime.utcnow() if checked else None
    db.session.add(item)
    db.session.commit()
    log_action('NODE_CHECKED' if checked else 'NODE_UNCHECKED', user_id=getattr(current_user,'id', None), event_id=event_id, target_node_id=node_id)
    return build_parent_progress(event_id, node_id)

def build_parent_progress(event_id: int, node_id: int):
    # compute progress for all ancestors including root, using path prefix
    node = InventoryNode.query.get(node_id)
    if not node:
        return {}
    # We assume path like /A/B/C where C is node_id; we will iterate ancestors by slicing path
    path_ids = [int(x) for x in node.path.strip('/').split('/') if x]
    progress = {}
    from app.models import InventoryNode as IN, EventItem as EI
    for aid in path_ids:
        parent = IN.query.get(aid)
        if not parent:
            continue
        # collect leaf nodes under this parent by path prefix
        prefix = (parent.path or f"/{parent.id}").rstrip('/') + '/'
        # subquery to get all leaves under parent
        leaves = IN.query.filter(IN.is_leaf.is_(True), IN.path.like(f"{prefix}%")).all()
        if not leaves:
            progress[parent.id] = 1.0
            continue
        leaf_ids = [l.id for l in leaves]
        total = EI.query.filter(EI.event_id==event_id, EI.node_id.in_(leaf_ids), EI.include.is_(True)).count()
        if total == 0:
            progress[parent.id] = 0.0
            continue
        done = EI.query.filter(EI.event_id==event_id, EI.node_id.in_(leaf_ids), EI.include.is_(True), EI.state=='checked').count()
        progress[parent.id] = done / total
    return progress
