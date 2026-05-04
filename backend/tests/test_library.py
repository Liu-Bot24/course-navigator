from course_navigator.library import CourseLibrary
from course_navigator.models import CourseItem, TranscriptSegment


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
