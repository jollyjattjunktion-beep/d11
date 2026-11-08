from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.config import DATABASE_URL


def normalize_database_url(url: str) -> str:
    """Use the installed psycopg v3 driver for PostgreSQL URLs."""
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


ENGINE_DATABASE_URL = normalize_database_url(DATABASE_URL)
if ENGINE_DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
    engine = create_engine(
        ENGINE_DATABASE_URL,
        connect_args=connect_args,
        pool_pre_ping=True,
    )
else:
    # Keep small connection pools for the single-instance Render web service
    # and refresh idle connections to handle serverless/managed PG wake-ups.
    engine = create_engine(
        ENGINE_DATABASE_URL,
        pool_pre_ping=True,
        pool_size=3,
        max_overflow=2,
        pool_timeout=30,
        pool_recycle=300,
    )
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
