"""Bounded per-course scheduling without workers blocked on another worker."""

from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event, RLock


class KeyedExecutor:
    def __init__(self, max_workers: int, max_pending: int = 64):
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        self._max_workers = max_workers
        self._max_pending = max_pending
        self._lock = RLock()
        self._queues: dict[str, deque] = {}
        self._active: dict[str, Future] = {}
        self._count = 0
        self._closed = False
        self._drained = Event()
        self._drained.set()

    def submit(self, key: str, function, *args) -> Future:
        with self._lock:
            if self._closed:
                raise RuntimeError("Task scheduler is shutting down")
            if self._count >= self._max_pending:
                raise RuntimeError("Task queue is full; try again after a task finishes")
            future = Future()
            self._queues.setdefault(key, deque()).append((future, function, args))
            self._count += 1
            self._drained.clear()
            self._dispatch()
            return future

    def _dispatch(self):
        for key in list(self._queues):
            if len(self._active) >= self._max_workers:
                return
            if key in self._active:
                continue
            queue = self._queues[key]
            future, function, args = queue.popleft()
            if not queue:
                self._queues.pop(key)
            self._active[key] = future
            self._pool.submit(self._run, key, future, function, args)

    def _run(self, key, future, function, args):
        try:
            if future.set_running_or_notify_cancel():
                try:
                    future.set_result(function(*args))
                except BaseException as exc:
                    future.set_exception(exc)
        finally:
            with self._lock:
                self._active.pop(key)
                self._count -= 1
                # Give other courses their turn before draining one busy course.
                if key in self._queues:
                    queue = self._queues.pop(key)
                    self._queues[key] = queue
                self._dispatch()
                if self._count == 0:
                    self._drained.set()
                    if self._closed:
                        self._pool.shutdown(wait=False)

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False):
        with self._lock:
            self._closed = True
            if cancel_futures:
                for queue in self._queues.values():
                    for future, _, _ in queue:
                        future.cancel()
                        self._count -= 1
                self._queues.clear()
                for future in self._active.values():
                    future.cancel()
                if self._count == 0:
                    self._drained.set()
        if wait:
            self._drained.wait()
        if wait or cancel_futures or self._drained.is_set():
            # Let dispatched wrappers settle their public Future even when
            # shutdown races the start of an underlying worker.
            self._pool.shutdown(wait=wait, cancel_futures=False)
