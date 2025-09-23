#!/usr/bin/env bash
set -euo pipefail

echo "🔎 Attente Postgres (db:5432)…"
for i in {1..60}; do
  if python - <<'PY'
import os, sys
import psycopg2
from urllib.parse import urlparse
url = os.getenv("DATABASE_URL","")
if not url:
    sys.exit(1)
# Convert SA URL -> psycopg2 dsn
# postgresql+psycopg2://user:pass@host:port/db
if "+psycopg2" in url:
    url = url.replace("+psycopg2","")
u = urlparse(url)
pw = (u.password or "")
dsn = f"dbname={u.path.lstrip('/')} user={u.username} password={pw} host={u.hostname} port={u.port or 5432}"
try:
    psycopg2.connect(dsn).close()
    sys.exit(0)
except Exception as e:
    sys.exit(2)
PY
  then
    echo "✅ Postgres prêt."
    break
  else
    sleep 2
  fi
  if [ "$i" -eq 60 ]; then
    echo "❌ Postgres indisponible."
    exit 1
  fi
done

echo "🔎 Attente Redis (redis:6379)…"
for i in {1..60}; do
  if python - <<'PY'
import os, sys, redis, urllib.parse
url = os.getenv("REDIS_URL","")
if not url:
    sys.exit(1)
r = redis.Redis.from_url(url, socket_connect_timeout=1)
try:
    r.ping()
    sys.exit(0)
except Exception:
    sys.exit(2)
PY
  then
    echo "✅ Redis prêt."
    break
  else
    sleep 2
  fi
  if [ "$i" -eq 60 ]; then
    echo "❌ Redis indisponible."
    exit 1
  fi
done

echo "✔️  Tous les services sont prêts."
