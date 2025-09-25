# app/seeds_templates.py — Modèles d'arbres (templates) + enregistrement CLI
from __future__ import annotations
import click
from flask.cli import with_appcontext
from . import db
from .models import StockNode, NodeType

def seed_template_ps():
    """Crée un modèle SAC PS complet prêt à dupliquer (si absent)."""
    root = StockNode.query.filter_by(name="MODELE SAC PS", level=0).first()
    if root:
        return root
    root = StockNode(name="MODELE SAC PS", type=NodeType.GROUP, level=0)
    db.session.add(root)
    db.session.flush()

    # Poche Trauma
    trauma = StockNode(name="Poche trauma", type=NodeType.GROUP, level=1, parent=root)
    db.session.add(trauma)
    db.session.flush()
    db.session.add(StockNode(name="Compresses stériles 10x10", type=NodeType.ITEM, level=2, parent=trauma, quantity=20))
    db.session.add(StockNode(name="Bande adhésive (scotch)", type=NodeType.ITEM, level=2, parent=trauma, quantity=1))
    db.session.add(StockNode(name="Bande élastique 4m", type=NodeType.ITEM, level=2, parent=trauma, quantity=2))

    # Poche Bilan
    bilan = StockNode(name="Poche bilan", type=NodeType.GROUP, level=1, parent=root)
    db.session.add(bilan)
    db.session.flush()
    db.session.add(StockNode(name="Saturomètre", type=NodeType.ITEM, level=2, parent=bilan, quantity=1))
    db.session.add(StockNode(name="Thermomètre", type=NodeType.ITEM, level=2, parent=bilan, quantity=1))
    db.session.add(StockNode(name="Tensiomètre", type=NodeType.ITEM, level=2, parent=bilan, quantity=1))

    # Poche Plaies
    plaies = StockNode(name="Poche plaies", type=NodeType.GROUP, level=1, parent=root)
    db.session.add(plaies)
    db.session.flush()
    db.session.add(StockNode(name="Pansements 4x4", type=NodeType.ITEM, level=2, parent=plaies, quantity=10))
    db.session.add(StockNode(name="Pansements compressifs", type=NodeType.ITEM, level=2, parent=plaies, quantity=2))

    db.session.commit()
    return root

def register_cli(app):
    @app.cli.command("seed-template-ps")
    @with_appcontext
    def seed_template_ps_cmd():
        root = seed_template_ps()
        click.echo(f"Template créé: id={root.id} name={root.name}")
