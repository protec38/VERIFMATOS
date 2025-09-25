#!/usr/bin/env sh
set -e

echo "==> PCPrep entrypoint: waiting for database..."
python - <<'PY'
import os, time, sys
from sqlalchemy import create_engine, text
url = os.environ.get("DATABASE_URL", "postgresql+psycopg2://pcprep:pcprep@db:5432/pcprep")
timeout = int(os.environ.get("DB_WAIT_TIMEOUT", "90"))
start = time.time()
while True:
    try:
        e = create_engine(url)
        with e.connect() as c:
            c.execute(text("SELECT 1"))
        print("DB is up:", url)
        break
    except Exception as e:
        if time.time() - start > timeout:
            print("ERROR: DB not ready after", timeout, "seconds ->", e)
            sys.exit(1)
        time.sleep(2)
PY

echo "==> Checking Alembic state..."
HAS_VERSION="$(python - <<'PY'
import os
from sqlalchemy import create_engine, text
url = os.environ.get("DATABASE_URL", "postgresql+psycopg2://pcprep:pcprep@db:5432/pcprep")
e = create_engine(url)
with e.connect() as c:
    # to_regclass -> None si la table n'existe pas
    exists = c.execute(text("SELECT to_regclass('public.alembic_version')")).scalar()
    if not exists:
        print("no")
    else:
        ver = c.execute(text("SELECT version_num FROM alembic_version")).scalar()
        print(f"yes:{ver}")
PY
)"

case "$HAS_VERSION" in
  no)
    echo "==> First-time schema: generating initial migration & upgrading..."
    if [ ! -d "/app/migrations" ]; then
      flask --app wsgi db init
    fi
    flask --app wsgi db migrate -m "init schema"
    flask --app wsgi db upgrade
    ;;
  yes:*)
    echo "==> Alembic version present ($HAS_VERSION)"
    if [ -d "/app/migrations" ]; then
      echo "==> Applying pending upgrades (if any)..."
      # On tente un upgrade. S'il y a un décalage de chaîne, on n'échoue pas le démarrage.
      if ! flask --app wsgi db upgrade; then
        echo "WARN: Alembic upgrade failed (mismatch probable). Démarrage quand même."
      fi
    else
      echo "==> No local migrations directory; skipping upgrade to avoid mismatch."
    fi
    ;;
esac

echo "==> Seeding admin (idempotent)..."
python - <<'PY'
import os
from app import create_app, db
from app.models import User, Role
app = create_app()
with app.app_context():
    username = os.environ.get("ADMIN_USERNAME","admin")
    password = os.environ.get("ADMIN_PASSWORD","admin")
    u = User.query.filter_by(username=username).first()
    if not u:
        u = User(username=username, role=Role.ADMIN, is_active=True)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        print(f"Admin created: {username}/{password}")
    else:
        print(f"Admin already exists: {username}")
PY

echo "==> Starting Gunicorn..."
exec gunicorn -k eventlet -w ${GUNICORN_WORKERS:-1} -b ${GUNICORN_BIND:-0.0.0.0:8000} ${GUNICORN_APP:-wsgi:app}
