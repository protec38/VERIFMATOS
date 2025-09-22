from datetime import datetime, timedelta
import io
import csv
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, jsonify, session, send_file
)
from flask_login import login_required, current_user
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

from .models import (
    db, Item, Event, EventItem, EventInclude, Verification,
    Activity, Presence, ROLE_ADMIN, ROLE_CHEF
)

events_bp = Blueprint("events", __name__)


# ---------------- Helpers ----------------
def is_admin_or_chef():
    return current_user.is_authenticated and current_user.role in (ROLE_ADMIN, ROLE_CHEF)


def collect_descendant_leaves(parent: Item):
    """Toutes les feuilles sous ce parent (multi-niveaux)."""
    out = []
    stack = [parent]
    while stack:
        node = stack.pop()
        if node.children:
            stack.extend(node.children)
        else:
            out.append(node)
    return out


def parent_complete(ev: Event, parent_id: int) -> bool:
    """True si toutes les feuilles incluses de ce parent sont vérifiées."""
    incs = EventInclude.query.filter_by(event_id=ev.id, parent_id=parent_id, included=True).all()
    leaf_ids = [inc.leaf_id for inc in incs]
    if not leaf_ids:
        return False
    verifs = Verification.query.filter(
        Verification.event_id == ev.id,
        Verification.leaf_id.in_(leaf_ids),
    ).all()
    vmap = {v.leaf_id: v.verified for v in verifs}
    return all(vmap.get(lid) for lid in leaf_ids)


def status_payload(ev: Event):
    # verifs
    verifs = Verification.query.filter_by(event_id=ev.id).all()
    ver_map = {
        str(v.leaf_id): {
            "verified": v.verified,
            "by": v.by,
            "at": v.timestamp.isoformat() if v.timestamp else None,
        } for v in verifs
    }
    # parents complete + loaded
    parents_complete = {}
    loaded = {}
    for ei in ev.event_items:
        parents_complete[ei.parent_id] = parent_complete(ev, ei.parent_id)
        loaded[ei.parent_id] = ei.loaded
    # presences (actifs < 5s)
    cutoff = datetime.utcnow() - timedelta(seconds=5)
    pres = Presence.query.filter(
        Presence.event_id == ev.id,
        Presence.ping_at >= cutoff,
    ).all()
    busy = {}
    for p in pres:
        busy.setdefault(p.parent_id, []).append(p.volunteer)

    return {
        "verifications": ver_map,
        "parents_complete": parents_complete,
        "loaded": loaded,
        "busy": busy,
    }


# ---------------- Liste / création ----------------
@events_bp.route("/")
@login_required
def list_events():
    if not is_admin_or_chef():
        return redirect(url_for("index"))
    events = Event.query.order_by(Event.created_at.desc()).all()
    return render_template("events/list.html", events=events)


@events_bp.route("/create", methods=["GET", "POST"])
@login_required
def create_event():
    if not is_admin_or_chef():
        return redirect(url_for("events.list_events"))

    if request.method == "POST":
        title = request.form.get("title")
        date_str = request.form.get("date")
        location = request.form.get("location")
        parent_ids = [int(x) for x in request.form.getlist("parent_ids")]

        ev = Event(
            title=title,
            date=datetime.fromisoformat(date_str) if date_str else datetime.utcnow(),
            location=location,
            chef_id=current_user.id,
            state="in_progress",
        )
        db.session.add(ev)
        db.session.flush()

        for pid in parent_ids:
            p = Item.query.get(pid)
            if not p or not p.is_parent:
                continue
            db.session.add(EventItem(event_id=ev.id, parent_id=p.id))
            # inclure toutes les feuilles sous ce parent
            for leaf in collect_descendant_leaves(p):
                if not EventInclude.query.filter_by(
                    event_id=ev.id, parent_id=p.id, leaf_id=leaf.id
                ).first():
                    db.session.add(EventInclude(
                        event_id=ev.id, parent_id=p.id, leaf_id=leaf.id, included=True
                    ))
                if not Verification.query.filter_by(
                    event_id=ev.id, leaf_id=leaf.id
                ).first():
                    db.session.add(Verification(
                        event_id=ev.id, leaf_id=leaf.id, verified=False
                    ))

        db.session.commit()
        flash("Évènement créé.", "success")
        return redirect(url_for("events.view_event", event_id=ev.id))

    parents = Item.query.filter_by(is_parent=True).order_by(Item.name.asc()).all()
    return render_template("events/create.html", parents=parents)


