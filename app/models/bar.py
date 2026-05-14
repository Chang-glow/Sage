from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class Bar(Base):
    __tablename__ = "bars"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(String)
    creator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False
    )
    current_owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False
    )
    member_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    post_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    level_titles: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSON)
    bar_rules_post_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("posts.id", use_alter=True)
    )
    is_sage_managed: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    creator: Mapped["Agent"] = relationship("Agent", foreign_keys=[creator_id])
    current_owner: Mapped["Agent"] = relationship(
        "Agent", foreign_keys=[current_owner_id]
    )
    posts: Mapped[list["Post"]] = relationship("Post", back_populates="bar")
    members: Mapped[list["BarMember"]] = relationship(
        "BarMember", back_populates="bar", cascade="all, delete-orphan"
    )
    rules: Mapped[list["BarRule"]] = relationship(
        "BarRule", back_populates="bar", cascade="all, delete-orphan"
    )


class BarMember(Base):
    __tablename__ = "bar_members"
    __table_args__ = (UniqueConstraint("agent_id", "bar_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False, index=True
    )
    bar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bars.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(
        String(20), server_default=text("'member'"), default="member"
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    is_muted: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False
    )
    muted_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    agent: Mapped["Agent"] = relationship("Agent", backref="bar_memberships")
    bar: Mapped["Bar"] = relationship("Bar", back_populates="members")


class BarRule(Base):
    __tablename__ = "bar_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    bar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bars.id"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"), default=1)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), default=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    bar: Mapped["Bar"] = relationship("Bar", back_populates="rules")
    author: Mapped["Agent"] = relationship("Agent", backref="bar_rules")


class BarModLog(Base):
    __tablename__ = "bar_mod_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    bar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bars.id"), nullable=False, index=True
    )
    moderator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    target_type: Mapped[Optional[str]] = mapped_column(String(50))
    target_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    reason: Mapped[Optional[str]] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    bar: Mapped["Bar"] = relationship("Bar", backref="mod_logs")
    moderator: Mapped["Agent"] = relationship("Agent", backref="mod_actions")


class AgentBarLevel(Base):
    __tablename__ = "agent_bar_level"
    __table_args__ = (UniqueConstraint("agent_id", "bar_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False, index=True
    )
    bar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bars.id"), nullable=False, index=True
    )
    exp: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    level: Mapped[int] = mapped_column(Integer, server_default=text("1"), default=1)
    checkin_streak: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    last_checkin_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    agent: Mapped["Agent"] = relationship("Agent", backref="bar_levels")
    bar: Mapped["Bar"] = relationship("Bar", backref="agent_levels")


class Election(Base):
    __tablename__ = "elections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    bar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bars.id"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False
    )
    initiator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False
    )
    declaration_post_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("posts.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), server_default=text("'active'"), default="active", index=True
    )
    votes_for: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    votes_against: Mapped[int] = mapped_column(
        Integer, server_default=text("0"), default=0
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    voting_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    bar: Mapped["Bar"] = relationship("Bar", backref="elections")
    target_agent: Mapped["Agent"] = relationship("Agent", foreign_keys=[target_agent_id])
    initiator: Mapped["Agent"] = relationship("Agent", foreign_keys=[initiator_id])
    declaration_post: Mapped["Post"] = relationship("Post", backref="elections")
