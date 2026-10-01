"""Add tier classification to custom artifacts.

Revision ID: b6c7d8e9f0a2
Revises: b5c6d7e8f9a0

Tier replaces the hardcoded TIER1_CUSTOM_TOOLS / TIER2_CUSTOM_TOOLS whitelist
in DeepAgent's `catalog.py`. Admins promote a Custom.* artifact to Tier 1 by
setting `tier=1` so the artifact is eligible for initial collection; Tier 2
artifacts only run after Tier 1 evidence triggers them.

Default = 2 (safer: Tier 1 must be an explicit opt-in). The migration sets
tier=1 for the built-in triage wrappers that were previously Tier 1 via
hardcoded whitelist, so behavior is preserved without forcing a backend
release for every tier change.

Idempotent: safe to run on databases where this migration was applied out of
band (e.g. via direct ALTER TABLE during incident response).
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "b6c7d8e9f0a2"
down_revision = "b5c6d7e8f9a0"
branch_labels = None
depends_on = None


# Names of artifacts that were Tier 1 in the hardcoded whitelist (see
# deepagent/catalog.py TIER1_CUSTOM_TOOLS prior to this migration). Preserve
# tier=1 for these so existing investigations continue to behave identically.
_TIER1_ARTIFACT_NAMES = (
    "Custom.DFIR.Windows.Triage",
    "Custom.DFIR.Linux.Triage",
)


def upgrade() -> None:
    # 1) Add tier column if missing. Idempotent: ALTER TABLE ADD COLUMN IF NOT
    # EXISTS is a no-op when column is already present.
    op.execute(
        sa.text(
            "ALTER TABLE velociraptor_artifacts "
            "ADD COLUMN IF NOT EXISTS tier SMALLINT NOT NULL DEFAULT 2"
        )
    )

    # 2) Add CHECK constraint if missing. Idempotent: query information_schema
    # and skip when constraint already exists (PostgreSQL has no native
    # ADD CONSTRAINT IF NOT EXISTS).
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE constraint_name = 'ck_velociraptor_artifacts_tier_range'
                    AND table_name = 'velociraptor_artifacts'
                ) THEN
                    ALTER TABLE velociraptor_artifacts
                    ADD CONSTRAINT ck_velociraptor_artifacts_tier_range
                    CHECK (tier IN (1, 2));
                END IF;
            END $$
            """
        )
    )

    # 3) Promote built-in triage wrappers to Tier 1. Idempotent: UPDATE is a
    # no-op for rows already at tier=1.
    op.execute(
        sa.text(
            "UPDATE velociraptor_artifacts SET tier = 1 WHERE name = ANY(:names)"
        ).bindparams(names=list(_TIER1_ARTIFACT_NAMES))
    )


def downgrade() -> None:
    # Drop the check constraint and column. DOWN is rare in production but
    # supported for symmetry.
    op.execute(
        sa.text(
            "ALTER TABLE velociraptor_artifacts "
            "DROP CONSTRAINT IF EXISTS ck_velociraptor_artifacts_tier_range"
        )
    )
    op.execute(
        sa.text("ALTER TABLE velociraptor_artifacts DROP COLUMN IF EXISTS tier")
    )
