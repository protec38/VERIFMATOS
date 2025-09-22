from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session, send_file
from flask_login import login_required, current_user
from .models import db, Item, Event, EventItem, EventChild, Verification, Activity, Presence, ROLE_ADMIN, ROLE_CHEF
from datetime import datetime, timedelta
import io, csv
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

events_bp = Blueprint('events', __name__)

def is_admin_or_chef():
    return current_user.is_authenticated and current_user.role in (ROLE_ADMIN, ROLE_CHEF)

# ---------------- LIST / CREATE ----------------
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
        parent_ids = [int(x) for x in request.form.getlist('parent_ids')]

        ev = Event(
            title=title,
            date=datetime.fromisoformat(date) if date else datetime.utcnow(),
            location=location,
            chef_id=current_user.id,
            state='in_progress'
        )
        db.session.add(ev)
        db.session.flush()

        for pid in parent_ids:
            p = Item.query.get(pid)
            if p and p.is_parent:
                db.session.add(EventItem(event_id=ev.id, item_id=p.id))
                for child in p.children:
                    db.session.add(EventChild(event_id=ev.id, parent_id=p.id, child_id=child.id, included=True))
                    db.session.add(Verification(event_id=ev.id, item_id=child.id, verified=False))
        db.session.commit()
        flash('Évènement créé', 'success')
        return redirect(url_for('events.view_event', event_id=ev.id))

    parents = Item.query.filter_by(is_parent=True).order_by(Item.name.asc()).all()
    return render_template('events/create.html', parents=parents)

