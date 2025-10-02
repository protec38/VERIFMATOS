# app/seeds.py — Fonctions de seed (modèles, exemples)
from . import db
from .models import User, Role, StockNode, NodeType

def seed_basic():
    """Exemple de seed minimal: admin + 2 sacs racines."""
    if not User.query.filter_by(username="admin").first():
        admin = User(username="admin", role=Role.ADMIN, is_active=True)
        admin.set_password("admin")
        db.session.add(admin)

    if not StockNode.query.filter_by(name="SAC PS BLEU", level=0).first():
        sac_bleu = StockNode(name="SAC PS BLEU", type=NodeType.GROUP, level=0)
        db.session.add(sac_bleu)
    if not StockNode.query.filter_by(name="AMBULANCE 1", level=0).first():
        amb1 = StockNode(name="AMBULANCE 1", type=NodeType.GROUP, level=0)
        db.session.add(amb1)

    db.session.commit()
