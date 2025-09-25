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

echo "==> Seeding admin (idempotent)..."
flask --app wsgi seed-admin || true

echo "==> Starting Gunicorn..."
exec gunicorn -k eventlet -w ${GUNICORN_WORKERS:-1} -b ${GUNICORN_BIND:-0.0.0.0:8000} ${GUNICORN_APP:-wsgi:app}
