"""add_expectation_to_promises

Revision ID: a1b2c3d4e5f6
Revises: e3b8f9d2a1c4
Create Date: 2026-05-23 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "e3b8f9d2a1c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("promises", sa.Column("expectation", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("promises", "expectation")
