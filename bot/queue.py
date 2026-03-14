from __future__ import annotations

import asyncio
from typing import Generic, List, TypeVar

T = TypeVar("T")


class SongQueue(Generic[T]):
    """Async wrapper around asyncio.Queue with helper methods for music queues."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[T] = asyncio.Queue()

    async def put(self, item: T) -> None:
        await self._queue.put(item)

    async def get(self) -> T:
        return await self._queue.get()

    async def clear(self) -> None:
        while not self._queue.empty():
            self._queue.get_nowait()

    async def snapshot(self) -> List[T]:
        # asyncio.Queue stores pending items in an internal deque.
        return list(self._queue._queue)  # type: ignore[attr-defined]

    def __len__(self) -> int:
        return self._queue.qsize()
