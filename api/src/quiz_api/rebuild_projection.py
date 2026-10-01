"""Command-line entry point for rebuilding one Redis leaderboard projection."""

import argparse
import asyncio
from typing import cast
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from quiz_api.services.outbox_relay import RedisEventTransport, RedisLeaderboardProjection
from quiz_api.services.projection_rebuild import ProjectionRebuildService
from quiz_api.settings import get_settings


def parse_arguments() -> argparse.Namespace:
    """Parse the quiz identifier whose Redis projection should be replaced."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("quiz_id", type=UUID)
    return parser.parse_args()


async def rebuild(quiz_id: UUID) -> int:
    """Open scoped resources, rebuild one projection, and close all connections."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        service = ProjectionRebuildService(
            session_factory,
            RedisLeaderboardProjection(cast(RedisEventTransport, redis)),
        )
        return await service.rebuild_quiz(quiz_id)
    finally:
        await redis.aclose()
        await engine.dispose()


def main() -> None:
    """Run the rebuild command and print the number of projected participants."""
    arguments = parse_arguments()
    projected_count = asyncio.run(rebuild(arguments.quiz_id))
    print(f"Projection rebuilt for {arguments.quiz_id}: participants={projected_count}")


if __name__ == "__main__":
    main()
