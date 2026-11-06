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
connect_args = {"check_same_thread": False} if ENGINE_DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(ENGINE_DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
