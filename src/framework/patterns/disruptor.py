import asyncio
from typing import Any, Callable, List, Optional


class EventProcessor:
    """Base class for event processors used by Disruptor.

    Subclasses should override `on_event` to process events.
    """

    async def on_event(self, event: Any, sequence: int) -> None:
        raise NotImplementedError


class Disruptor:
    """Minimal async disruptor-like ring buffer using an asyncio.Queue.

    This is a pragmatic, simplified implementation to satisfy the engine's
    expectations: processors can be registered, start() spawns a background
    task that consumes events and dispatches to processors, and publish()
    enqueues events.
    """

    def __init__(self, buffer_size: int = 65536) -> None:
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=buffer_size)
        self._processors: List[EventProcessor] = []
        self._worker_task: Optional[asyncio.Task] = None
        self._sequence: int = 0
        self._stopped = asyncio.Event()

    def add_processor(self, processor: EventProcessor) -> None:
        self._processors.append(processor)

    async def start(self) -> None:
        if self._worker_task is not None and not self._worker_task.done():
            return
        self._stopped.clear()
        self._worker_task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stopped.set()
        # Enqueue sentinel to unblock queue.get()
        try:
            self._queue.put_nowait(None)
        except asyncio.QueueFull:
            pass
        if self._worker_task:
            try:
                await self._worker_task
            except Exception:
                pass
            self._worker_task = None

    async def publish(self, event: Any) -> None:
        await self._queue.put(event)

    async def _run(self) -> None:
        while not self._stopped.is_set():
            event = await self._queue.get()
            if event is None:
                # sentinel for shutdown
                break
            seq = self._sequence
            self._sequence += 1
            # fan-out to processors; exceptions are isolated per processor
            await asyncio.gather(
                *[self._safe_call(p, event, seq) for p in self._processors],
                return_exceptions=True,
            )

    async def _safe_call(self, processor: EventProcessor, event: Any, seq: int) -> None:
        try:
            await processor.on_event(event, seq)
        except Exception:
            # Keep running even if a processor fails
            pass
