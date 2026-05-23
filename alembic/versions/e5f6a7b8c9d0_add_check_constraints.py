"""add_check_constraints

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-23

Add CHECK constraints on numeric fields for data integrity:
- agents.age, agents.reputation, agents.token_limit_override
- posts.reply_count
- relationships.intimacy
- promises.expectation
- agent_slangs.personal_affinity
- usage_records.quantity
- elections.votes_for, elections.votes_against
"""
from typing import Sequence, Union

from alembic import op


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint("ck_agents_age_range", "agents", "age >= 0 AND age <= 120")
    op.create_check_constraint("ck_agents_reputation_range", "agents", "reputation >= -100 AND reputation <= 100")
    op.create_check_constraint("ck_agents_token_limit_override_positive", "agents", "token_limit_override IS NULL OR token_limit_override > 0")
    op.create_check_constraint("ck_posts_reply_count_nonnegative", "posts", "reply_count >= 0")
    op.create_check_constraint("ck_relationships_intimacy_range", "relationships", "intimacy >= -1.0 AND intimacy <= 1.0")
    op.create_check_constraint("ck_promises_expectation_range", "promises", "expectation IS NULL OR (expectation >= 0 AND expectation <= 100)")
    op.create_check_constraint("ck_agent_slangs_affinity_range", "agent_slangs", "personal_affinity >= 0 AND personal_affinity <= 1")
    op.create_check_constraint("ck_usage_records_quantity_positive", "usage_records", "quantity > 0")
    op.create_check_constraint("ck_elections_votes_for_nonnegative", "elections", "votes_for >= 0")
    op.create_check_constraint("ck_elections_votes_against_nonnegative", "elections", "votes_against >= 0")


def downgrade() -> None:
    op.drop_constraint("ck_elections_votes_against_nonnegative", "elections")
    op.drop_constraint("ck_elections_votes_for_nonnegative", "elections")
    op.drop_constraint("ck_usage_records_quantity_positive", "usage_records")
    op.drop_constraint("ck_agent_slangs_affinity_range", "agent_slangs")
    op.drop_constraint("ck_promises_expectation_range", "promises")
    op.drop_constraint("ck_relationships_intimacy_range", "relationships")
    op.drop_constraint("ck_posts_reply_count_nonnegative", "posts")
    op.drop_constraint("ck_agents_token_limit_override_positive", "agents")
    op.drop_constraint("ck_agents_reputation_range", "agents")
    op.drop_constraint("ck_agents_age_range", "agents")
