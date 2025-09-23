import os

class BaseConfig:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me-please")
    # Database URL priority:
    # 1) SQLALCHEMY_DATABASE_URI directly
    # 2) Compose PG vars (POSTGRES_*)
    # 3) Fallback to local sqlite (dev)
    SQLALCHEMY_DATABASE_URI = os.getenv("SQLALCHEMY_DATABASE_URI") or (
        f"postgresql+psycopg2://{os.getenv('POSTGRES_USER','postgres')}:"
        f"{os.getenv('POSTGRES_PASSWORD','postgres')}@"
        f"{os.getenv('POSTGRES_HOST','db')}:"
        f"{os.getenv('POSTGRES_PORT','5432')}/"
        f"{os.getenv('POSTGRES_DB','ems')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Improve stability on some Docker/PG combos
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }

class DevelopmentConfig(BaseConfig):
    DEBUG = True

class ProductionConfig(BaseConfig):
    DEBUG = False

def get_config(env: str):
    env = (env or "").lower()
    if env.startswith("dev"):
        return DevelopmentConfig
    return ProductionConfig