from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class Relationship(Base):
    __tablename__ = "relationships"
    __table_args__ = (UniqueConstraint("agent_id", "target_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False, index=True
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False, index=True
    )
    attitude: Mapped[str] = mapped_column(
        String(20), server_default=text("'neutral'"), default="neutral"
    )
    intimacy: Mapped[float] = mapped_column(Float, server_default=text("0.0"), default=0.0, index=True)
    last_interaction: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    is_blocked: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False
    )
    is_archived: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False
    )

    agent: Mapped["Agent"] = relationship("Agent", foreign_keys=[agent_id], backref="outgoing_relationships")
    target: Mapped["Agent"] = relationship("Agent", foreign_keys=[target_id], backref="incoming_relationships")
