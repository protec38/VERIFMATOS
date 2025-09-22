import os, sys, time
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

url = os.getenv("DATABASE_URL")
if not url:
    print("DATABASE_URL manquant", file=sys.stderr)
    sys.exit(1)

# Petite attente initiale
time.sleep(2)

max_tries = 30
for i in range(1, max_tries+1):
    try:
        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute("SELECT 1")
        print("DB OK.")
        sys.exit(0)
    except OperationalError as e:
        print(f"DB pas prête (tentative {i}/{max_tries}) : {e.__class__.__name__}", file=sys.stderr)
        time.sleep(2)

print("Échec: DB indisponible.")
sys.exit(2)
