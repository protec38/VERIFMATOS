# manage.py — Utilitaires CLI (migrations, seed)
import click
from flask.cli import with_appcontext
from app import create_app, db
from app.models import *  # noqa

app = create_app()

@app.cli.command("seed-admin")
@with_appcontext
def seed_admin():
    """Crée le compte admin/admin si absent."""
    from app.models import User, Role
    if not User.query.filter_by(username="admin").first():
        u = User(username="admin", role=Role.ADMIN, is_active=True)
        u.set_password("admin")
        db.session.add(u)
        db.session.commit()
        click.echo("Admin créé: admin/admin")
    else:
        click.echo("Admin déjà présent")

@app.cli.command("info")
@with_appcontext
def info():
    from app.models import User, Event, StockNode
    click.echo(f"Users: {User.query.count()} | Events: {Event.query.count()} | Nodes: {StockNode.query.count()} ")
