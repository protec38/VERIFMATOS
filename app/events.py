from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session, send_file
from flask_login import login_required, current_user
from .models import db, Item, Event, EventItem, Verification, Activity, ROLE_ADMIN, ROLE_CHEF
from datetime import datetime
import csv, io
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

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
        for pid in parent_ids:
            it = Item.query.get(int(pid))
            if it and it.is_parent:
                db.session.add(EventItem(event_id=ev.id, item_id=it.id))
                # precreate verification rows for all children
                for child in it.children:
                    if not Verification.query.filter_by(event_id=ev.id, item_id=child.id).first():
                        db.session.add(Verification(event_id=ev.id, item_id=child.id, verified=False))
        db.session.commit()
        flash('Évènement créé', 'success')
        return redirect(url_for('events.view_event', event_id=ev.id))
    parents = Item.query.filter_by(is_parent=True).all()
    return render_template('events/create.html', parents=parents)

@events_bp.route('/<int:event_id>')
@login_required
def view_event(event_id):
    ev = Event.query.get_or_404(event_id)
    parents = [ei.item for ei in ev.event_items]
    return render_template('events/detail.html', ev=ev, parents=parents)

@events_bp.route('/link/<int:event_id>')
@login_required
def event_link(event_id):
    ev = Event.query.get_or_404(event_id)
    if not is_admin_or_chef():
        return redirect(url_for('events.list_events'))
    return render_template('events/link.html', ev=ev)

# ---- public token flow ----
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
    parents = [ei.item for ei in ev.event_items]
    data = [(p, p.children) for p in parents]
    return render_template('events/verify.html', ev=ev, data=data)

# ---- AJAX APIs ----

def _status_payload(ev):
    verifs = Verification.query.filter_by(event_id=ev.id).all()
    vmap = {v.item_id: v for v in verifs}
    parents = [ei.item for ei in ev.event_items]
    parents_status = {}
    for p in parents:
        child_ids = [c.id for c in p.children]
        parents_status[p.id] = all(vmap.get(cid) and vmap[cid].verified for cid in child_ids) if child_ids else False
    loaded = {ei.item_id: ei.loaded for ei in ev.event_items}
    history = Activity.query.filter_by(event_id=ev.id).order_by(Activity.at.desc()).limit(100).all()
    return {
        'verifications': {str(v.item_id): {'verified': v.verified, 'by': v.last_by, 'at': v.last_at.isoformat() if v.last_at else None} for v in verifs},
        'parents_complete': parents_status,
        'loaded': loaded,
        'history': [{'action': h.action, 'item_id': h.item_id, 'actor': h.actor, 'at': h.at.isoformat()} for h in history]
    }

@events_bp.route('/api/<int:event_id>/status')
def api_status(event_id):
    ev = Event.query.get_or_404(event_id)
    return jsonify(_status_payload(ev))

@events_bp.route('/api/token/<token>/status')
def api_status_token(token):
    ev = Event.query.filter_by(token=token).first_or_404()
    return jsonify(_status_payload(ev))

@events_bp.route('/api/<token>/verify', methods=['POST'])
def api_verify(token):
    ev = Event.query.filter_by(token=token).first_or_404()
    name = session.get('volunteer_name')
    if not name:
        return jsonify({'ok': False, 'error': 'not_authenticated'}), 401
    data = request.get_json() or {}
    item_id = int(data.get('item_id'))
    state = bool(data.get('verified'))
    v = Verification.query.filter_by(event_id=ev.id, item_id=item_id).first()
    if not v:
        v = Verification(event_id=ev.id, item_id=item_id, verified=state, last_by=name, last_at=datetime.utcnow())
        db.session.add(v)
    else:
        v.verified = state
        v.last_by = name
        v.last_at = datetime.utcnow()
    db.session.add(Activity(event_id=ev.id, actor=name, action='verify' if state else 'unverify', item_id=item_id))
    db.session.commit()
    return jsonify({'ok': True})

@events_bp.route('/api/<int:event_id>/load', methods=['POST'])
@login_required
def api_load(event_id):
    ev = Event.query.get_or_404(event_id)
    if not is_admin_or_chef():
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    item_id = int((request.get_json() or {}).get('item_id'))
    loaded = bool((request.get_json() or {}).get('loaded'))
    ei = EventItem.query.filter_by(event_id=ev.id, item_id=item_id).first()
    if not ei:
        return jsonify({'ok': False, 'error': 'not_in_event'}), 400
    ei.loaded = loaded
    db.session.add(Activity(event_id=ev.id, actor=current_user.username, action='load' if loaded else 'unload', item_id=item_id))
    db.session.commit()
    return jsonify({'ok': True, 'loaded': loaded})

# ---- Exports (CSV/PDF) unchanged ----
@events_bp.route('/<int:event_id>/export.csv')
@login_required
def export_csv(event_id):
    ev = Event.query.get_or_404(event_id)
    si = io.StringIO()
    cw = csv.writer(si, delimiter=';')
    cw.writerow(['Event', ev.title, ev.date.isoformat(), ev.location or ''])
    cw.writerow([])
    cw.writerow(['ItemID','Parent','Child','ExpectedQty','Verified','By','At','LoadedParent'])
    parents = [ei.item for ei in ev.event_items]
    loaded_map = {ei.item_id: ei.loaded for ei in ev.event_items}
    for p in parents:
        for c in p.children:
            v = Verification.query.filter_by(event_id=ev.id, item_id=c.id).first()
            cw.writerow([c.id, p.name, c.name, c.expected_qty, (v.verified if v else False), (v.last_by if v else ''), (v.last_at.isoformat() if v and v.last_at else ''), loaded_map.get(p.id, False)])
    mem = io.BytesIO(si.getvalue().encode('utf-8'))
    mem.seek(0)
    return send_file(mem, mimetype='text/csv', as_attachment=True, download_name=f"event_{ev.id}.csv")

@events_bp.route('/<int:event_id>/export.pdf')
@login_required
def export_pdf(event_id):
    ev = Event.query.get_or_404(event_id)
    mem = io.BytesIO()
    p = canvas.Canvas(mem, pagesize=A4)
    width, height = A4
    y = height - 40
    p.setFont("Helvetica-Bold", 14)
    p.drawString(40, y, f"Évènement #{ev.id} — {ev.title}")
    y -= 18
    p.setFont("Helvetica", 10)
    p.drawString(40, y, f"Date: {ev.date.strftime('%d/%m/%Y %H:%M')}  Lieu: {ev.location or '—'}")
    y -= 20
    parents = [ei.item for ei in ev.event_items]
    for parent in parents:
        if y < 60: p.showPage(); y = height - 40
        p.setFont("Helvetica-Bold", 12); p.drawString(40, y, f"Parent: {parent.name}"); y -= 14
        for child in parent.children:
            v = Verification.query.filter_by(event_id=ev.id, item_id=child.id).first()
            if y < 60: p.showPage(); y = height - 40
            status = "OK" if (v and v.verified) else "—"
            p.setFont("Helvetica", 10)
            p.drawString(60, y, f"- {child.name} (x{child.expected_qty})  [{status}]  {v.last_by if v and v.last_by else ''}")
            y -= 12
        y -= 6
    p.showPage(); p.save(); mem.seek(0)
    return send_file(mem, mimetype='application/pdf', as_attachment=True, download_name=f"event_{ev.id}.pdf")
