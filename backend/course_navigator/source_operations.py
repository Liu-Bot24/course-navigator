"""Short-lived invalidations for source requests whose metadata is unresolved."""
from threading import RLock

from .library import CourseConflict


class SourceOperations:
    def __init__(self):
        self._lock = RLock()
        self._sequence = 0
        self._active: set[int] = set()
        self._invalidations: dict[str, int] = {}

    def begin(self) -> int:
        with self._lock:
            self._sequence += 1
            self._active.add(self._sequence)
            return self._sequence

    def finish(self, ticket: int) -> None:
        with self._lock:
            self._active.discard(ticket)
            oldest = min(self._active, default=self._sequence)
            self._invalidations = {key: sequence for key, sequence in self._invalidations.items()
                                   if sequence > oldest}

    def invalidate(self, keys: set[str]) -> None:
        with self._lock:
            if self._active:
                self._sequence += 1
                for key in keys:
                    self._invalidations[key] = self._sequence

    def check(self, ticket: int, keys: set[str]) -> None:
        with self._lock:
            if ticket not in self._active or any(self._invalidations.get(key, 0) > ticket for key in keys):
                raise CourseConflict("Course source was deleted or replaced while loading metadata")
