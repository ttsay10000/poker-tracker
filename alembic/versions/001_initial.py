"""Initial schema: player, game, game_entry, settlement.

Revision ID: 001
Revises:
Create Date: 2025-02-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "player",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("name_normalized", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name_normalized"),
    )
    op.create_table(
        "game",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("played_at", sa.DateTime(), nullable=False),
        sa.Column("source_image_path_or_url", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "game_entry",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("game_id", sa.String(), nullable=False),
        sa.Column("player_id", sa.String(), nullable=False),
        sa.Column("raw_name", sa.String(length=255), nullable=True),
        sa.Column("buyin", sa.Numeric(), nullable=True),
        sa.Column("cashout", sa.Numeric(), nullable=True),
        sa.Column("final_stack", sa.Numeric(), nullable=True),
        sa.Column("net_change", sa.Numeric(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["game_id"], ["game.id"]),
        sa.ForeignKeyConstraint(["player_id"], ["player.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "settlement",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("player_id", sa.String(), nullable=False),
        sa.Column("settled_at", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(), nullable=False),
        sa.Column("note", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["player.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("settlement")
    op.drop_table("game_entry")
    op.drop_table("game")
    op.drop_table("player")
