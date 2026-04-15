"""Add game_id to settlement for linking paid-up-at-save settlements.

Revision ID: 006
Revises: 005
Create Date: 2025-02-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "006"
down_revision: Union[str, None] = "005"
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
    if not _has_table("settlement") or _has_column("settlement", "game_id"):
        return
    op.add_column("settlement", sa.Column("game_id", sa.String(length=36), nullable=True))
    # FK omitted for SQLite compatibility when adding to existing table


def downgrade() -> None:
    if _has_table("settlement") and _has_column("settlement", "game_id"):
        op.drop_column("settlement", "game_id")
