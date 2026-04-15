"""Add deleted_at to expense for soft-delete (restore = add back to outstanding).

Revision ID: 007
Revises: 006
Create Date: 2025-02-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "007"
down_revision: Union[str, None] = "006"
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


def _create_expense_table() -> None:
    op.create_table(
        "expense",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("player_id", sa.String(), nullable=False),
        sa.Column("amount", sa.Numeric(), nullable=False),
        sa.Column("note", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expense_group_id", sa.String(length=36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["player_id"], ["player.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def upgrade() -> None:
    if not _has_table("expense"):
        _create_expense_table()
        return
    if not _has_column("expense", "expense_group_id"):
        op.add_column("expense", sa.Column("expense_group_id", sa.String(length=36), nullable=True))
    if not _has_column("expense", "deleted_at"):
        op.add_column("expense", sa.Column("deleted_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    if _has_table("expense") and _has_column("expense", "deleted_at"):
        op.drop_column("expense", "deleted_at")
