"""merge public_ip with drop_org_assign_rules

Revision ID: c5416fb6b905
Revises: 9b4c5d6e7f8a, g8h9j0k1l2m3
Create Date: 2026-08-27 07:34:09.290537
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'c5416fb6b905'
down_revision = ('9b4c5d6e7f8a', 'g8h9j0k1l2m3')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
