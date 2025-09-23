from flask import Blueprint, render_template
from flask_login import current_user
from ...models import InventoryNode, Event
bp = Blueprint('core', __name__)

@bp.get('/')
def index():
    events = Event.query.order_by(Event.created_at.desc()).limit(5).all()
    roots = InventoryNode.query.filter_by(parent_id=None).all()
    return render_template('index.html', events=events, roots=roots, user=current_user)
