"""Database session and engine."""
from sqlmodel import Session, create_engine

from config import DATABASE_URL
from models import SQLModel

connect_args = {} if "sqlite" in DATABASE_URL else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, echo=False)


def create_db_and_tables():
    """Create all tables (for SQLite / initial deploy)."""
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
