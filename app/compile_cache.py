import asyncio
import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional


TOOLCHAIN_MARKER = "texforge-v1"


@dataclass
class CompileCacheEntry:
    key: str
    pdf_path: str
    project_id: str
    engine: str
    flags: str
    signed_url: Optional[str] = None
    signed_url_expires_at: float = 0.0
    created_at: float = 0.0

    def is_signed_url_valid(self, safety_window_seconds: int = 5) -> bool:
        return bool(self.signed_url) and self.signed_url_expires_at > (time.time() + safety_window_seconds)


def build_compile_key(project_id: str, tex_content: str, engine: str, flags: str) -> str:
    digest = hashlib.sha256()
    digest.update(project_id.encode("utf-8"))
    digest.update(b"\0")
    digest.update(tex_content.encode("utf-8"))
    digest.update(b"\0")
    digest.update(engine.encode("utf-8"))
    digest.update(b"\0")
    digest.update(flags.encode("utf-8"))
    digest.update(b"\0")
    digest.update(TOOLCHAIN_MARKER.encode("utf-8"))
    return digest.hexdigest()


class CompileCache:
    def __init__(self, max_entries: int = 500):
        self.max_entries = max_entries
        self._entries: OrderedDict[str, CompileCacheEntry] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[CompileCacheEntry]:
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            self._entries.move_to_end(key)
            return entry

    async def set(self, entry: CompileCacheEntry) -> None:
        async with self._lock:
            self._entries[entry.key] = entry
            self._entries.move_to_end(entry.key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    async def invalidate_project(self, project_id: str) -> None:
        async with self._lock:
            to_delete = [key for key, value in self._entries.items() if value.project_id == project_id]
            for key in to_delete:
                self._entries.pop(key, None)
