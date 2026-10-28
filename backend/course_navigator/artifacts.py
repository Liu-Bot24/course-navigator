"""Process-local ownership of temporary extraction files.

Each operation uses its own directory. Cleanup can reclaim inactive files while
an active operation keeps both its current and future audio chunks available.
"""

from contextlib import contextmanager
from pathlib import Path
from threading import RLock
import shutil


lock = RLock()
_active: dict[Path, int] = {}
_pending_removal: set[Path] = set()


def is_active(path: Path) -> bool:
    resolved = path.resolve()
    with lock:
        return any(resolved == root or root in resolved.parents for root in _active)


def contains_active(path: Path) -> bool:
    resolved = path.resolve()
    with lock:
        return any(resolved == root or resolved in root.parents for root in _active)


@contextmanager
def lease(path: Path, *, remove_on_error: bool = False):
    resolved = path.resolve()
    with lock:
        _active[resolved] = _active.get(resolved, 0) + 1
    try:
        yield path
    except BaseException:
        if remove_on_error:
            remove_tree(path)
        raise
    finally:
        with lock:
            _active[resolved] -= 1
            if _active[resolved] == 0:
                _active.pop(resolved)
                if resolved in _pending_removal:
                    _pending_removal.remove(resolved)
                    if resolved.exists():
                        shutil.rmtree(resolved)


def remove_tree(path: Path) -> None:
    """Delete a tree, deferring only directories leased at this instant."""
    resolved = path.resolve()
    with lock:
        active_children = [root for root in _active if root == resolved or resolved in root.parents]
        if not active_children:
            if resolved.exists():
                shutil.rmtree(resolved)
            return
        _pending_removal.update(active_children)
        if resolved in _active:
            return
        if not resolved.exists():
            return
        for child in resolved.iterdir():
            if child.is_dir():
                if child.resolve() not in active_children:
                    remove_tree(child)
            else:
                child.unlink(missing_ok=True)
