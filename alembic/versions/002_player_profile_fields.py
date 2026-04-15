"""Add player profile fields: venmo_handle, zelle_handle, photo_path_or_url, notes.

Revision ID: 002
Revises: 001
Create Date: 2025-02-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    if not _has_table("player"):
        return
    if not _has_column("player", "venmo_handle"):
        op.add_column("player", sa.Column("venmo_handle", sa.String(length=255), nullable=True))
    if not _has_column("player", "zelle_handle"):
        op.add_column("player", sa.Column("zelle_handle", sa.String(length=255), nullable=True))
    if not _has_column("player", "photo_path_or_url"):
        op.add_column("player", sa.Column("photo_path_or_url", sa.String(length=512), nullable=True))
    if not _has_column("player", "notes"):
        op.add_column("player", sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    if not _has_table("player"):
        return
    if _has_column("player", "notes"):
        op.drop_column("player", "notes")
    if _has_column("player", "photo_path_or_url"):
        op.drop_column("player", "photo_path_or_url")
    if _has_column("player", "zelle_handle"):
        op.drop_column("player", "zelle_handle")
    if _has_column("player", "venmo_handle"):
        op.drop_column("player", "venmo_handle")
