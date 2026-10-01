"""Seed a deterministic vocabulary quiz for local demonstrations."""

import asyncio
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from quiz_api.database.models import Question, Quiz, QuizStatus, Round, RoundStatus
from quiz_api.settings import get_database_settings

DEMO_QUIZ_ID: Final[UUID] = UUID("10000000-0000-0000-0000-000000000001")
DEMO_HOST_ID: Final[str] = "demo-host"


@dataclass(frozen=True, slots=True)
class SeedQuestion:
    """Immutable question content inserted by the demo seed command."""

    id: UUID
    prompt: str
    options: tuple[str, ...]
    correct_answer: str


@dataclass(frozen=True, slots=True)
class SeedResult:
    """Counts of records inserted by one seed-command invocation."""

    created_questions: int
    created_quiz: bool
    created_rounds: int


DEMO_QUESTIONS: Final[tuple[SeedQuestion, ...]] = (
    SeedQuestion(
        id=UUID("20000000-0000-0000-0000-000000000001"),
        prompt="Which word means to make something less severe or painful?",
        options=("alleviate", "exacerbate", "obscure", "revoke"),
        correct_answer="alleviate",
    ),
    SeedQuestion(
        id=UUID("20000000-0000-0000-0000-000000000002"),
        prompt="Which word best describes someone who is careful and persistent?",
        options=("diligent", "impulsive", "vague", "fragile"),
        correct_answer="diligent",
    ),
    SeedQuestion(
        id=UUID("20000000-0000-0000-0000-000000000003"),
        prompt="Which word means clear and easy to understand?",
        options=("lucid", "tedious", "scarce", "rigid"),
        correct_answer="lucid",
    ),
)


def demo_round_id(question: SeedQuestion) -> UUID:
    """Derive a stable round ID from a seeded question ID."""
    return UUID(f"30000000-0000-0000-0000-{question.id.hex[-12:]}")


async def seed_demo_data(session: AsyncSession) -> SeedResult:
    """Insert missing deterministic demo records without changing existing state."""
    created_questions = 0
    for seed_question in DEMO_QUESTIONS:
        if await session.get(Question, seed_question.id) is None:
            session.add(
                Question(
                    id=seed_question.id,
                    prompt=seed_question.prompt,
                    options=list(seed_question.options),
                    correct_answer=seed_question.correct_answer,
                ),
            )
            created_questions += 1

    quiz = await session.get(Quiz, DEMO_QUIZ_ID)
    created_quiz = quiz is None
    if quiz is None:
        quiz = Quiz(
            id=DEMO_QUIZ_ID,
            host_id=DEMO_HOST_ID,
            status=QuizStatus.DRAFT,
        )
        session.add(quiz)
        await session.flush()

    created_rounds = 0
    for seed_question in DEMO_QUESTIONS:
        round_id = demo_round_id(seed_question)
        if await session.get(Round, round_id) is None:
            session.add(
                Round(
                    id=round_id,
                    question_id=seed_question.id,
                    quiz_id=quiz.id,
                    status=RoundStatus.PENDING,
                ),
            )
            created_rounds += 1

    return SeedResult(
        created_questions=created_questions,
        created_quiz=created_quiz,
        created_rounds=created_rounds,
    )


async def run_seed_command() -> SeedResult:
    """Connect to the configured database and commit a safe seed transaction."""
    engine = create_async_engine(get_database_settings().database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory.begin() as session:
            return await seed_demo_data(session)
    finally:
        await engine.dispose()


def main() -> None:
    """Run the deterministic demo-data seed command."""
    result = asyncio.run(run_seed_command())
    print(
        "Seed complete: "
        f"quiz_created={result.created_quiz}, "
        f"questions_created={result.created_questions}, "
        f"rounds_created={result.created_rounds}",
    )


if __name__ == "__main__":
    main()
