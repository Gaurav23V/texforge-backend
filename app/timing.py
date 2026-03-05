import time
from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass
class TimingRecorder:
    """Collects monotonic stage timings for one compile request."""

    _start_time: float = field(default_factory=time.perf_counter)
    _durations: dict[str, float] = field(default_factory=dict)

    @contextmanager
    def stage(self, name: str):
        stage_start = time.perf_counter()
        try:
            yield
        finally:
            self._durations[name] = self._durations.get(name, 0.0) + (
                time.perf_counter() - stage_start
            )

    def set_duration(self, name: str, seconds: float) -> None:
        self._durations[name] = max(seconds, 0.0)

    def add_duration(self, name: str, seconds: float) -> None:
        self._durations[name] = self._durations.get(name, 0.0) + max(seconds, 0.0)

    def as_ms(self) -> dict[str, int]:
        data = {f"{name}_ms": int(duration * 1000) for name, duration in self._durations.items()}
        total_seconds = time.perf_counter() - self._start_time
        data["total_ms"] = int(total_seconds * 1000)
        return data
