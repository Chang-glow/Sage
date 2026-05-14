from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    nickname: Mapped[str] = mapped_column(String(50), nullable=False)
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    gender: Mapped[str] = mapped_column(String(10), nullable=False)
    occupation: Mapped[Optional[str]] = mapped_column(String(100))
    income_level: Mapped[Optional[str]] = mapped_column(String(20))
    education: Mapped[Optional[str]] = mapped_column(String(50))
    district: Mapped[Optional[str]] = mapped_column(String(100))
    school_or_company: Mapped[Optional[str]] = mapped_column(String(200))
    boarding: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False
    )
    interests: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    personality_vector: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    life_history: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSON)
    notification_settings: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    stealth_mode: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False
    )
    is_online: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False
    )
    last_online: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    previous_identity: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id")
    )
    solidified_memories: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(
        String(20), server_default=text("'active'"), default="active"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_by: Mapped[Optional[str]] = mapped_column(String)
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    previous: Mapped[Optional[Agent]] = relationship(
        "Agent", remote_side=[id], back_populates="successors"
    )
    successors: Mapped[list[Agent]] = relationship(
        "Agent", remote_side=[previous_identity], back_populates="previous"
    )
    schedule: Mapped[Optional[AgentSchedule]] = relationship(
        "AgentSchedule", back_populates="agent", uselist=False
    )


class AgentSchedule(Base):
    __tablename__ = "agent_schedules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False, unique=True
    )
    active_windows: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSON)
    browse_speed: Mapped[str] = mapped_column(
        String(10), server_default=text("'normal'"), default="normal"
    )
    reply_impulse: Mapped[float] = mapped_column(Float, default=0.5)
    max_flow_rounds: Mapped[int] = mapped_column(Integer, default=5)
    max_flow_per_day: Mapped[int] = mapped_column(Integer, default=3)
    weekly_boost: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    calendar_events: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSON)

    agent: Mapped[Agent] = relationship("Agent", back_populates="schedule")


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    details: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
