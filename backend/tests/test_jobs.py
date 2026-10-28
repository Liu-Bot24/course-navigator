from threading import Event

import pytest

from course_navigator.jobs import KeyedExecutor


def test_same_course_serializes_without_blocking_other_courses():
    executor = KeyedExecutor(max_workers=2)
    started, release = Event(), Event()
    order = []

    def first():
        started.set()
        assert release.wait(3)
        order.append("first")

    try:
        initial = executor.submit("course-a", first)
        assert started.wait(2)
        second = executor.submit("course-a", lambda: order.append("second"))
        other = executor.submit("course-b", lambda: "other course finished")
        assert other.result(timeout=1) == "other course finished"
        assert not second.done()
        release.set()
        initial.result(timeout=2)
        second.result(timeout=2)
        assert order == ["first", "second"]
    finally:
        release.set()
        executor.shutdown()


def test_queue_limit_and_shutdown_cancel_pending_work():
    executor = KeyedExecutor(max_workers=1, max_pending=2)
    started, release = Event(), Event()

    def block():
        started.set()
        assert release.wait(3)

    try:
        running = executor.submit("a", block)
        assert started.wait(2)
        pending = executor.submit("a", lambda: pytest.fail("cancelled work ran"))
        with pytest.raises(RuntimeError, match="full"):
            executor.submit("b", lambda: None)
        executor.shutdown(wait=False, cancel_futures=True)
        assert pending.cancelled()
        release.set()
        running.result(timeout=2)
    finally:
        release.set()
        executor.shutdown()
