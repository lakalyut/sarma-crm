import os
import sys
from pathlib import Path
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BASE_DIR))

# Alembic Config
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# IMPORTANT: import Base + models so metadata is complete
from app.database import Base  # noqa: E402
from app import models  # noqa: F401, E402

target_metadata = Base.metadata


def get_url() -> str:
    return os.getenv("DATABASE_URL", "sqlite:///./main.db")


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(get_url(), future=True)

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