# ---------------- Edition parents / enfants ----------------
@events_bp.route("/<int:event_id>/edit", methods=["GET", "POST"])
@login_required
def edit_event(event_id):
    ev = Event.query.get_or_404(event_id)
    if not is_admin_or_chef():
        return redirect(url_for("events.list_events"))
    if ev.state == "closed":
        flash("Évènement clôturé.", "warning")
        return redirect(url_for("events.view_event", event_id=ev.id))

    if request.method == "POST":
        new_parents = set(int(x) for x in request.form.getlist("parent_ids"))
        old_parents = {ei.parent_id for ei in ev.event_items}

        # add
        for pid in new_parents - old_parents:
            p = Item.query.get(pid)
            if not p or not p.is_parent:
                continue
            db.session.add(EventItem(event_id=ev.id, parent_id=p.id))
            for leaf in collect_descendant_leaves(p):
                if not EventInclude.query.filter_by(
                    event_id=ev.id, parent_id=p.id, leaf_id=leaf.id
                ).first():
                    db.session.add(EventInclude(
                        event_id=ev.id, parent_id=p.id, leaf_id=leaf.id, included=True
                    ))
                if not Verification.query.filter_by(
                    event_id=ev.id, leaf_id=leaf.id
                ).first():
                    db.session.add(Verification(
                        event_id=ev.id, leaf_id=leaf.id, verified=False
                    ))

        # remove
        for pid in old_parents - new_parents:
            ei = EventItem.query.filter_by(event_id=ev.id, parent_id=pid).first()
            if ei:
                db.session.delete(ei)
            for inc in EventInclude.query.filter_by(event_id=ev.id, parent_id=pid).all():
                db.session.delete(inc)

        db.session.commit()
        flash("Parents mis à jour.", "success")
        return redirect(url_for("events.edit_children", event_id=ev.id))

    parents = Item.query.filter_by(is_parent=True).order_by(Item.name.asc()).all()
    selected = {ei.parent_id for ei in ev.event_items}
    return render_template("events/edit_parents.html", ev=ev, parents=parents, selected=selected)


@events_bp.route("/<int:event_id>/children", methods=["GET", "POST"])
@login_required
def edit_children(event_id):
    ev = Event.query.get_or_404(event_id)
    if not is_admin_or_chef():
        return redirect(url_for("events.list_events"))
    if ev.state == "closed":
        flash("Évènement clôturé.", "warning")
        return redirect(url_for("events.view_event", event_id=ev.id))

    # construire l'arbre parent -> feuilles incluses
    parents = [ei.parent for ei in ev.event_items]
    tree = []
    for p in parents:
        leaves = collect_descendant_leaves(p)
        rows = []
        for leaf in leaves:
            inc = EventInclude.query.filter_by(
                event_id=ev.id, parent_id=p.id, leaf_id=leaf.id
            ).first()
            if not inc:
                inc = EventInclude(event_id=ev.id, parent_id=p.id, leaf_id=leaf.id, included=True)
                db.session.add(inc)
                db.session.commit()
            rows.append((leaf, inc.included))
        tree.append((p, rows))

    if request.method == "POST":
        marked = {int(x) for x in request.form.getlist("leaf_ids")}
        incs = EventInclude.query.filter_by(event_id=ev.id).all()
        for inc in incs:
            inc.included = (inc.leaf_id in marked)
        db.session.commit()
        flash("Sélection d’enfants mise à jour.", "success")
        return redirect(url_for("events.view_event", event_id=ev.id))

    return render_template("events/edit_children.html", ev=ev, tree=tree)


# ---------------- Vues ----------------
@events_bp.route("/<int:event_id>")
@login_required
def view_event(event_id):
    ev = Event.query.get_or_404(event_id)
    tree = []
    for ei in ev.event_items:
        p = ei.parent
        incs = EventInclude.query.filter_by(
            event_id=ev.id, parent_id=p.id, included=True
        ).all()
        leaves = [inc.leaf for inc in incs]
        tree.append((p, leaves))
    return render_template("events/detail.html", ev=ev, tree=tree)


@events_bp.route("/link/<int:event_id>")
@login_required
def event_link(event_id):
    ev = Event.query.get_or_404(event_id)
    if not is_admin_or_chef():
        return redirect(url_for("events.list_events"))
    share_url = url_for("events.token_entry", token=ev.token, _external=True)
    return render_template("events/link.html", ev=ev, share_url=share_url)


