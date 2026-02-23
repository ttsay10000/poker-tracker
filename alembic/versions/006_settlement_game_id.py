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


def upgrade() -> None:
    op.add_column("settlement", sa.Column("game_id", sa.String(length=36), nullable=True))
    # FK omitted for SQLite compatibility when adding to existing table


def downgrade() -> None:
    op.drop_column("settlement", "game_id")