# ---------------- EDIT PARENTS / CHILDREN ----------------
@events_bp.route('/<int:event_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_event(event_id):
    ev = Event.query.get_or_404(event_id)
    if not is_admin_or_chef():
        return redirect(url_for('events.list_events'))
    if ev.state == 'closed':
        flash('Évènement clôturé — modification interdite.', 'warning')
        return redirect(url_for('events.view_event', event_id=ev.id))

    if request.method == 'POST':
        new_parents = set(int(x) for x in request.form.getlist('parent_ids'))
        old_parents = set(ei.item_id for ei in ev.event_items)

        # add new
        for pid in new_parents - old_parents:
            p = Item.query.get(pid)
            if p and p.is_parent:
                db.session.add(EventItem(event_id=ev.id, item_id=p.id))
                for child in p.children:
                    if not EventChild.query.filter_by(event_id=ev.id, child_id=child.id).first():
                        db.session.add(EventChild(event_id=ev.id, parent_id=p.id, child_id=child.id, included=True))
                    if not Verification.query.filter_by(event_id=ev.id, item_id=child.id).first():
                        db.session.add(Verification(event_id=ev.id, item_id=child.id, verified=False))

        # remove
        for pid in old_parents - new_parents:
            ei = EventItem.query.filter_by(event_id=ev.id, item_id=pid).first()
            if ei:
                db.session.delete(ei)
            for ec in EventChild.query.filter_by(event_id=ev.id, parent_id=pid).all():
                db.session.delete(ec)

        db.session.commit()
        flash('Parents mis à jour', 'success')
        return redirect(url_for('events.edit_children', event_id=ev.id))

    parents = Item.query.filter_by(is_parent=True).order_by(Item.name.asc()).all()
    selected = set(ei.item_id for ei in ev.event_items)
    return render_template('events/edit_parents.html', ev=ev, parents=parents, selected=selected)

@events_bp.route('/<int:event_id>/children', methods=['GET', 'POST'])
@login_required
def edit_children(event_id):
    ev = Event.query.get_or_404(event_id)
    if not is_admin_or_chef():
        return redirect(url_for('events.list_events'))
    if ev.state == 'closed':
        flash('Évènement clôturé — modification interdite.', 'warning')
        return redirect(url_for('events.view_event', event_id=ev.id))

    if request.method == 'POST':
        included_ids = set(int(x) for x in request.form.getlist('child_ids'))
        ecs = EventChild.query.filter_by(event_id=ev.id).all()
        for ec in ecs:
            ec.included = (ec.child_id in included_ids)
        db.session.commit()
        flash('Enfants mis à jour', 'success')
        return redirect(url_for('events.view_event', event_id=ev.id))

    parents = [ei.item for ei in ev.event_items]
    tree = []
    for p in parents:
        rows = []
        for c in p.children:
            ec = EventChild.query.filter_by(event_id=ev.id, child_id=c.id).first()
            if not ec:
                ec = EventChild(event_id=ev.id, parent_id=p.id, child_id=c.id, included=True)
                db.session.add(ec)
                db.session.commit()
            rows.append((c, ec.included))
        tree.append((p, rows))
    return render_template('events/edit_children.html', ev=ev, tree=tree)

# ---------------- VIEW / SHARE ----------------
@events_bp.route('/<int:event_id>')
@login_required
def view_event(event_id):
    ev = Event.query.get_or_404(event_id)
    parents = [ei.item for ei in ev.event_items]
    tree = []
    for p in parents:
        included_children = []
        for c in p.children:
            ec = EventChild.query.filter_by(event_id=ev.id, child_id=c.id).first()
            if ec and ec.included:
                included_children.append(c)
        tree.append((p, included_children))
    return render_template('events/detail.html', ev=ev, tree=tree)

@events_bp.route('/link/<int:event_id>')
@login_required
def event_link(event_id):
    ev = Event.query.get_or_404(event_id)
    if not is_admin_or_chef():
        return redirect(url_for('events.list_events'))
    # URL absolue prête à copier
    share_url = url_for('events.token_entry', token=ev.token, _external=True)
    return render_template('events/link.html', ev=ev, share_url=share_url)


# ---------------- LIFECYCLE ----------------
@events_bp.route('/<int:event_id>/state', methods=['POST'])
@login_required
def change_state(event_id):
    ev = Event.query.get_or_404(event_id)
    if not is_admin_or_chef():
        return redirect(url_for('events.list_events'))
    target = request.form.get('state')
    if target not in ('draft', 'in_progress', 'closed'):
        return redirect(url_for('events.view_event', event_id=ev.id))
    ev.state = target
    db.session.commit()
    flash(f"État passé à {target}", 'success')
    return redirect(url_for('events.view_event', event_id=ev.id))

# ---------------- VOLUNTEER (TOKEN) ----------------
@events_bp.route('/token/<string:token>', methods=['GET'])
def token_entry(token):
    ev = Event.query.filter_by(token=token).first_or_404()
    session['volunteer_name'] = session.get('volunteer_name')
    if not session['volunteer_name']:
        return render_template('events/token_entry.html', ev=ev)
    return redirect(url_for('events.verify', token=token))

@events_bp.route('/token/<string:token>', methods=['POST'])
def token_entry_post(token):
    ev = Event.query.filter_by(token=token).first_or_404()
    name = request.form.get('name')
    if not name:
        flash("Nom requis", 'danger')
        return render_template('events/token_entry.html', ev=ev)
    session['volunteer_name'] = name
    return redirect(url_for('events.verify', token=token))

@events_bp.route('/verify/<string:token>')
def verify(token):
    ev = Event.query.filter_by(token=token).first_or_404()
    if ev.state != 'in_progress':
        return "Évènement non disponible.", 403
    parents = [ei.item for ei in ev.event_items]
    tree = []
    for p in parents:
        included_children = []
        for c in p.children:
            ec = EventChild.query.filter_by(event_id=ev.id, child_id=c.id).first()
            if ec and ec.included:
                included_children.append(c)
        tree.append((p, included_children))
    return render_template('events/verify.html', ev=ev, tree=tree, token=token)

# ---------------- PRESENCE ----------------
@events_bp.route('/api/token/<string:token>/presence', methods=['POST'])
def presence(token):
    ev = Event.query.filter_by(token=token).first_or_404()
    name = session.get('volunteer_name')
    if not name:
        return jsonify({'error': 'no_name'}), 400
    data = request.get_json()
    pid = data.get('parent_id')
    p = Presence.query.filter_by(event_id=ev.id, parent_id=pid, name=name).first()
    if not p:
        p = Presence(event_id=ev.id, parent_id=pid, name=name, last_seen=datetime.utcnow())
        db.session.add(p)
    else:
        p.last_seen = datetime.utcnow()
    db.session.commit()
    return jsonify({'ok': True})

# ---------------- API STATUS / VERIFY / LOAD ----------------
@events_bp.route('/events/api/<int:event_id>/status')
@login_required
def api_status(event_id):
    ev = Event.query.get_or_404(event_id)
    verifs = Verification.query.filter_by(event_id=ev.id).all()
    vmap = {v.item_id: {'verified': v.verified, 'by': v.by, 'at': v.timestamp.isoformat() if v.timestamp else None} for v in verifs}
    parents_complete = {}
    for ei in ev.event_items:
        children = [ec.child for ec in EventChild.query.filter_by(event_id=ev.id, parent_id=ei.item_id, included=True).all()]
        parents_complete[ei.item_id] = all(vmap.get(c.id, {}).get('verified') for c in children) if children else False
    loaded = {ei.item_id: ei.loaded for ei in ev.event_items}
    busy = {}
    for ei in ev.event_items:
        pres = Presence.query.filter(Presence.event_id==ev.id, Presence.parent_id==ei.item_id,
                                     Presence.last_seen >= datetime.utcnow()-timedelta(seconds=10)).all()
        busy[ei.item_id] = [p.name for p in pres]
    return jsonify({'verifications': vmap, 'parents_complete': parents_complete, 'loaded': loaded, 'busy': busy})

@events_bp.route('/events/api/token/<string:token>/status')
def api_status_token(token):
    ev = Event.query.filter_by(token=token).first_or_404()
    verifs = Verification.query.filter_by(event_id=ev.id).all()
    vmap = {v.item_id: {'verified': v.verified, 'by': v.by, 'at': v.timestamp.isoformat() if v.timestamp else None} for v in verifs}
    parents_complete = {}
    for ei in ev.event_items:
        children = [ec.child for ec in EventChild.query.filter_by(event_id=ev.id, parent_id=ei.item_id, included=True).all()]
        parents_complete[ei.item_id] = all(vmap.get(c.id, {}).get('verified') for c in children) if children else False
    loaded = {ei.item_id: ei.loaded for ei in ev.event_items}
    busy = {}
    for ei in ev.event_items:
        pres = Presence.query.filter(Presence.event_id==ev.id, Presence.parent_id==ei.item_id,
                                     Presence.last_seen >= datetime.utcnow()-timedelta(seconds=10)).all()
        busy[ei.item_id] = [p.name for p in pres]
    return jsonify({'verifications': vmap, 'parents_complete': parents_complete, 'loaded': loaded, 'busy': busy})

@events_bp.route('/events/api/<string:token>/verify', methods=['POST'])
def api_verify(token):
    ev = Event.query.filter_by(token=token).first_or_404()
    if ev.state != 'in_progress':
        return jsonify({'error': 'not_in_progress'}), 400
    data = request.get_json()
    iid = data.get('item_id'); state = data.get('verified')
    v = Verification.query.filter_by(event_id=ev.id, item_id=iid).first()
    if not v: return jsonify({'error':'no_item'}),400
    v.verified=bool(state); v.by=session.get('volunteer_name'); v.timestamp=datetime.utcnow()
    db.session.commit()
    db.session.add(Activity(event_id=ev.id, message=f"{v.by or '???'} a {'coché' if v.verified else 'décoché'} {Item.query.get(iid).name}"))
    db.session.commit()
    return jsonify({'ok': True})

@events_bp.route('/events/api/<int:event_id>/load', methods=['POST'])
@login_required
def api_load(event_id):
    ev = Event.query.get_or_404(event_id)
    data = request.get_json()
    pid = data.get('item_id'); state = data.get('loaded')
    ei = EventItem.query.filter_by(event_id=ev.id, item_id=pid).first()
    if not ei: return jsonify({'error':'no_parent'}),400
    children = [ec.child for ec in EventChild.query.filter_by(event_id=ev.id, parent_id=pid, included=True).all()]
    verifs = Verification.query.filter_by(event_id=ev.id).all()
    vmap = {v.item_id: v.verified for v in verifs}
    if state and not all(vmap.get(c.id) for c in children):
        return jsonify({'error': 'not_all_children_verified'}),400
    ei.loaded=bool(state); db.session.commit()
    return jsonify({'ok': True})

# ---------------- EXPORT ----------------
@events_bp.route('/<int:event_id>/export/csv')
@login_required
def export_csv(event_id):
    ev = Event.query.get_or_404(event_id)
    si = io.StringIO(); cw = csv.writer(si)
    cw.writerow(['Parent','Enfant','Vérifié','Par','Heure'])
    for ec in EventChild.query.filter_by(event_id=ev.id, included=True).all():
        v = Verification.query.filter_by(event_id=ev.id, item_id=ec.child_id).first()
        cw.writerow([Item.query.get(ec.parent_id).name, ec.child.name, v.verified, v.by, v.timestamp])
    output = io.BytesIO(); output.write(si.getvalue().encode('utf-8')); output.seek(0)
    return send_file(output, mimetype='text/csv', as_attachment=True, download_name=f"event_{ev.id}.csv")

@events_bp.route('/<int:event_id>/export/pdf')
@login_required
def export_pdf(event_id):
    ev = Event.query.get_or_404(event_id)
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    w,h = A4
    c.setFont("Helvetica-Bold", 16)
    c.drawString(30,h-50, f"Rapport Évènement: {ev.title}")
    c.setFont("Helvetica",12)
    y=h-90
    for ec in EventChild.query.filter_by(event_id=ev.id, included=True).all():
        v=Verification.query.filter_by(event_id=ev.id, item_id=ec.child_id).first()
        line=f"{Item.query.get(ec.parent_id).name} - {ec.child.name} : {'OK' if v.verified else 'NON'} ({v.by or '—'})"
        c.drawString(40,y,line); y-=20
        if y<50: c.showPage(); y=h-50
    c.showPage(); c.save(); buffer.seek(0)
    return send_file(buffer, mimetype='application/pdf', as_attachment=True, download_name=f"event_{ev.id}.pdf")

@events_bp.route('/<int:event_id>/export/log')
@login_required
def export_log(event_id):
    ev=Event.query.get_or_404(event_id)
    si=io.StringIO(); cw=csv.writer(si)
    cw.writerow(['Date','Action'])
    for a in ev.activities:
        cw.writerow([a.timestamp,a.message])
    output=io.BytesIO(); output.write(si.getvalue().encode('utf-8')); output.seek(0)
    return send_file(output,mimetype='text/csv',as_attachment=True,download_name=f"event_{ev.id}_log.csv")
