from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from threading import RLock

from pydantic import ValidationError

from .models import CourseItem, LibraryState

SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
logger = logging.getLogger(__name__)


class CourseConflict(ValueError):
    """The course changed or was removed while an operation was running."""


def course_input(item: CourseItem) -> tuple:
    """Inputs whose changes invalidate an in-flight generated result."""
    metadata = item.metadata
    return (item.title, item.source_url, item.duration, item.video_source_type, item.media_revision,
            str(item.local_video_path) if item.local_video_path else None,
            item.transcript_language,
            tuple((s.start, s.end, s.text) for s in item.transcript),
            metadata.language if metadata else None,
            metadata.description if metadata else None)


class CourseLibrary:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.items_dir = self.data_dir / "items"
        self.library_state_path = self.data_dir / "library-state.json"
        self.lock = RLock()
        self.read_errors: dict[str, str] = {}
        # Parsed records keyed by file stamp. Every read still validates into a
        # new CourseItem, so callers never share mutable state with the cache.
        self._payloads: dict[str, tuple[tuple[int, int], dict]] = {}
        self.items_dir.mkdir(parents=True, exist_ok=True)

    def save(self, item: CourseItem) -> None:
        """Store a complete record. Runtime edits should use update instead."""
        with self.lock:
            self._write(item)

    def create(self, item: CourseItem) -> CourseItem:
        with self.lock:
            path = self._item_path(item.id)
            if path and path.exists():
                raise CourseConflict("Course already exists; reload before updating")
            self._write(item)
            return item

    def update(self, expected: CourseItem, changes: Mapping[str, object], *, check_inputs: bool = False,
               input_key: Callable[[CourseItem], object] | None = None) -> CourseItem:
        """Atomically apply owned fields to the current instance, rejecting stale work.

        Slow work happens before this call. Unrelated fields always come from the
        latest record; overlapping edits and changed generation inputs conflict.
        """
        with self.lock:
            current = self.validate_snapshot(expected, check_inputs=check_inputs, input_key=input_key)
            for field, value in changes.items():
                if field in {"id", "instance_id"}:
                    raise ValueError("Course identity cannot be changed")
                if getattr(current, field) != getattr(expected, field) and getattr(current, field) != value:
                    raise CourseConflict(f"Course field '{field}' changed; reload before saving")
            updated = CourseItem.model_validate(current.model_copy(update=dict(changes)).model_dump())
            self._write(updated)
            return updated

    def validate_snapshot(self, expected: CourseItem, *, check_inputs: bool = False,
                          input_key: Callable[[CourseItem], object] | None = None) -> CourseItem:
        with self.lock:
            current = self.get(expected.id)
            if current is None or current.instance_id != expected.instance_id:
                raise CourseConflict("Course was deleted or replaced; discard this result")
            key = input_key or (course_input if check_inputs else None)
            if key is not None and key(current) != key(expected):
                raise CourseConflict("Course inputs changed; generate again from the updated course")
            return current

    def _write(self, item: CourseItem) -> None:
        path = self._item_path(item.id)
        if not path:
            raise ValueError("Invalid course item id")
        tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        self._payloads.pop(item.id, None)
        try:
            tmp_path.write_text(
                item.model_dump_json(indent=2),
                encoding="utf-8",
            )
            tmp_path.replace(path)
        finally:
            tmp_path.unlink(missing_ok=True)

    def get(self, item_id: str) -> CourseItem | None:
        with self.lock:
            path = self._item_path(item_id)
            if not path:
                return None
            try:
                stat = path.stat()
            except FileNotFoundError:
                self._payloads.pop(item_id, None)
                return None
            stamp = (stat.st_mtime_ns, stat.st_size)
            cached = self._payloads.get(item_id)
            payload = cached[1] if cached and cached[0] == stamp else self._read_payload(path)
            item = CourseItem.model_validate(payload)
            if item.id != item_id:
                raise ValueError("Course id does not match its filename")
            self._payloads[item_id] = (stamp, payload)
            return item

    def _read_payload(self, path: Path) -> dict:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Course record must be a JSON object")
        if "instance_id" not in payload:
            # Stable for a legacy record until its next successful write.
            payload["instance_id"] = uuid.uuid5(uuid.NAMESPACE_URL, f"{path.resolve()}:{payload.get('created_at', '')}").hex
        return payload

    def delete(self, item_id: str) -> bool:
        with self.lock:
            path = self._item_path(item_id)
            self._payloads.pop(item_id, None)
            if not path or not path.exists():
                return False
            path.unlink()
            return True

    def list_items(self) -> list[CourseItem]:
        items = []
        errors = {}
        with self.lock:
            present = set()
            for path in self.items_dir.glob("*.json"):
                if not path.is_file():
                    continue
                present.add(path.stem)
                try:
                    item = self.get(path.stem)
                    if item is not None:
                        items.append(item)
                except (OSError, ValueError, ValidationError) as exc:
                    self._payloads.pop(path.stem, None)
                    message = f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}"
                    errors[path.name] = message
                    if self.read_errors.get(path.name) != message:
                        logger.error("Cannot load course record %s: %s. Original file retained for recovery.", path, exc)
            # Forget records whose files were removed outside the app.
            for item_id in self._payloads.keys() - present:
                del self._payloads[item_id]
            self.read_errors = errors
        return sorted(items, key=_course_sort_key)

    def load_state(self) -> LibraryState:
        if not self.library_state_path.exists():
            return LibraryState()
        payload = json.loads(self.library_state_path.read_text(encoding="utf-8"))
        return LibraryState.model_validate(payload)

    def save_state(self, state: LibraryState) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self.library_state_path.with_name(
            f".{self.library_state_path.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            tmp_path.write_text(
                state.model_dump_json(indent=2),
                encoding="utf-8",
            )
            tmp_path.replace(self.library_state_path)
        finally:
            tmp_path.unlink(missing_ok=True)

    def _item_path(self, item_id: str) -> Path | None:
        if not SAFE_ID_RE.fullmatch(item_id):
            return None
        return self.items_dir / f"{item_id}.json"


def _course_sort_key(item: CourseItem) -> tuple[str, str, int, float, float]:
    collection_group = (item.collection_group_title or "").casefold()
    collection = (item.collection_title or "未归档").casefold()
    has_index = 0 if item.course_index is not None else 1
    numeric_order = item.course_index if item.course_index is not None else item.sort_order
    if numeric_order is None:
        numeric_order = float("inf")
    return (collection_group, collection, has_index, numeric_order, -_created_at_timestamp(item.created_at))


def _created_at_timestamp(value: str) -> float:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0
