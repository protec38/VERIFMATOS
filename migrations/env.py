
from __future__ import with_statement
import logging
from logging.config import fileConfig

from alembic import context
from flask import current_app

config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
logger = logging.getLogger('alembic.env')

def get_engine():
    try:
        return current_app.extensions['migrate'].db.get_engine()
    except TypeError:
        return current_app.extensions['migrate'].db.engine

target_metadata = current_app.extensions['migrate'].db.metadata

def run_migrations_offline():
    url = current_app.extensions['migrate'].db.get_engine().url
    context.configure(
        url=str(url),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    connectable = get_engine()

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
