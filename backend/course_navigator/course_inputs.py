"""Input contracts shared by generation, cache validation and guarded writes."""
from __future__ import annotations

import hashlib
import json

from .models import CourseItem, TranscriptSegment, VideoMetadata


def study_input_fingerprint(title: str, transcript: list[TranscriptSegment], source_language: str | None = None,
                            metadata: VideoMetadata | None = None) -> str:
    payload = {"title": title, "transcript": [segment.model_dump() for segment in transcript],
               "source_language": source_language,
               "metadata": metadata.model_dump(exclude={"stream_url", "hls_manifest_url"}) if metadata else None}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def study_input(item: CourseItem) -> str:
    return study_input_fingerprint(item.title, item.transcript, item.transcript_language, item.metadata)


def media_input(item: CourseItem) -> tuple:
    """A file operation depends on the source binding, not the lesson text."""
    return (item.source_url, item.media_revision, item.video_source_type,
            str(item.local_video_path) if item.local_video_path else None)


def transcript_input(item: CourseItem) -> tuple:
    return (item.transcript_language, item.transcript_source,
            tuple((segment.start, segment.end, segment.text) for segment in item.transcript))


def remote_extraction_input(item: CourseItem) -> str:
    # Hashing keeps pre-metadata snapshots of unresolved aliases small. Caching
    # this same URL does not change the remote extraction's actual input.
    payload = (item.source_url, item.media_revision, transcript_input(item))
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def local_extraction_input(item: CourseItem) -> tuple:
    return media_input(item), transcript_input(item)
