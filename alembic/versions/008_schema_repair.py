"""Repair drifted schemas that were stamped ahead of the actual tables/columns.

Revision ID: 008
Revises: 007
Create Date: 2026-04-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table_name: str) -> bool:
    return table_name in _inspector().get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    if table_name not in _inspector().get_table_names():
        return False
    return column_name in {column["name"] for column in _inspector().get_columns(table_name)}


def _ensure_player_columns() -> None:
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
    if not _has_column("player", "harper_crew"):
        op.add_column(
            "player",
            sa.Column("harper_crew", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def _ensure_expense_table() -> None:
    if not _has_table("expense"):
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
        return
    if not _has_column("expense", "expense_group_id"):
        op.add_column("expense", sa.Column("expense_group_id", sa.String(length=36), nullable=True))
    if not _has_column("expense", "deleted_at"):
        op.add_column("expense", sa.Column("deleted_at", sa.DateTime(), nullable=True))


def _ensure_settlement_game_id() -> None:
    if _has_table("settlement") and not _has_column("settlement", "game_id"):
        op.add_column("settlement", sa.Column("game_id", sa.String(length=36), nullable=True))


def upgrade() -> None:
    _ensure_player_columns()
    _ensure_expense_table()
    _ensure_settlement_game_id()


def downgrade() -> None:
    # This repair migration is intentionally a no-op on downgrade.
    pass
