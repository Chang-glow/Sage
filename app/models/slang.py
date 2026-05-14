from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class Slang(Base):
    __tablename__ = "slangs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    meaning: Mapped[str] = mapped_column(String, nullable=False)
    usage: Mapped[Optional[str]] = mapped_column(String)
    tags: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(
        String(20), server_default=text("'active'"), default="active", index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AgentSlang(Base):
    __tablename__ = "agent_slangs"
    __table_args__ = (UniqueConstraint("agent_id", "slang_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False, index=True
    )
    slang_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("slangs.id"), nullable=False, index=True
    )
    personal_affinity: Mapped[float] = mapped_column(Float, default=0.5)
    learned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
