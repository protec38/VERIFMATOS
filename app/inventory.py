from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from .models import db, Item, ROLE_ADMIN

inventory_bp = Blueprint('inventory', __name__)

def require_admin():
    return current_user.is_authenticated and current_user.role == ROLE_ADMIN

@inventory_bp.route('/')
@login_required
def index():
    items = Item.query.filter_by(parent_id=None).all()
    return render_template('inventory/index.html', items=items)

@inventory_bp.route('/create', methods=['POST'])
@login_required
def create_item():
    if not require_admin():
        return redirect(url_for('inventory.index'))
    name = request.form.get('name')
    is_parent = request.form.get('is_parent') == 'on'
    unique_code = request.form.get('unique_code') or None
    parent_id = request.form.get('parent_id') or None
    parent_id = int(parent_id) if parent_id else None
    item = Item(name=name, is_parent=is_parent, unique_code=unique_code, parent_id=parent_id)
    db.session.add(item)
    db.session.commit()
    flash('Objet créé', 'success')
    return redirect(url_for('inventory.index'))

@inventory_bp.route('/<int:item_id>/delete', methods=['POST'])
@login_required
def delete_item(item_id):
    if not require_admin():
        return redirect(url_for('inventory.index'))
    it = Item.query.get(item_id)
    if it:
        db.session.delete(it)
        db.session.commit()
        flash('Objet supprimé', 'success')
    return redirect(url_for('inventory.index'))
