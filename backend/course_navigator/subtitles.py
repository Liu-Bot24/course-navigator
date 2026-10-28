from __future__ import annotations

import re

from .models import TranscriptSegment

TIMING_RE = re.compile(
    r"(?P<start>(?:\d{1,2}:)?\d{2}:\d{2}[\.,]\d{1,3})\s+-->\s+"
    r"(?P<end>(?:\d{1,2}:)?\d{2}:\d{2}[\.,]\d{1,3})"
)
ROLLUP_OVERLAP_WORDS = 60


def parse_subtitle_text(raw: str, subtitle_format: str) -> list[TranscriptSegment]:
    normalized_format = subtitle_format.lower().lstrip(".")
    if normalized_format not in {"vtt", "srt"}:
        raise ValueError(f"Unsupported subtitle format: {subtitle_format}")

    segments: list[TranscriptSegment] = []
    lines = raw.replace("\ufeff", "").splitlines()
    index = 0

    while index < len(lines):
        line = lines[index].strip()
        match = TIMING_RE.search(line)
        if not match:
            index += 1
            continue

        start = _timestamp_to_seconds(match.group("start"))
        end = _timestamp_to_seconds(match.group("end"))
        text_lines: list[str] = []
        index += 1

        while index < len(lines) and lines[index].strip():
            candidate = lines[index].strip()
            # Files without blank lines between cues start the next cue here;
            # a number alone is cue text unless a timing line follows it.
            if TIMING_RE.search(candidate) or (
                candidate.isdigit() and index + 1 < len(lines) and TIMING_RE.search(lines[index + 1])
            ):
                break
            if not candidate.startswith(("NOTE", "STYLE")):
                text_lines.append(_clean_cue_text(candidate))
            index += 1

        text = " ".join(part for part in text_lines if part).strip()
        if text:
            segments.append(TranscriptSegment(start=start, end=end, text=text))

    return _dedupe_rollup_segments(segments)


def _timestamp_to_seconds(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    if len(parts) == 2:
        hours = 0
        minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    hours, minutes, seconds = parts
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _clean_cue_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _dedupe_rollup_segments(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    if not segments:
        return []

    collapsed: list[TranscriptSegment] = []
    for segment in sorted(segments, key=lambda item: (item.start, item.end, len(item.text))):
        if collapsed:
            previous = collapsed[-1]
            near_same_start = abs(segment.start - previous.start) <= 0.2
            if near_same_start and segment.text.startswith(previous.text):
                collapsed[-1] = segment
                continue
            if near_same_start and previous.text.startswith(segment.text):
                continue
        collapsed.append(segment)

    incremental: list[TranscriptSegment] = []
    recent_words: list[str] = []
    previous_end: float | None = None

    for segment in collapsed:
        # Roll-up captions overlap or touch the cue they repeat; a phrase said
        # again in a cue that starts later, even by a few milliseconds, is new
        # speech and stays.
        adjacent = previous_end is not None and segment.start <= previous_end
        text = _remove_previous_overlap(recent_words, segment.text) if adjacent else segment.text
        if not text:
            continue
        incremental.append(TranscriptSegment(start=segment.start, end=segment.end, text=text))
        recent_words = [*recent_words, *text.split()][-ROLLUP_OVERLAP_WORDS:] if adjacent else text.split()[-ROLLUP_OVERLAP_WORDS:]
        previous_end = max(segment.end, previous_end or segment.end)

    return incremental


def _remove_previous_overlap(previous_words: list[str], current: str) -> str:
    if not previous_words:
        return current
    current_words = current.split()
    max_overlap = min(len(previous_words), len(current_words))

    for size in range(max_overlap, 2, -1):
        if previous_words[-size:] == current_words[:size]:
            return " ".join(current_words[size:]).strip()

    return current
