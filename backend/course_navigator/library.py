from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from .models import CourseItem

SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class CourseLibrary:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.items_dir = self.data_dir / "items"
        self.items_dir.mkdir(parents=True, exist_ok=True)

    def save(self, item: CourseItem) -> None:
        path = self._item_path(item.id)
        if not path:
            raise ValueError("Invalid course item id")
        path.write_text(
            item.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def get(self, item_id: str) -> CourseItem | None:
        path = self._item_path(item_id)
        if not path or not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return CourseItem.model_validate(payload)

    def delete(self, item_id: str) -> bool:
        path = self._item_path(item_id)
        if not path or not path.exists():
            return False
        path.unlink()
        return True

    def list_items(self) -> list[CourseItem]:
        items = [
            CourseItem.model_validate(json.loads(path.read_text(encoding="utf-8")))
            for path in self.items_dir.glob("*.json")
            if path.is_file()
        ]
        return sorted(items, key=_course_sort_key)

    def _item_path(self, item_id: str) -> Path | None:
        if not SAFE_ID_RE.match(item_id):
            return None
        return self.items_dir / f"{item_id}.json"


def _course_sort_key(item: CourseItem) -> tuple[str, int, float, float]:
    collection = (item.collection_title or "未归档").casefold()
    has_index = 0 if item.course_index is not None else 1
    numeric_order = item.course_index if item.course_index is not None else item.sort_order
    if numeric_order is None:
        numeric_order = float("inf")
    return (collection, has_index, numeric_order, -_created_at_timestamp(item.created_at))


def _created_at_timestamp(value: str) -> float:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0
