"""add_world_dynamic_fields

Revision ID: g8h9i0j1k2l3
Revises: f7a8b9c0d1e2
Create Date: 2026-05-25

Add hometown, is_away, birthday columns to agents table for
world dynamic system (education mobility, career mobility, etc.).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g8h9i0j1k2l3"
down_revision: Union[str, None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('agents', sa.Column('hometown', sa.String(100), nullable=True))
    op.add_column('agents', sa.Column('is_away', sa.Boolean(),
                                      server_default=sa.text("false"), nullable=False))
    op.add_column('agents', sa.Column('birthday', sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column('agents', 'birthday')
    op.drop_column('agents', 'is_away')
    op.drop_column('agents', 'hometown')
