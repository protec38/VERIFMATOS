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
        db.session.add(ev); db.session.flush()

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
            if ei: db.session.delete(ei)
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
                db.session.add(ec); db.session.commit()
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
    ev.state = target; db.session.commit()
    flash(f"État passé à {target}", 'success')
    return redirect(url_for('events.view_event', event_id=ev.id))

# ---------------- VOLONTAIRES (TOKEN) ----------------
@events_bp.route('/token/<token>', methods=['GET','POST'])
def token_entry(token):
    ev = Event.query.filter_by(token=token).first_or_404()
    if ev.state == 'closed':
        flash('Évènement clôturé', 'warning')
        return render_template('events/token_entry.html', ev=ev)

    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        if not full_name:
            flash('Nom requis', 'danger')
            return render_template('events/token_entry.html', ev=ev)
        session['volunteer_name'] = full_name
        session['event_token'] = token
        return redirect(url_for('events.verify', token=token))

    return render_template('events/token_entry.html', ev=ev)

@events_bp.route('/token/<token>/verify')
def verify(token):
    ev = Event.query.filter_by(token=token).first_or_404()
    if session.get('event_token') != token or not session.get('volunteer_name'):
        return redirect(url_for('events.token_entry', token=token))
    if ev.state != 'in_progress':
        return "Évènement non disponible.", 403
    parents = [ei.item for ei in ev.event_items]
    data = []
    for p in parents:
        children = []
        for c in p.children:
            ec = EventChild.query.filter_by(event_id=ev.id, child_id=c.id).first()
            if ec and ec.included:
                children.append(c)
        data.append((p, children))
    return render_template('events/verify.html', ev=ev, data=data)

# ---------------- PRESENCE ----------------
@events_bp.route('/api/token/<token>/presence', methods=['POST'])
def ping_presence(token):
    ev = Event.query.filter_by(token=token).first_or_404()
    name = session.get('volunteer_name')
    parent_id = int((request.get_json() or {}).get('parent_id') or 0)
    if not name:
        return jsonify({'ok': False}), 401
    pr = Presence.query.filter_by(event_id=ev.id, parent_id=parent_id, volunteer=name).first()
    if not pr:
        pr = Presence(event_id=ev.id, parent_id=parent_id, volunteer=name)
        db.session.add(pr)
    pr.ping_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'ok': True})

