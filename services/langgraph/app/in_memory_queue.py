"""Bounded process-local queue for the zero-external-DB MVP ingress path."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
import time
from typing import Generic, TypeVar

T = TypeVar("T")


class QueueFullError(RuntimeError):
    """The bounded queue cannot accept another item."""


class DuplicateOperationError(RuntimeError):
    """The operation id is already present in the process-local dedupe window."""


@dataclass(frozen=True, slots=True)
class InMemoryEnvelope(Generic[T]):
    operation_id: str
    payload: T
    enqueued_at_monotonic: float


@dataclass(frozen=True, slots=True)
class QueueSnapshot:
    depth: int
    capacity: int
    dedupe_entries: int
    durable: bool = False
    process_local: bool = True


class BoundedInMemoryQueue(Generic[T]):
    """FIFO queue with bounded memory and bounded process-local dedupe.

    Semantics are deliberately modest:
    - process-local only;
    - non-durable across restart;
    - no cross-worker coordination;
    - no exactly-once delivery claim.
    """

    def __init__(self, *, maxsize: int, dedupe_capacity: int | None = None) -> None:
        if maxsize <= 0:
            raise ValueError("maxsize must be positive")
        self._queue: asyncio.Queue[InMemoryEnvelope[T]] = asyncio.Queue(maxsize=maxsize)
        self._dedupe_capacity = dedupe_capacity if dedupe_capacity is not None else maxsize * 4
        if self._dedupe_capacity < maxsize:
            raise ValueError("dedupe_capacity must be >= maxsize")
        self._seen: OrderedDict[str, None] = OrderedDict()

    @property
    def maxsize(self) -> int:
        return self._queue.maxsize

    def qsize(self) -> int:
        return self._queue.qsize()

    def snapshot(self) -> QueueSnapshot:
        return QueueSnapshot(
            depth=self._queue.qsize(),
            capacity=self._queue.maxsize,
            dedupe_entries=len(self._seen),
        )

    def put_nowait(self, *, operation_id: str, payload: T) -> InMemoryEnvelope[T]:
        operation_id = operation_id.strip()
        if not operation_id:
            raise ValueError("operation_id is required")
        if operation_id in self._seen:
            raise DuplicateOperationError(operation_id)

        envelope = InMemoryEnvelope(
            operation_id=operation_id,
            payload=payload,
            enqueued_at_monotonic=time.monotonic(),
        )
        try:
            self._queue.put_nowait(envelope)
        except asyncio.QueueFull as exc:
            raise QueueFullError("in-memory queue is full") from exc

        self._seen[operation_id] = None
        self._seen.move_to_end(operation_id)
        while len(self._seen) > self._dedupe_capacity:
            self._seen.popitem(last=False)
        return envelope

    async def get(self) -> InMemoryEnvelope[T]:
        return await self._queue.get()

    def get_nowait(self) -> InMemoryEnvelope[T]:
        try:
            return self._queue.get_nowait()
        except asyncio.QueueEmpty as exc:
            raise LookupError("in-memory queue is empty") from exc

    def task_done(self) -> None:
        self._queue.task_done()

    async def join(self) -> None:
        await self._queue.join()
