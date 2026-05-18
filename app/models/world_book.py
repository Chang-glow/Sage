from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class WorldBookEntry(Base):
    __tablename__ = "world_book_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"),
    )
    scope: Mapped[str] = mapped_column(
        String(20), server_default=text("'character'"), default="character",
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)
    trigger_type: Mapped[str] = mapped_column(
        String(20), server_default=text("'keyword'"), default="keyword",
    )
    trigger_keys: Mapped[Optional[list[str]]] = mapped_column(JSON)
    logic_rule: Mapped[Optional[str]] = mapped_column(String(20))
    priority: Mapped[int] = mapped_column(Integer, server_default=text("5"), default=5)
    position: Mapped[str] = mapped_column(
        String(20), server_default=text("'after_char'"), default="after_char",
    )
    depth: Mapped[Optional[int]] = mapped_column(Integer)
    recursive: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), default=True,
    )
    created_by_skill: Mapped[Optional[str]] = mapped_column(String(100))
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(),
    )
