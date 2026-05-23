"""add_critical_indexes

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-23

Add indexes on:
- agents.status, agents.nickname (highest priority — filtered in every scheduler cycle)
- 14 unindexed FK columns
- High-frequency filter columns (relationships.is_archived, posts.reply_count, etc.)
"""
from typing import Sequence, Union

from alembic import op


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # agents — highest priority (filtered every scheduler cycle)
    op.create_index("ix_agents_status", "agents", ["status"])
    op.create_index("ix_agents_nickname", "agents", ["nickname"])

    # FK columns without indexes (join/lookup performance)
    op.create_index("ix_agents_previous_identity", "agents", ["previous_identity"])
    op.create_index("ix_bars_creator_id", "bars", ["creator_id"])
    op.create_index("ix_bars_current_owner_id", "bars", ["current_owner_id"])
    op.create_index("ix_bar_rules_created_by", "bar_rules", ["created_by"])
    op.create_index("ix_elections_target_agent_id", "elections", ["target_agent_id"])
    op.create_index("ix_elections_initiator_id", "elections", ["initiator_id"])
    op.create_index("ix_elections_declaration_post_id", "elections", ["declaration_post_id"])
    op.create_index("ix_notifications_sender_id", "notifications", ["sender_id"])
    op.create_index("ix_replies_parent_reply_id", "replies", ["parent_reply_id"])
    op.create_index("ix_promises_requester_id", "promises", ["requester_id"])
    op.create_index("ix_promises_promiser_id", "promises", ["promiser_id"])
    op.create_index("ix_promises_source_reply_id", "promises", ["source_reply_id"])
    op.create_index("ix_likes_agent_id", "likes", ["agent_id"])

    # High-frequency filter columns
    op.create_index("ix_relationships_is_archived", "relationships", ["is_archived"])
    op.create_index("ix_posts_reply_count", "posts", ["reply_count"])
    op.create_index("ix_notifications_type", "notifications", ["type"])
    op.create_index("ix_private_messages_is_read", "private_messages", ["is_read"])


def downgrade() -> None:
    op.drop_index("ix_private_messages_is_read", table_name="private_messages")
    op.drop_index("ix_notifications_type", table_name="notifications")
    op.drop_index("ix_posts_reply_count", table_name="posts")
    op.drop_index("ix_relationships_is_archived", table_name="relationships")

    op.drop_index("ix_likes_agent_id", table_name="likes")
    op.drop_index("ix_promises_source_reply_id", table_name="promises")
    op.drop_index("ix_promises_promiser_id", table_name="promises")
    op.drop_index("ix_promises_requester_id", table_name="promises")
    op.drop_index("ix_replies_parent_reply_id", table_name="replies")
    op.drop_index("ix_notifications_sender_id", table_name="notifications")
    op.drop_index("ix_elections_declaration_post_id", table_name="elections")
    op.drop_index("ix_elections_initiator_id", table_name="elections")
    op.drop_index("ix_elections_target_agent_id", table_name="elections")
    op.drop_index("ix_bar_rules_created_by", table_name="bar_rules")
    op.drop_index("ix_bars_current_owner_id", table_name="bars")
    op.drop_index("ix_bars_creator_id", table_name="bars")
    op.drop_index("ix_agents_previous_identity", table_name="agents")

    op.drop_index("ix_agents_nickname", table_name="agents")
    op.drop_index("ix_agents_status", table_name="agents")
