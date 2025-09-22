from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_required, current_user
from .models import db, Item, Event, EventItem, Verification, ROLE_ADMIN, ROLE_CHEF
from datetime import datetime

events_bp = Blueprint('events', __name__)

def is_admin_or_chef():
    return current_user.is_authenticated and current_user.role in (ROLE_ADMIN, ROLE_CHEF)

@events_bp.route('/')
@login_required
def list_events():
    if not is_admin_or_chef():
        return redirect(url_for('index'))
    events = Event.query.order_by(Event.created_at.desc()).all()
    return render_template('events/list.html', events=events)

@events_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_event():
    if not is_admin_or_chef():
        return redirect(url_for('events.list_events'))
    if request.method == 'POST':
        title = request.form.get('title')
        date = request.form.get('date')
        location = request.form.get('location')
        parent_ids = request.form.getlist('parent_ids')
        ev = Event(title=title, date=datetime.fromisoformat(date) if date else datetime.utcnow(),
                   location=location, chef_id=current_user.id)
        db.session.add(ev)
        db.session.flush()
        # Only parents are selectable; add them to EventItem
        for pid in parent_ids:
            it = Item.query.get(int(pid))
            if it and it.is_parent:
                db.session.add(EventItem(event_id=ev.id, item_id=it.id))
        db.session.commit()
        flash('Évènement créé', 'success')
        return redirect(url_for('events.view_event', event_id=ev.id))
    parents = Item.query.filter_by(is_parent=True).all()
    return render_template('events/create.html', parents=parents)

@events_bp.route('/<int:event_id>')
@login_required
def view_event(event_id):
    ev = Event.query.get_or_404(event_id)
    parent_items = [ei.item for ei in ev.event_items]
    return render_template('events/detail.html', ev=ev, parents=parent_items)

@events_bp.route('/token/<token>', methods=['GET', 'POST'])
def token_entry(token):
    ev = Event.query.filter_by(token=token).first_or_404()
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        if not full_name:
            flash('Nom et prénom requis', 'warning')
            return redirect(url_for('events.token_entry', token=token))
        session['volunteer_name'] = full_name
        session['event_token'] = token
        return redirect(url_for('events.verify', token=token))
    return render_template('events/token_entry.html', ev=ev)

@events_bp.route('/token/<token>/verify')
def verify(token):
    ev = Event.query.filter_by(token=token).first_or_404()
    if session.get('event_token') != token or not session.get('volunteer_name'):
        return redirect(url_for('events.token_entry', token=token))
    # Build hierarchical list: parents and their children
    parents = [ei.item for ei in ev.event_items]
    data = []
    for p in parents:
        children = p.children
        data.append((p, children))
    return render_template('events/verify.html', ev=ev, data=data)

# ---- AJAX APIs ----

@events_bp.route('/api/<int:event_id>/status')
def api_status(event_id):
    ev = Event.query.get_or_404(event_id)
    verifs = Verification.query.filter_by(event_id=ev.id).all()
    verified_ids = {v.item_id for v in verifs}
    loaded = {ei.item_id: ei.loaded for ei in ev.event_items}
    return jsonify({
        'verified': list(verified_ids),
        'loaded': loaded,
        'verifications': [
            {'item_id': v.item_id, 'by': v.verified_by, 'at': v.verified_at.isoformat()}
            for v in verifs
        ]
    })

@events_bp.route('/api/<token>/verify', methods=['POST'])
def api_verify(token):
    ev = Event.query.filter_by(token=token).first_or_404()
    name = session.get('volunteer_name')
    if not name:
        return jsonify({'ok': False, 'error': 'not_authenticated'}), 401
    item_id = int(request.json.get('item_id'))
    if not Item.query.get(item_id):
        return jsonify({'ok': False, 'error': 'bad_item'}), 400
    # Prevent duplicate verification for same item by the same person at the exact moment (allow multiple verifiers overall)
    v = Verification(event_id=ev.id, item_id=item_id, verified_by=name)
    db.session.add(v)
    db.session.commit()
    return jsonify({'ok': True})

@events_bp.route('/api/<int:event_id>/load', methods=['POST'])
@login_required
def api_load(event_id):
    ev = Event.query.get_or_404(event_id)
    if not is_admin_or_chef():
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    item_id = int(request.json.get('item_id'))
    loaded = bool(request.json.get('loaded'))
    ei = EventItem.query.filter_by(event_id=ev.id, item_id=item_id).first()
    if not ei:
        return jsonify({'ok': False, 'error': 'not_in_event'}), 400
    ei.loaded = loaded
    db.session.commit()
    return jsonify({'ok': True, 'loaded': loaded})

@events_bp.route('/link/<int:event_id>')
@login_required
def event_link(event_id):
    ev = Event.query.get_or_404(event_id)
    if not is_admin_or_chef():
        return redirect(url_for('events.list_events'))
    return render_template('events/link.html', ev=ev)
