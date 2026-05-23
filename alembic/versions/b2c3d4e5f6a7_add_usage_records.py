"""add_usage_records

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "usage_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("record_type", sa.String(20), nullable=False, index=True, comment="api_call | token_usage"),
        sa.Column("source", sa.String(50), nullable=False, index=True, comment="bing_search | deepseek_chat | siliconflow | ..."),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default=sa.text("1"), comment="call count for api_call; token count for token_usage"),
        sa.Column("cost_estimate", sa.Float(), nullable=True, comment="estimated USD cost"),
        sa.Column("metadata_json", postgresql.JSON(), nullable=True, comment="extra context: endpoint URL, model name, query text, ..."),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("usage_records")
