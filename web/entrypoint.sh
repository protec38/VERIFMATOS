#!/usr/bin/env sh
set -e

echo "==> PCPrep entrypoint: waiting for database..."
python - <<'PY'
import os, time, sys
from sqlalchemy import create_engine
url = os.environ.get("DATABASE_URL", "postgresql+psycopg2://pcprep:pcprep@db:5432/pcprep")
timeout = int(os.environ.get("DB_WAIT_TIMEOUT", "90"))
start = time.time()
while True:
    try:
        create_engine(url).connect().close()
        print("DB is up:", url)
        break
    except Exception as e:
        if time.time() - start > timeout:
            print("ERROR: DB not ready after", timeout, "seconds ->", e)
            sys.exit(1)
        time.sleep(2)
PY

echo "==> Applying migrations (idempotent)..."
if [ ! -d "/app/migrations" ]; then
  flask --app wsgi db init
  flask --app wsgi db migrate -m "init schema"
fi
flask --app wsgi db upgrade

echo "==> Seeding admin (idempotent, inline Python)..."
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
