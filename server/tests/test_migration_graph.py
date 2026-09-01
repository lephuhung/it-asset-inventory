"""Regression checks for the Alembic revision graph."""
from __future__ import annotations

from pathlib import Path

from alembic.script import ScriptDirectory


def test_public_ip_migration_runs_after_machine_current_schema() -> None:
    """A fresh database must create machine_current before altering it."""
    migrations_dir = Path(__file__).parents[1] / "alembic"
    script = ScriptDirectory(str(migrations_dir))

    public_ip_revision = script.get_revision("g8h9j0k1l2m3")

    assert public_ip_revision is not None
    assert "d7e8f9a0b1c2" in public_ip_revision._normalized_down_revisions
