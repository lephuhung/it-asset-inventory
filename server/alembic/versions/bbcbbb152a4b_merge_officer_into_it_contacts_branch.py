"""merge officer into it-contacts branch

Revision ID: bbcbbb152a4b
Revises: a5b6c7d8e9f1, c7d8e9f0a1b2
Create Date: 2026-09-07 13:04:43.942412
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'bbcbbb152a4b'
down_revision = ('a5b6c7d8e9f1', 'c7d8e9f0a1b2')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