# ---------------- Secouristes (token) ----------------
@events_bp.route("/token/<token>", methods=["GET", "POST"])
def token_entry(token):
    ev = Event.query.filter_by(token=token).first_or_404()
    if ev.state == "closed":
        flash("Évènement clôturé.", "warning")
        return render_template("events/token_entry.html", ev=ev)

    if request.method == "POST":
        full_name = (request.form.get("full_name") or "").strip()
        if not full_name:
            flash("Nom requis", "danger")
            return render_template("events/token_entry.html", ev=ev)
        session["volunteer_name"] = full_name
        session["event_token"] = token
        return redirect(url_for("events.verify", token=token))

    return render_template("events/token_entry.html", ev=ev)


@events_bp.route("/token/<token>/verify")
def verify(token):
    ev = Event.query.filter_by(token=token).first_or_404()
    if session.get("event_token") != token or not session.get("volunteer_name"):
        return redirect(url_for("events.token_entry", token=token))
    if ev.state != "in_progress":
        return "Évènement non disponible.", 403

    data = []
    for ei in ev.event_items:
        p = ei.parent
        incs = EventInclude.query.filter_by(
            event_id=ev.id, parent_id=p.id, included=True
        ).all()
        leaves = [inc.leaf for inc in incs]
        # garantir une ligne Verification pour chaque feuille
        for leaf in leaves:
            if not Verification.query.filter_by(event_id=ev.id, leaf_id=leaf.id).first():
                db.session.add(Verification(event_id=ev.id, leaf_id=leaf.id, verified=False))
        data.append((p, leaves))
    db.session.commit()

    return render_template("events/verify.html", ev=ev, data=data)


# ---------------- APIs live ----------------
@events_bp.route("/api/token/<token>/presence", methods=["POST"])
def ping_presence(token):
    ev = Event.query.filter_by(token=token).first_or_404()
    name = session.get("volunteer_name")
    parent_id = int((request.get_json() or {}).get("parent_id") or 0)
    if not name:
        return jsonify({"ok": False}), 401

    pr = Presence.query.filter_by(
        event_id=ev.id, parent_id=parent_id, volunteer=name
    ).first()
    if not pr:
        pr = Presence(event_id=ev.id, parent_id=parent_id, volunteer=name)
        db.session.add(pr)
    pr.ping_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True})


@events_bp.route("/api/<int:event_id>/status")
def api_status(event_id):
    ev = Event.query.get_or_404(event_id)

    def _status_payload(ev: Event):
        verifs = Verification.query.filter_by(event_id=ev.id).all()
        ver_map = {
            str(v.leaf_id): {
                "verified": v.verified,
                "by": v.by,
                "at": v.timestamp.isoformat() if v.timestamp else None,
            } for v in verifs
        }
        parents_complete = {}
        loaded = {}
        for ei in ev.event_items:
            parents_complete[ei.parent_id] = parent_complete(ev, ei.parent_id)
            loaded[ei.parent_id] = ei.loaded
        cutoff = datetime.utcnow() - timedelta(seconds=5)
        pres = Presence.query.filter(
            Presence.event_id == ev.id,
            Presence.ping_at >= cutoff,
        ).all()
        busy = {}
        for p in pres:
            busy.setdefault(p.parent_id, []).append(p.volunteer)
        return {
            "verifications": ver_map,
            "parents_complete": parents_complete,
            "loaded": loaded,
            "busy": busy,
        }

    return jsonify(_status_payload(ev))


@events_bp.route("/api/token/<token>/status")
def api_status_token(token):
    ev = Event.query.filter_by(token=token).first_or_404()
    return api_status(ev.id)


