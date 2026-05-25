"""fix_reputation_check_range

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-05-25

Replace ck_agents_reputation_range: was [-100, 100], now [0, 1].
Code uses 0-1 scale (min(1.0, reputation + 0.01)), so the old wide range
was unreachable in practice.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_agents_reputation_range", "agents")
    op.create_check_constraint("ck_agents_reputation_range", "agents",
                               "reputation >= 0 AND reputation <= 1")


def downgrade() -> None:
    op.drop_constraint("ck_agents_reputation_range", "agents")
    op.create_check_constraint("ck_agents_reputation_range", "agents",
                               "reputation >= -100 AND reputation <= 100")
