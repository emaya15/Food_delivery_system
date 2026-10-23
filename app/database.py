"""Database engine, session factory and declarative base.

Schema creation is handled exclusively by Alembic migrations - this module
never calls ``Base.metadata.create_all()``.
"""
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base shared by all models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def build_engine(url: str) -> Engine:
    """Create an engine with sensible defaults for MySQL (and SQLite for tests)."""
    if url.startswith("sqlite"):
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url or url.endswith("://"):
            kwargs["poolclass"] = StaticPool
        engine = create_engine(url, **kwargs)
    else:
        engine = create_engine(url, pool_pre_ping=True, pool_recycle=1800)

    if engine.dialect.name == "sqlite":
        # Documented SQLAlchemy recipe so SAVEPOINT / transactions behave correctly with pysqlite.
        @event.listens_for(engine, "connect")
        def _sqlite_connect(dbapi_connection, _record):
            dbapi_connection.isolation_level = None

        @event.listens_for(engine, "begin")
        def _sqlite_begin(conn):
            # Tests share one in-memory connection between sessions: only BEGIN if none is open.
            if not conn.connection.driver_connection.in_transaction:
                conn.exec_driver_sql("BEGIN")

    if engine.dialect.name == "mysql":

        @event.listens_for(engine, "connect")
        def _set_utc(dbapi_connection, _record):  # pragma: no cover - needs MySQL
            cursor = dbapi_connection.cursor()
            cursor.execute("SET time_zone = '+00:00'")
            cursor.close()

    return engine


engine = build_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def transaction(db: Session) -> Iterator[Session]:
    """Commit on success, roll back on any exception.

    This is the single transaction-management strategy used by every service:
    public service functions wrap their work in ``with transaction(db):`` and
    internal helpers only ``flush()``.
    """
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
