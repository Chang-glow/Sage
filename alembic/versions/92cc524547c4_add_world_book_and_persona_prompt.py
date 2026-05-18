"""add world_book_entries and agents.persona_prompt

Revision ID: 92cc524547c4
Revises: 5cfe4d7624a1
Create Date: 2026-05-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '92cc524547c4'
down_revision: Union[str, None] = '5cfe4d7624a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('world_book_entries',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('scope', sa.String(length=20), server_default=sa.text("'character'"), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('content', sa.String(), nullable=False),
        sa.Column('trigger_type', sa.String(length=20), server_default=sa.text("'keyword'"), nullable=False),
        sa.Column('trigger_keys', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('logic_rule', sa.String(length=20), nullable=True),
        sa.Column('priority', sa.Integer(), server_default=sa.text("5"), nullable=False),
        sa.Column('position', sa.String(length=20), server_default=sa.text("'after_char'"), nullable=False),
        sa.Column('depth', sa.Integer(), nullable=True),
        sa.Column('recursive', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_by_skill', sa.String(length=100), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_world_book_entries_scope'), 'world_book_entries', ['scope'], unique=False)
    op.create_index(op.f('ix_world_book_entries_is_active'), 'world_book_entries', ['is_active'], unique=False)
    op.create_index(op.f('ix_world_book_entries_trigger_type'), 'world_book_entries', ['trigger_type'], unique=False)
    op.create_index(op.f('ix_world_book_entries_created_by_skill'), 'world_book_entries', ['created_by_skill'], unique=False)

    op.add_column('agents', sa.Column('persona_prompt', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('agents', 'persona_prompt')
    op.drop_index(op.f('ix_world_book_entries_created_by_skill'), table_name='world_book_entries')
    op.drop_index(op.f('ix_world_book_entries_trigger_type'), table_name='world_book_entries')
    op.drop_index(op.f('ix_world_book_entries_is_active'), table_name='world_book_entries')
    op.drop_index(op.f('ix_world_book_entries_scope'), table_name='world_book_entries')
    op.drop_table('world_book_entries')
