"""Stamp Alembic at 001 when the DB has tables but no migration history.

Useful when the database was created without Alembic (e.g. create_db_and_tables
or manual setup). Run once before 'alembic upgrade head' so we only apply 002+.
"""
import sys
from pathlib import Path

# Project root
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import create_engine, text
from sqlalchemy.engine import reflection

from config import DATABASE_URL


def main() -> None:
    engine = create_engine(DATABASE_URL)
    inspector = reflection.Inspector.from_engine(engine)
    tables = inspector.get_table_names()

    has_player = "player" in tables
    has_alembic_version = "alembic_version" in tables

    if not has_player:
        # Fresh DB; let alembic upgrade head run from scratch
        return

    if has_alembic_version:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT COUNT(*) FROM alembic_version")).fetchone()
            if row and row[0] > 0:
                # Already stamped; nothing to do
                return

    # DB has tables but no (or empty) alembic_version → stamp 001
    from alembic.config import Config
    from alembic import command

    alembic_cfg = Config(Path(__file__).parent / "alembic.ini")
    command.stamp(alembic_cfg, "001")


if __name__ == "__main__":
    main()
