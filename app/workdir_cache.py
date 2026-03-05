import asyncio
import hashlib
import re
import shutil
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path


class WorkdirCache:
    def __init__(self, root_dir: str, max_projects: int):
        self.root = Path(root_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_projects = max_projects
        self._entries: OrderedDict[str, Path] = OrderedDict()
        self._in_use_counts: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, project_id: str) -> Path:
        async with self._lock:
            workdir = self._entries.get(project_id)
            if workdir is None:
                workdir = self.root / self._project_dir_name(project_id)
                workdir.mkdir(parents=True, exist_ok=True)
                self._entries[project_id] = workdir
            else:
                self._entries.move_to_end(project_id)

            self._in_use_counts[project_id] = self._in_use_counts.get(project_id, 0) + 1
            await self._evict_if_needed_locked()
            return workdir

    async def release(self, project_id: str) -> None:
        async with self._lock:
            count = self._in_use_counts.get(project_id, 0)
            if count <= 1:
                self._in_use_counts.pop(project_id, None)
            else:
                self._in_use_counts[project_id] = count - 1
            await self._evict_if_needed_locked()

    @asynccontextmanager
    async def lease(self, project_id: str):
        workdir = await self.acquire(project_id)
        try:
            yield workdir
        finally:
            await self.release(project_id)

    async def _evict_if_needed_locked(self) -> None:
        while len(self._entries) > self.max_projects:
            evicted = False
            for project_id, workdir in list(self._entries.items()):
                if self._in_use_counts.get(project_id, 0) > 0:
                    continue
                self._safe_delete(workdir)
                self._entries.pop(project_id, None)
                evicted = True
                break
            if not evicted:
                return

    def _safe_delete(self, workdir: Path) -> None:
        resolved_workdir = workdir.resolve()
        if resolved_workdir == self.root:
            return
        if str(resolved_workdir).startswith(str(self.root) + "/"):
            shutil.rmtree(resolved_workdir, ignore_errors=True)

    def _project_dir_name(self, project_id: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", project_id)
        digest = hashlib.sha1(project_id.encode("utf-8")).hexdigest()[:8]
        return f"{safe}-{digest}"
