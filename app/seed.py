from app.extensions import db
from app.models import User, Role
from app import create_app

def seed_admin():
    app = create_app()
    with app.app_context():
        # Vérifier si un utilisateur existe déjà
        if User.query.first():
            print("✅ Des utilisateurs existent déjà, aucun admin ajouté.")
            return

        # Créer un admin par défaut
        admin = User(
            email="admin@example.com",
            display_name="Admin",
            role=Role.ADMIN,
            is_active=True,
        )
        admin.set_password("admin")

        db.session.add(admin)
        db.session.commit()
        print("👤 Compte admin créé : admin@example.com / admin")


if __name__ == "__main__":
    seed_admin()
