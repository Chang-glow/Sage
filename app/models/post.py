from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False, index=True
    )
    bar_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bars.id", use_alter=True),
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)
    urge_type: Mapped[Optional[str]] = mapped_column(String(50))
    is_essential: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, index=True
    )
    is_pinned: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, index=True
    )
    is_rule_post: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False
    )
    pinned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    essential_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    reply_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    like_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    inspiration: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    embedding: Mapped[Optional[list[float]]] = mapped_column(Vector(1536))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    author: Mapped["Agent"] = relationship("Agent", backref="posts")
    bar: Mapped[Optional["Bar"]] = relationship("Bar", back_populates="posts")
    replies: Mapped[list["Reply"]] = relationship(
        "Reply", back_populates="post", cascade="all, delete-orphan"
    )


class Reply(Base):
    __tablename__ = "replies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    post_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False, index=True
    )
    parent_reply_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("replies.id")
    )
    content: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    post: Mapped["Post"] = relationship("Post", back_populates="replies")
    author: Mapped["Agent"] = relationship("Agent", backref="replies")
    parent: Mapped[Optional["Reply"]] = relationship(
        "Reply", remote_side=[id], back_populates="children"
    )
    children: Mapped[list["Reply"]] = relationship(
        "Reply", remote_side=[parent_reply_id], back_populates="parent"
    )
