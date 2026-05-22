# Status: SkillGroup/SkillGroupMember → future-phase (not yet wired)
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class SkillGroup(Base):
    __tablename__ = "skill_groups"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    agent: Mapped["Agent"] = relationship("Agent", backref="skill_groups")
    members: Mapped[list["SkillGroupMember"]] = relationship(
        "SkillGroupMember", back_populates="group", cascade="all, delete-orphan"
    )


class SkillGroupMember(Base):
    __tablename__ = "skill_group_members"
    __table_args__ = (UniqueConstraint("group_id", "skill_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skill_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    skill_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    group: Mapped["SkillGroup"] = relationship("SkillGroup", back_populates="members")
