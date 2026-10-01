"""Add a per-quiz outbox sequence allocator.

Revision ID: 20261001_0002
Revises: 20260930_0001
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261001_0002"
down_revision: str | None = "20260930_0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Add an atomically incremented event sequence counter to quizzes."""
    op.add_column(
        "quiz",
        sa.Column("next_event_seq", sa.BigInteger(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    """Remove the per-quiz event sequence counter."""
    op.drop_column("quiz", "next_event_seq")
