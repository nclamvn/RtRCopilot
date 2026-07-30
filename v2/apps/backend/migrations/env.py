from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config

from rtr_copilot.config import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def migration_url() -> str:
    settings = get_settings()
    dsn = settings.migration_dsn or settings.postgres_dsn
    return str(dsn).replace("postgresql://", "postgresql+psycopg://", 1)


def run_migrations_offline() -> None:
    context.configure(
        url=migration_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        transactional_ddl=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_online_migrations() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = migration_url()
    engine = engine_from_config(section, prefix="sqlalchemy.", poolclass=None)
    with engine.connect() as connection:
        context.configure(connection=connection, transactional_ddl=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_online_migrations()
