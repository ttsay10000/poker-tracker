"""SQLModel entities for poker tracker."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel


def new_uuid() -> str:
    return str(uuid.uuid4())


class Player(SQLModel, table=True):
    __tablename__ = "player"

    id: str = Field(default_factory=new_uuid, primary_key=True)
    name: str = Field(max_length=255)
    name_normalized: str = Field(max_length=255, unique=True, index=True)
    is_active: bool = Field(default=True)
    harper_crew: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    # Profile / analytics add-on
    venmo_handle: Optional[str] = Field(default=None, max_length=255)
    zelle_handle: Optional[str] = Field(default=None, max_length=255)
    photo_path_or_url: Optional[str] = Field(default=None, max_length=512)
    notes: Optional[str] = Field(default=None)

    game_entries: list["GameEntry"] = Relationship(back_populates="player")
    settlements: list["Settlement"] = Relationship(back_populates="player")


class Game(SQLModel, table=True):
    __tablename__ = "game"

    id: str = Field(default_factory=new_uuid, primary_key=True)
    played_at: datetime = Field()
    source_image_path_or_url: Optional[str] = Field(default=None, max_length=512)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    entries: list["GameEntry"] = Relationship(back_populates="game")


class GameEntry(SQLModel, table=True):
    __tablename__ = "game_entry"

    id: str = Field(default_factory=new_uuid, primary_key=True)
    game_id: str = Field(foreign_key="game.id")
    player_id: str = Field(foreign_key="player.id")
    raw_name: Optional[str] = Field(default=None, max_length=255)
    buyin: Optional[Decimal] = Field(default=None)
    cashout: Optional[Decimal] = Field(default=None)
    final_stack: Optional[Decimal] = Field(default=None)
    net_change: Decimal = Field()
    created_at: datetime = Field(default_factory=datetime.utcnow)

    game: Optional[Game] = Relationship(back_populates="entries")
    player: Optional[Player] = Relationship(back_populates="game_entries")


class Settlement(SQLModel, table=True):
    __tablename__ = "settlement"

    id: str = Field(default_factory=new_uuid, primary_key=True)
    player_id: str = Field(foreign_key="player.id")
    settled_at: date = Field(default_factory=date.today)
    amount: Decimal = Field()  # >0 organizer paid player; <0 player paid organizer
    note: Optional[str] = Field(default=None, max_length=512)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    player: Optional[Player] = Relationship(back_populates="settlements")