# ---------------- STATUS / VERIFY / LOAD ----------------
def _status_payload(ev: Event) -> dict:
    verifs = Verification.query.filter_by(event_id=ev.id).all()
    vmap = {v.item_id: v for v in verifs}

    parents = [ei.item for ei in ev.event_items]
    parents_status = {}
    for p in parents:
        child_ids = [
            c.id for c in p.children
            if (EventChild.query.filter_by(event_id=ev.id, child_id=c.id).first()
                and EventChild.query.filter_by(event_id=ev.id, child_id=c.id).first().included)
        ]
        parents_status[p.id] = all(vmap.get(cid) and vmap[cid].verified for cid in child_ids) if child_ids else False

    loaded = {ei.item_id: ei.loaded for ei in ev.event_items}

    cutoff = datetime.utcnow() - timedelta(seconds=5)
    presence = Presence.query.filter(Presence.event_id == ev.id, Presence.ping_at >= cutoff).all()
    busy = {}
    for pr in presence:
        busy.setdefault(pr.parent_id, set()).add(pr.volunteer)
    busy = {k: list(v) for k, v in busy.items()}

    return {
        'verifications': {
            str(v.item_id): {
                'verified': v.verified,
                'by': v.by,
                'at': v.timestamp.isoformat() if v.timestamp else None
            } for v in verifs
        },
        'parents_complete': parents_status,
        'loaded': loaded,
        'busy': busy
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
    if ev.state == 'closed':
        return jsonify({'ok': False, 'error': 'closed'}), 400

    name = session.get('volunteer_name')
    if not name:
        return jsonify({'ok': False, 'error': 'auth'}), 401

    data = request.get_json() or {}
    item_id = int(data.get('item_id'))
    state = bool(data.get('verified'))

    v = Verification.query.filter_by(event_id=ev.id, item_id=item_id).first()
    if not v:
        v = Verification(event_id=ev.id, item_id=item_id, verified=state, by=name, timestamp=datetime.utcnow())
        db.session.add(v)
    else:
        v.verified = state
        v.by = name
        v.timestamp = datetime.utcnow()

    # journal
    db.session.add(Activity(
        event_id=ev.id,
        actor=name,
        action=('verify' if state else 'unverify'),
        item_id=item_id
    ))
    db.session.commit()
    return jsonify({'ok': True})


@events_bp.route('/api/<int:event_id>/load', methods=['POST'])
@login_required
def api_load(event_id):
    ev = Event.query.get_or_404(event_id)
    if not is_admin_or_chef():
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    data = request.get_json() or {}
    item_id = int(data.get('item_id'))
    loaded = bool(data.get('loaded'))
    status = _status_payload(ev)
    if loaded and not status['parents_complete'].get(item_id, False):
        return jsonify({'ok': False, 'error': 'not_all_children_verified'}), 400
    ei = EventItem.query.filter_by(event_id=ev.id, item_id=item_id).first()
    if not ei:
        return jsonify({'ok': False, 'error': 'not_in_event'}), 400
    ei.loaded = loaded
    db.session.add(Activity(event_id=ev.id, actor=current_user.username, action='load' if loaded else 'unload', item_id=item_id))
    db.session.commit()
    return jsonify({'ok': True, 'loaded': loaded})

# ---------------- EXPORTS ----------------
@events_bp.route('/<int:event_id>/export.csv')
@login_required
def export_csv(event_id):
    ev = Event.query.get_or_404(event_id)
    si = io.StringIO(); cw = csv.writer(si, delimiter=';')
    cw.writerow(['Event', ev.title, ev.date.isoformat(), ev.location or '', ev.state])
    cw.writerow([])
    cw.writerow(['ItemID','Parent','Child','ExpectedQty','Verified','By','At','LoadedParent'])
    loaded_map = {ei.item_id: ei.loaded for ei in ev.event_items}
    parents = [ei.item for ei in ev.event_items]
    for p in parents:
        for c in p.children:
            ec = EventChild.query.filter_by(event_id=ev.id, child_id=c.id).first()
            if not ec or not ec.included:
                continue
            v = Verification.query.filter_by(event_id=ev.id, item_id=c.id).first()
            cw.writerow([
                c.id, p.name, c.name, c.expected_qty,
                (v.verified if v else False),
                (v.last_by if v else ''),
                (v.last_at.isoformat() if v and v.last_at else ''),
                loaded_map.get(p.id, False)
            ])
    mem = io.BytesIO(si.getvalue().encode('utf-8')); mem.seek(0)
    return send_file(mem, mimetype='text/csv', as_attachment=True, download_name=f"event_{ev.id}.csv")

@events_bp.route('/<int:event_id>/export.pdf')
@login_required
def export_pdf(event_id):
    ev = Event.query.get_or_404(event_id)
    mem = io.BytesIO()
    p = canvas.Canvas(mem, pagesize=A4)
    w, h = A4
    y = h - 40
    p.setFont("Helvetica-Bold", 16); p.drawString(40, y, "Protection Civile de l'Isère — Rapport de mission"); y -= 22
    p.setFont("Helvetica", 12); p.drawString(40, y, f"Évènement #{ev.id} — {ev.title} — {ev.date.strftime('%d/%m/%Y %H:%M')}  ({ev.location or '—'})"); y -= 16
    p.drawString(40, y, f"État: {ev.state}"); y -= 16
    parents = [ei.item for ei in ev.event_items]
    for parent in parents:
        if y < 80:
            p.showPage(); y = h - 40
        p.setFont("Helvetica-Bold", 12); p.drawString(40, y, f"Parent: {parent.name}"); y -= 14
        for child in parent.children:
            ec = EventChild.query.filter_by(event_id=ev.id, child_id=child.id).first()
            if not ec or not ec.included:
                continue
            v = Verification.query.filter_by(event_id=ev.id, item_id=child.id).first()
            status = "OK" if (v and v.verified) else "—"
            who = v.last_by if v and v.last_by else ''
            when = v.last_at.strftime('%d/%m %H:%M') if v and v.last_at else ''
            p.setFont("Helvetica", 10); p.drawString(60, y, f"- {child.name} (x{child.expected_qty})  [{status}]  {who} {when}"); y -= 12
        y -= 6
    p.setFont("Helvetica", 10); p.drawString(40, 60, "Chef de poste: ____________________"); p.drawString(300, 60, "Conducteur: ____________________")
    p.showPage(); p.save(); mem.seek(0)
    return send_file(mem, mimetype='application/pdf', as_attachment=True, download_name=f"event_{ev.id}.pdf")

@events_bp.route('/<int:event_id>/log.csv')
@login_required
def export_log(event_id):
    ev = Event.query.get_or_404(event_id)
    si = io.StringIO()
    cw = csv.writer(si, delimiter=';')
    cw.writerow(['at', 'actor', 'action', 'item_id'])
    for a in ev.activities:
        cw.writerow([a.at.isoformat(), a.actor, a.action, a.item_id or ''])
    mem = io.BytesIO(si.getvalue().encode('utf-8'))
    mem.seek(0)
    return send_file(mem, mimetype='text/csv', as_attachment=True, download_name=f"event_{ev.id}_log.csv")
