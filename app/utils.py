from sqlalchemy.orm import Session
from .models import User, Role, Item, ItemType, KitItem
from .security import hash_password
import secrets

def seed_admin(db: Session, default_password: str = "admin"):
    # Ensure an admin exists with email admin@pcisere.fr
    admin = db.query(User).filter(User.email=="admin@pcisere.fr").first()
    if not admin:
        admin = User(
            email="admin@pcisere.fr",
            full_name="Administrateur",
            role=Role.ADMIN,
            password_hash=hash_password(default_password),
        )
        db.add(admin)
        db.commit()

def seed_demo_items(db: Session):
    # Create a SAC PS (KIT) and a few components if missing
    sac = db.query(Item).filter(Item.name=="Sac Premier Secours").first()
    if not sac:
        sac = Item(name="Sac Premier Secours", type=ItemType.KIT, description="Kit PS standard")
        db.add(sac); db.commit()
    gants = db.query(Item).filter(Item.name=="Gants nitrile (paire)").first()
    if not gants:
        gants = Item(name="Gants nitrile (paire)", type=ItemType.BULK, stock_qty=50)
        db.add(gants)
    dae = db.query(Item).filter(Item.name=="DAE Lifepak #001").first()
    if not dae:
        dae = Item(name="DAE Lifepak #001", type=ItemType.UNIQUE, serial_number="SN-LP-001")
        db.add(dae)
    db.commit()
    # link kit items
    exists = db.query(KitItem).filter(KitItem.kit_id==sac.id).first()
    if not exists:
        db.add_all([
            KitItem(kit_id=sac.id, component_id=gants.id, required_qty=10),
            KitItem(kit_id=sac.id, component_id=dae.id, required_qty=1),
        ])
        db.commit()
