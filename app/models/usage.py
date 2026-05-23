"""Usage tracking models — API call counts + agent token consumption.

Record types:
  - api_call:    external API invocations (Bing Search, etc.)
  - token_usage: LLM token consumption per agent per call
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    record_type: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True,
        comment="api_call | token_usage",
    )
    source: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True,
        comment="bing_search | deepseek_chat | siliconflow | ...",
    )
    agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
        comment="call count for api_call; token count for token_usage",
    )
    cost_estimate: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
        comment="estimated USD cost",
    )
    metadata_json: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True,
        comment="extra context: endpoint URL, model name, query text, ...",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True,
    )
