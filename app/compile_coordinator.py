import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable


@dataclass
class InFlightCompile:
    key: str
    task: asyncio.Task


class CompileCoordinator:
    """Coalesces same-key requests and cancels stale same-project compiles."""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._by_project: dict[str, InFlightCompile] = {}

    async def run(
        self,
        project_id: str,
        key: str,
        create_task: Callable[[], Awaitable[dict]],
    ) -> tuple[dict, bool]:
        created_new = False
        async with self._lock:
            in_flight = self._by_project.get(project_id)
            if in_flight is not None:
                if in_flight.key == key:
                    task = in_flight.task
                else:
                    in_flight.task.cancel()
                    task = asyncio.create_task(create_task())
                    self._by_project[project_id] = InFlightCompile(key=key, task=task)
                    created_new = True
            else:
                task = asyncio.create_task(create_task())
                self._by_project[project_id] = InFlightCompile(key=key, task=task)
                created_new = True

        try:
            result = await asyncio.shield(task)
            return result, created_new
        finally:
            async with self._lock:
                current = self._by_project.get(project_id)
                if current is not None and current.task is task and task.done():
                    self._by_project.pop(project_id, None)
