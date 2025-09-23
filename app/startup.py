import os
from werkzeug.security import generate_password_hash
from .extensions import db
from .models import Settings, User, Role, InventoryNode
from datetime import datetime

def _setting(key):
    return Settings.query.filter_by(key=key).first()

def bootstrap_once():
    # Run only once
    if not _setting("bootstrap_done"):
        # Create admin user
        admin_email = os.environ.get("ADMIN_EMAIL", "admin@example.com")
        admin_password = os.environ.get("ADMIN_PASSWORD", "admin")
        admin_display = os.environ.get("ADMIN_DISPLAY_NAME", "Admin")

        if not User.query.filter_by(email=admin_email).first():
            admin = User(
                email=admin_email,
                password_hash=generate_password_hash(admin_password),
                display_name=admin_display,
                role=Role.ADMIN,
                is_active=True,
            )
            db.session.add(admin)

        # Seed a sample inventory hierarchy
        if InventoryNode.query.count() == 0:
            sac = InventoryNode(name="Sac Médical", is_leaf=False, path="Sac Médical")
            db.session.add(sac)
            db.session.flush()
            compA = InventoryNode(name="Compartiment A", parent_id=sac.id, is_leaf=False, path="Sac Médical>Compartiment A")
            compB = InventoryNode(name="Compartiment B", parent_id=sac.id, is_leaf=False, path="Sac Médical>Compartiment B")
            db.session.add_all([compA, compB])
            db.session.flush()
            leaf1 = InventoryNode(name="Pansements", parent_id=compA.id, is_leaf=True, expected_qty=20, icon="fa-bandage", path="Sac Médical>Compartiment A>Pansements")
            leaf2 = InventoryNode(name="Gants", parent_id=compA.id, is_leaf=True, expected_qty=10, icon="fa-hands", path="Sac Médical>Compartiment A>Gants")
            leaf3 = InventoryNode(name="Masques", parent_id=compB.id, is_leaf=True, expected_qty=15, icon="fa-mask-face", path="Sac Médical>Compartiment B>Masques")
            db.session.add_all([leaf1, leaf2, leaf3])

        db.session.add(Settings(key="bootstrap_done", value="1"))
        db.session.commit()