@events_bp.route("/api/<token>/verify", methods=["POST"])
def api_verify(token):
    ev = Event.query.filter_by(token=token).first_or_404()
    if ev.state == "closed":
        return jsonify({"ok": False, "error": "closed"}), 400
    name = session.get("volunteer_name")
    if not name:
        return jsonify({"ok": False, "error": "auth"}), 401

    data = request.get_json() or {}
    try:
        leaf_id = int(data.get("item_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "bad_item"}), 400
    state = bool(data.get("verified"))

    v = Verification.query.filter_by(event_id=ev.id, leaf_id=leaf_id).first()
    if not v:
        v = Verification(
            event_id=ev.id, leaf_id=leaf_id, verified=state,
            by=name, timestamp=datetime.utcnow()
        )
        db.session.add(v)
    else:
        v.verified = state
        v.by = name
        v.timestamp = datetime.utcnow()

    db.session.add(Activity(
        event_id=ev.id, actor=name,
        action=("verify" if state else "unverify"), item_id=leaf_id
    ))
    db.session.commit()
    return jsonify({"ok": True})


@events_bp.route("/api/<int:event_id>/load", methods=["POST"])
@login_required
def api_load(event_id):
    ev = Event.query.get_or_404(event_id)
    if not is_admin_or_chef():
        return jsonify({"ok": False, "error": "forbidden"}), 403

    data = request.get_json() or {}
    try:
        parent_id = int(data.get("item_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "bad_parent"}), 400
    want_loaded = bool(data.get("loaded"))

    if want_loaded and not parent_complete(ev, parent_id):
        return jsonify({"ok": False, "error": "not_all_children_verified"}), 400

    ei = EventItem.query.filter_by(event_id=ev.id, parent_id=parent_id).first()
    if not ei:
        return jsonify({"ok": False, "error": "not_in_event"}), 400

    ei.loaded = want_loaded
    db.session.add(Activity(
        event_id=ev.id, actor=current_user.username,
        action=("load" if want_loaded else "unload"), item_id=parent_id
    ))
    db.session.commit()
    return jsonify({"ok": True, "loaded": want_loaded})


# ---------------- Exports ----------------
@events_bp.route("/<int:event_id>/export.csv")
@login_required
def export_csv(event_id):
    ev = Event.query.get_or_404(event_id)
    si = io.StringIO()
    cw = csv.writer(si, delimiter=";")
    cw.writerow(["Event", ev.title, ev.date.isoformat(), ev.location or "", ev.state])
    cw.writerow([])
    cw.writerow(["LeafID", "Parent", "Leaf", "Qty", "Verified", "By", "At", "ParentLoaded"])

    loaded_map = {ei.parent_id: ei.loaded for ei in ev.event_items}
    for ei in ev.event_items:
        p = ei.parent
        incs = EventInclude.query.filter_by(
            event_id=ev.id, parent_id=p.id, included=True
        ).all()
        for inc in incs:
            v = Verification.query.filter_by(event_id=ev.id, leaf_id=inc.leaf_id).first()
            cw.writerow([
                inc.leaf_id, p.name, inc.leaf.name, inc.leaf.expected_qty,
                (v.verified if v else False),
                (v.by if v else ""),
                (v.timestamp.isoformat() if v and v.timestamp else ""),
                loaded_map.get(p.id, False),
            ])

    mem = io.BytesIO(si.getvalue().encode("utf-8"))
    mem.seek(0)
    return send_file(mem, mimetype="text/csv", as_attachment=True,
                     download_name=f"event_{ev.id}.csv")


@events_bp.route("/<int:event_id>/export.pdf")
@login_required
def export_pdf(event_id):
    ev = Event.query.get_or_404(event_id)
    mem = io.BytesIO()
    pdf = canvas.Canvas(mem, pagesize=A4)
    w, h = A4
    y = h - 40

    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(40, y, "Protection Civile de l'Isère — Rapport de mission")
    y -= 22
    pdf.setFont("Helvetica", 12)
    pdf.drawString(40, y, f"Évènement #{ev.id} — {ev.title} — {ev.date.strftime('%d/%m/%Y %H:%M')} ({ev.location or '—'})")
    y -= 16
    pdf.drawString(40, y, f"État: {ev.state}")
    y -= 16

    for ei in ev.event_items:
        p = ei.parent
        if y < 80:
            pdf.showPage()
            y = h - 40
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(40, y, f"Parent: {p.name}")
        y -= 14

        incs = EventInclude.query.filter_by(
            event_id=ev.id, parent_id=p.id, included=True
        ).all()
        for inc in incs:
            v = Verification.query.filter_by(event_id=ev.id, leaf_id=inc.leaf_id).first()
            status = "OK" if (v and v.verified) else "—"
            who = v.by if v and v.by else ""
            when = v.timestamp.strftime("%d/%m %H:%M") if v and v.timestamp else ""
            pdf.setFont("Helvetica", 10)
            pdf.drawString(60, y, f"- {inc.leaf.name} (x{inc.leaf.expected_qty})  [{status}]  {who} {when}")
            y -= 12
        y -= 6

    pdf.showPage()
    pdf.save()
    mem.seek(0)
    return send_file(mem, mimetype="application/pdf", as_attachment=True,
                     download_name=f"event_{ev.id}.pdf")
