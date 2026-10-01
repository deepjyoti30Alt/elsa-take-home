"""Create durable quiz runtime tables.

Revision ID: 20260930_0001
Revises:
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260930_0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

quiz_status = sa.Enum(
    "draft",
    "active",
    "completed",
    name="quiz_status",
    native_enum=False,
    create_constraint=True,
)
round_status = sa.Enum(
    "pending",
    "open",
    "closed",
    name="round_status",
    native_enum=False,
    create_constraint=True,
)
score_reason = sa.Enum(
    "correct_answer",
    name="score_reason",
    native_enum=False,
    create_constraint=True,
)
outbox_event_type = sa.Enum(
    "answer_accepted",
    "round_closed",
    "round_opened",
    name="outbox_event_type",
    native_enum=False,
    create_constraint=True,
)


def upgrade() -> None:
    """Create the durable source-of-truth schema for live quiz state."""
    op.create_table(
        "question",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("correct_answer", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_question"),
    )
    op.create_table(
        "quiz",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("status", quiz_status, nullable=False),
        sa.Column("host_id", sa.String(length=255), nullable=False),
        sa.Column("current_round_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_quiz"),
    )
    op.create_table(
        "round",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("quiz_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("status", round_status, nullable=False),
        sa.Column("opens_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["question_id"], ["question.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["quiz_id"], ["quiz.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_round"),
    )
    op.create_foreign_key(
        "fk_quiz_current_round",
        "quiz",
        "round",
        ["current_round_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "participant",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("quiz_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("join_key", sa.String(length=255), nullable=False),
        sa.Column("total_score", sa.Integer(), nullable=False),
        sa.Column("total_response_ms", sa.BigInteger(), nullable=False),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["quiz_id"], ["quiz.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_participant"),
        sa.UniqueConstraint("quiz_id", "join_key", name="uq_participant_quiz_join_key"),
    )
    op.create_index(
        "ix_participant_quiz_ranking",
        "participant",
        ["quiz_id", "total_score", "total_response_ms"],
        unique=False,
    )
    op.create_table(
        "answer_submission",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("participant_id", sa.Uuid(), nullable=False),
        sa.Column("round_id", sa.Uuid(), nullable=False),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("answer", sa.String(length=255), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("response_ms", sa.Integer(), nullable=False),
        sa.Column("awarded_points", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["participant_id"], ["participant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["round_id"], ["round.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_answer_submission"),
        sa.UniqueConstraint("participant_id", "round_id", name="uq_answer_participant_round"),
    )
    op.create_table(
        "score_ledger",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("participant_id", sa.Uuid(), nullable=False),
        sa.Column("round_id", sa.Uuid(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("reason", score_reason, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["participant_id"], ["participant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["round_id"], ["round.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_score_ledger"),
        sa.UniqueConstraint("participant_id", "round_id", name="uq_score_ledger_participant_round"),
    )
    op.create_table(
        "outbox_event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("quiz_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("type", outbox_event_type, nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["quiz_id"], ["quiz.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_event"),
        sa.UniqueConstraint("quiz_id", "seq", name="uq_outbox_quiz_sequence"),
    )
    op.create_index(
        "ix_outbox_unpublished",
        "outbox_event",
        ["published_at", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drop all quiz runtime tables in dependency-safe reverse order."""
    op.drop_index("ix_outbox_unpublished", table_name="outbox_event")
    op.drop_table("outbox_event")
    op.drop_table("score_ledger")
    op.drop_table("answer_submission")
    op.drop_index("ix_participant_quiz_ranking", table_name="participant")
    op.drop_table("participant")
    op.drop_constraint("fk_quiz_current_round", "quiz", type_="foreignkey")
    op.drop_table("round")
    op.drop_table("quiz")
    op.drop_table("question")
