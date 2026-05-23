"""add_trust_tags_and_reputation

Revision ID: e3b8f9d2a1c4
Revises: 7ce852a2cc1f
Create Date: 2026-05-23 10:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'e3b8f9d2a1c4'
down_revision: Union[str, None] = '7ce852a2cc1f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('agents', sa.Column('trust_tags', postgresql.JSON(astext_type=sa.Text()), nullable=True))
    op.add_column('agents', sa.Column('reputation', sa.Float(), server_default=sa.text("0.0"), nullable=False))


def downgrade() -> None:
    op.drop_column('agents', 'reputation')
    op.drop_column('agents', 'trust_tags')
