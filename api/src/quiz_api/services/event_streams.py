"""Shared Redis pub/sub subscriptions for local SSE quiz listeners."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import structlog

from quiz_api.events import QuizEventEnvelope, quiz_channel
from quiz_api.observability import (
    ACTIVE_STREAMS,
    DEPENDENCY_FAILURES,
    STREAM_RECONNECTS,
    record_event_delivery_delay,
)

logger = structlog.get_logger(__name__)


class RedisPubSub(Protocol):
    """Subset of an asynchronous Redis pub/sub connection used by the broker."""

    async def aclose(self) -> None:
        """Close the pub/sub connection."""

    async def subscribe(self, *channels: str) -> None:
        """Subscribe the connection to quiz channels."""

    async def unsubscribe(self, *channels: str) -> None:
        """Remove the connection's quiz channel subscriptions."""

    def listen(self) -> AsyncIterator[dict[str, Any]]:
        """Yield incoming Redis pub/sub messages."""


class RedisPubSubFactory(Protocol):
    """Create independent pub/sub connections from the lifecycle-owned Redis client."""

    def pubsub(self) -> RedisPubSub:
        """Create one pub/sub connection."""


@dataclass(slots=True)
class StreamSubscription:
    """One local SSE listener queue and its explicit cleanup operation."""

    _broker: QuizEventBroker
    _closed: bool
    _quiz_id: UUID
    queue: asyncio.Queue[QuizEventEnvelope]

    async def close(self) -> None:
        """Remove the listener and stop its Redis subscription when it was the last one."""
        if not self._closed:
            self._closed = True
            await self._broker.disconnect(self._quiz_id, self.queue)


class QuizEventBroker:
    """Fan each quiz Redis channel into bounded queues for this process's SSE streams."""

    def __init__(self, redis: RedisPubSubFactory, *, queue_size: int) -> None:
        """Use one Redis client factory and bounded per-listener queues."""
        self._listeners: dict[UUID, set[asyncio.Queue[QuizEventEnvelope]]] = {}
        self._listener_tasks: dict[UUID, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()
        self._queue_size = queue_size
        self._redis = redis

    async def connect(self, quiz_id: UUID) -> StreamSubscription:
        """Register a local listener and begin Redis subscription on the first connection."""
        queue: asyncio.Queue[QuizEventEnvelope] = asyncio.Queue(maxsize=self._queue_size)
        async with self._lock:
            listeners = self._listeners.setdefault(quiz_id, set())
            listeners.add(queue)
            ACTIVE_STREAMS.inc()
            if quiz_id not in self._listener_tasks:
                self._listener_tasks[quiz_id] = asyncio.create_task(self._listen(quiz_id))
        return StreamSubscription(self, False, quiz_id, queue)

    async def disconnect(self, quiz_id: UUID, queue: asyncio.Queue[QuizEventEnvelope]) -> None:
        """Remove a local listener and cancel its Redis task when no listeners remain."""
        task: asyncio.Task[None] | None = None
        async with self._lock:
            listeners = self._listeners.get(quiz_id)
            if listeners is None:
                return
            listeners.discard(queue)
            ACTIVE_STREAMS.dec()
            if not listeners:
                self._listeners.pop(quiz_id, None)
                task = self._listener_tasks.pop(quiz_id, None)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def close(self) -> None:
        """Stop all listener tasks before the lifecycle-owned Redis client closes."""
        async with self._lock:
            tasks = tuple(self._listener_tasks.values())
            self._listener_tasks = {}
            self._listeners = {}
            ACTIVE_STREAMS.set(0)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _listen(self, quiz_id: UUID) -> None:
        """Read one quiz channel and reconnect while local listeners still exist."""
        channel = quiz_channel(quiz_id)
        while await self._has_listeners(quiz_id):
            pubsub = self._redis.pubsub()
            try:
                await pubsub.subscribe(channel)
                async for message in pubsub.listen():
                    if message.get("type") != "message":
                        continue
                    data = message.get("data")
                    if not isinstance(data, str):
                        continue
                    try:
                        event = QuizEventEnvelope.model_validate_json(data)
                    except ValueError:
                        continue
                    if event.quiz_id == quiz_id:
                        await self._fan_out(quiz_id, event)
            except asyncio.CancelledError:
                raise
            except Exception:
                DEPENDENCY_FAILURES.labels(dependency="redis").inc()
                STREAM_RECONNECTS.inc()
                logger.exception("quiz_event_listener_failed", quiz_id=str(quiz_id))
                await asyncio.sleep(1)
            finally:
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()

    async def _has_listeners(self, quiz_id: UUID) -> bool:
        """Return whether this process still has any local stream for a quiz."""
        async with self._lock:
            return bool(self._listeners.get(quiz_id))

    async def _fan_out(self, quiz_id: UUID, event: QuizEventEnvelope) -> None:
        """Deliver an event without allowing one slow browser to block other listeners."""
        async with self._lock:
            queues = tuple(self._listeners.get(quiz_id, ()))
        for queue in queues:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)
        record_event_delivery_delay(event.occurred_at)
