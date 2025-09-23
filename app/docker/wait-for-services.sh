#!/usr/bin/env bash
set -euo pipefail

echo "[wait] Checking Postgres..."
# Extrait les infos de connexion depuis DATABASE_URL si dispo, sinon fallback
: "${DATABASE_URL:=}"
if [[ -n "${DATABASE_URL}" ]]; then
  # postgres+psycopg2://user:pass@host:port/db
  DB_HOST=$(python - <<'PY'
import os, re
u=os.environ.get("DATABASE_URL","")
m=re.match(r".*?://.*?:?.*?@([^:/]+):?(\d+)?/.*", u)
print(m.group(1) if m else "db")
PY
)
  DB_PORT=$(python - <<'PY'
import os, re
u=os.environ.get("DATABASE_URL","")
m=re.match(r".*?://.*?:?.*?@[^:/]+:?(\\d+)?/.*", u)
print(m.group(1) if m and m.group(1) else "5432")
PY
)
else
  DB_HOST="db"
  DB_PORT="5432"
fi

for i in {1..60}; do
  if (echo > /dev/tcp/$DB_HOST/$DB_PORT) >/dev/null 2>&1; then
    echo "[wait] Postgres is reachable on $DB_HOST:$DB_PORT"
    break
  fi
  echo "[wait] Postgres not ready yet ($i/60) ..."
  sleep 2
done

echo "[wait] Checking Redis..."
: "${REDIS_URL:=redis://:pc_redis_pass@redis:6379/0}"
# parse host/port/password quickly
R_HOST=$(python - <<'PY'
import os, re
u=os.environ.get("REDIS_URL","redis://:pc_redis_pass@redis:6379/0")
m=re.match(r"redis://(?::[^@]*@)?([^:/]+):?(\\d+)?", u)
print(m.group(1) if m else "redis")
PY
)
R_PORT=$(python - <<'PY'
import os, re
u=os.environ.get("REDIS_URL","redis://:pc_redis_pass@redis:6379/0")
m=re.match(r"redis://(?::[^@]*@)?[^:/]+:?(\\d+)?", u)
print(m.group(1) if m and m.group(1) else "6379")
PY
)
for i in {1..60}; do
  if (echo > /dev/tcp/$R_HOST/$R_PORT) >/dev/null 2>&1; then
    echo "[wait] Redis is reachable on $R_HOST:$R_PORT"
    break
  fi
  echo "[wait] Redis not ready yet ($i/60) ..."
  sleep 2
done

echo "[wait] All dependencies are reachable."
