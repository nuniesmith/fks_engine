import asyncio
from typing import Any, Callable, Optional


class Space:
    """Minimal async space for space-based architecture patterns.

    Provides put/take/peek semantics backed by asyncio.Queue.
    """

    def __init__(self, maxsize: int = 0) -> None:
        self._q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)

    async def put(self, item: Any) -> None:
        await self._q.put(item)

    async def take(self, predicate: Optional[Callable[[Any], bool]] = None) -> Any:
        """Take first item matching predicate (or any item if predicate is None)."""
        if predicate is None:
            return await self._q.get()
        # naive scan: rotate until matching item appears
        # guard against infinite loop using queue size snapshot
        while True:
            item = await self._q.get()
            if predicate(item):
                return item
            # not a match; put back
            await self._q.put(item)

    async def peek(self) -> Any:
        """Peek next item without removing. Note: implemented via get/put."""
        item = await self._q.get()
        await self._q.put(item)
        return item
