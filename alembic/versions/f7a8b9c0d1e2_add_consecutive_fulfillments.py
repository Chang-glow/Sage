"""add_consecutive_fulfillments

Revision ID: f7a8b9c0d1e2
Revises: f6a7b8c9d0e1
Create Date: 2026-05-25

Add consecutive_fulfillments counter to agents table for tracking
consecutive promise fulfillments. Resets to 0 on broken promise.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('agents', sa.Column('consecutive_fulfillments', sa.Integer(),
                                      server_default=sa.text("0"), nullable=False))


def downgrade() -> None:
    op.drop_column('agents', 'consecutive_fulfillments')
