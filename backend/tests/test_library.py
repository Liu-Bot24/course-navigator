from course_navigator.library import CourseLibrary
from course_navigator.models import CourseItem, TranscriptSegment
from course_navigator.library import CourseConflict
import pytest


def test_library_saves_and_reads_course_item(tmp_path):
    library = CourseLibrary(tmp_path)
    item = CourseItem(
        id="lesson-1",
        source_url="https://example.com/video",
        title="Lesson 1",
        duration=30,
        created_at="2026-05-03T00:00:00Z",
        transcript=[TranscriptSegment(start=0, end=2, text="Hello")],
    )

    library.save(item)

    loaded = library.get("lesson-1")
    assert loaded == item


def test_library_save_uses_atomic_temp_replace(tmp_path, monkeypatch):
    library = CourseLibrary(tmp_path)
    item = CourseItem(
        id="lesson-1",
        source_url="https://example.com/video",
        title="Lesson 1",
        duration=30,
        created_at="2026-05-03T00:00:00Z",
        transcript=[TranscriptSegment(start=0, end=2, text="Hello")],
    )
    replaced_paths = []
    original_replace = type(tmp_path).replace

    def recording_replace(self, target):
        replaced_paths.append((self.name, target.name))
        return original_replace(self, target)

    monkeypatch.setattr(type(tmp_path), "replace", recording_replace)

    library.save(item)

    assert replaced_paths
    assert replaced_paths[0][0].startswith(".lesson-1.json.")
    assert replaced_paths[0][0].endswith(".tmp")
    assert replaced_paths[0][1] == "lesson-1.json"
    assert not list((tmp_path / "items").glob("*.tmp"))
    assert library.get("lesson-1") == item


def test_library_lists_items_sorted_newest_first(tmp_path):
    library = CourseLibrary(tmp_path)
    older = CourseItem(
        id="older",
        source_url="https://example.com/old",
        title="Older",
        created_at="2026-05-02T00:00:00Z",
    )
    newer = CourseItem(
        id="newer",
        source_url="https://example.com/new",
        title="Newer",
        created_at="2026-05-03T00:00:00Z",
    )

    library.save(older)
    library.save(newer)

    assert [item.id for item in library.list_items()] == ["newer", "older"]


def test_library_rejects_path_traversal_ids(tmp_path):
    library = CourseLibrary(tmp_path)

    assert library.get("../secret") is None


def test_atomic_updates_merge_unrelated_fields_and_reject_overlapping_edits(tmp_path):
    library = CourseLibrary(tmp_path)
    original = CourseItem(id="course", title="Original", source_url="https://example.com",
                          created_at="2026-09-09T00:00:00Z")
    library.create(original)
    first = library.get(original.id)
    second = library.get(original.id)
    library.update(first, {"title": "New title"})
    merged = library.update(second, {"collection_group_title": "My group"})
    assert merged.title == "New title"
    assert merged.collection_group_title == "My group"
    with pytest.raises(CourseConflict):
        library.update(second, {"title": "Stale title"})
    assert library.get(original.id).title == "New title"


def test_old_instance_cannot_update_reimported_course(tmp_path):
    library = CourseLibrary(tmp_path)
    old = CourseItem(id="course", title="Original", source_url="https://example.com",
                     created_at="2026-09-09T00:00:00Z")
    library.create(old)
    library.delete(old.id)
    with pytest.raises(CourseConflict):
        library.update(old, {"title": "Revived"})
    new = old.model_copy(update={"instance_id": "a" * 32, "title": "Reimported"})
    library.create(new)
    with pytest.raises(CourseConflict):
        library.update(old, {"title": "Revived"})
    assert library.get(old.id).title == "Reimported"


def _cached_course(item_id="cached-1"):
    return CourseItem(id=item_id, source_url="https://example.com/v", title="Cached", created_at="2026-05-03T00:00:00Z",
                      transcript=[TranscriptSegment(start=0, end=2, text="Hello")])


def test_cached_reads_skip_the_file_but_return_independent_items(tmp_path, monkeypatch):
    library = CourseLibrary(tmp_path)
    library.save(_cached_course())
    first = library.get("cached-1")
    reads = []
    original = library._read_payload
    monkeypatch.setattr(library, "_read_payload", lambda path: reads.append(path) or original(path))

    first.transcript[0].text = "mutated by a caller"
    second = library.get("cached-1")
    library.list_items()

    assert reads == []
    assert second.transcript[0].text == "Hello"
    assert second is not first


def test_cache_follows_writes_and_changes_made_outside_the_app(tmp_path):
    library = CourseLibrary(tmp_path)
    library.save(_cached_course())
    library.get("cached-1")

    library.update(library.get("cached-1"), {"title": "Renamed"})
    assert library.get("cached-1").title == "Renamed"

    path = tmp_path / "items" / "cached-1.json"
    path.write_text(path.read_text(encoding="utf-8").replace("Renamed", "Edited by hand, longer"), encoding="utf-8")
    assert library.get("cached-1").title == "Edited by hand, longer"

    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        library.get("cached-1")
    assert [item.id for item in library.list_items()] == []
    assert "cached-1.json" in library.read_errors

    path.unlink()
    assert library.get("cached-1") is None
    assert library.list_items() == []
