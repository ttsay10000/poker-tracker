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


def upgrade() -> None:
    op.add_column("player", sa.Column("venmo_handle", sa.String(length=255), nullable=True))
    op.add_column("player", sa.Column("zelle_handle", sa.String(length=255), nullable=True))
    op.add_column("player", sa.Column("photo_path_or_url", sa.String(length=512), nullable=True))
    op.add_column("player", sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("player", "notes")
    op.drop_column("player", "photo_path_or_url")
    op.drop_column("player", "zelle_handle")
    op.drop_column("player", "venmo_handle")
