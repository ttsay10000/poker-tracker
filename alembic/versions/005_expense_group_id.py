"""Add expense_group_id to expense for grouping charge batches.

Revision ID: 005
Revises: 004
Create Date: 2025-02-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
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
    if not _has_table("expense") or _has_column("expense", "expense_group_id"):
        return
    op.add_column("expense", sa.Column("expense_group_id", sa.String(length=36), nullable=True))


def downgrade() -> None:
    if _has_table("expense") and _has_column("expense", "expense_group_id"):
        op.drop_column("expense", "expense_group_id")
