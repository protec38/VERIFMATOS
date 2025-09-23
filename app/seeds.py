"""
Seed initial pour l'appli:
- admin/admin
- hiérarchie d'items multi-niveaux (parents/sous-parents/feuilles)
- un évènement d'exemple (draft, sans token)
"""
from datetime import datetime
from uuid import uuid4

from . import db
from .models import (
    User, ROLE_ADMIN,
    Item, Event, EventParent, EventChild, EventLoad
)


def seed_all():
    created = {}

    # Admin par défaut
    if not User.query.filter_by(username="admin").first():
        admin = User(username="admin", role=ROLE_ADMIN)
        admin.set_password("admin")
        db.session.add(admin)
        created["admin_user"] = "admin/admin"
    else:
        created["admin_user"] = "exists"

    # Arbre d'items
    if Item.query.count() == 0:
        # Top parents
        sac_soins = Item(name="Sac de soins", kind="parent", icon="fa-kit-medical")
        sac_ox = Item(name="Sac oxygénothérapie", kind="parent", icon="fa-lungs")
        db.session.add_all([sac_soins, sac_ox])
        db.session.flush()

        # Sous-parents de 'Sac de soins'
        pansements = Item(name="Pansements", kind="parent", parent_id=sac_soins.id, icon="fa-bandage")
        perfusions = Item(name="Perfusions", kind="parent", parent_id=sac_soins.id, icon="fa-flask")
        db.session.add_all([pansements, perfusions])
        db.session.flush()

        # Feuilles sous 'Pansements'
        db.session.add_all([
            Item(name="Compresses stériles", kind="leaf", parent_id=pansements.id, expected_qty=10, icon="fa-square-plus"),
            Item(name="Bandes extensibles", kind="leaf", parent_id=pansements.id, expected_qty=4, icon="fa-ribbon"),
            Item(name="Sparadrap", kind="leaf", parent_id=pansements.id, expected_qty=2, icon="fa-tape"),
        ])

        # Feuilles sous 'Perfusions'
        db.session.add_all([
            Item(name="Cathéters IV 18G", kind="leaf", parent_id=perfusions.id, expected_qty=5, icon="fa-droplet"),
            Item(name="Soluté NaCl 0.9% (500ml)", kind="leaf", parent_id=perfusions.id, expected_qty=3, icon="fa-prescription-bottle"),
        ])

        # Sous-parents de 'Sac oxygénothérapie'
        masques = Item(name="Masques", kind="parent", parent_id=sac_ox.id, icon="fa-mask-face")
        accessoires = Item(name="Accessoires", kind="parent", parent_id=sac_ox.id, icon="fa-screwdriver-wrench")
        db.session.add_all([masques, accessoires])
        db.session.flush()

        # Feuilles
        db.session.add_all([
            Item(name="Masques O2 adulte", kind="leaf", parent_id=masques.id, expected_qty=4, icon="fa-head-side-mask"),
            Item(name="Masques O2 pédiatrique", kind="leaf", parent_id=masques.id, expected_qty=2, icon="fa-child"),
            Item(name="Lunettes nasales", kind="leaf", parent_id=accessoires.id, expected_qty=3, icon="fa-wind"),
        ])

        created["items"] = "created"
    else:
        created["items"] = "exists"

    # Un event de démo
    if Event.query.count() == 0:
        ev = Event(title="Démonstration", date=datetime.utcnow(), location="Local", state="draft", token=str(uuid4()))
        db.session.add(ev)
        db.session.flush()

        # attacher les 2 parents top-level au demo event
        parents = Item.query.filter(Item.kind == "parent", Item.parent_id.is_(None)).all()
        for p in parents:
            db.session.add(EventParent(event_id=ev.id, parent_id=p.id))

        # inclure toutes les feuilles sous ces parents
        leaves = Item.query.filter(Item.kind == "leaf").all()
        for leaf in leaves:
            db.session.add(EventChild(event_id=ev.id, child_id=leaf.id, included=True))

        # état "loaded" initial à False
        for p in parents:
            db.session.add(EventLoad(event_id=ev.id, parent_id=p.id, loaded=False))

        created["event"] = f"demo #{ev.id} token={ev.token}"
    else:
        created["event"] = "exists"

    db.session.commit()
    return created
