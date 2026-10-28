from course_navigator.subtitles import parse_subtitle_text


def test_parse_webvtt_segments_with_cue_text():
    raw = """WEBVTT

00:00:01.000 --> 00:00:03.500
Hello there.

00:00:04.000 --> 00:00:06.250
This is a course.
"""

    segments = parse_subtitle_text(raw, "vtt")

    assert [segment.model_dump() for segment in segments] == [
        {"start": 1.0, "end": 3.5, "text": "Hello there."},
        {"start": 4.0, "end": 6.25, "text": "This is a course."},
    ]


def test_parse_webvtt_segments_without_hour_component():
    raw = """WEBVTT

00:00.860 --> 00:01.260
Hello

00:01.260 --> 00:01.700
大家好
"""

    segments = parse_subtitle_text(raw, "vtt")

    assert [segment.model_dump() for segment in segments] == [
        {"start": 0.86, "end": 1.26, "text": "Hello"},
        {"start": 1.26, "end": 1.7, "text": "大家好"},
    ]


def test_parse_srt_segments_with_sequence_numbers_and_multiline_text():
    raw = """1
00:00:10,000 --> 00:00:12,500
First line
second line

2
00:01:00,000 --> 00:01:05,000
Another cue
"""

    segments = parse_subtitle_text(raw, "srt")

    assert [segment.model_dump() for segment in segments] == [
        {"start": 10.0, "end": 12.5, "text": "First line second line"},
        {"start": 60.0, "end": 65.0, "text": "Another cue"},
    ]


def test_parse_subtitle_text_rejects_unknown_format():
    try:
        parse_subtitle_text("hello", "txt")
    except ValueError as exc:
        assert "Unsupported subtitle format" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_parse_webvtt_rollup_captions_keep_incremental_text():
    raw = """WEBVTT

00:00:07.390 --> 00:00:07.400
Welcome to AI for everyone. AI is

00:00:07.390 --> 00:00:10.429
Welcome to AI for everyone. AI is changing the way we work and live, and

00:00:10.419 --> 00:00:10.429
changing the way we work and live, and

00:00:10.419 --> 00:00:12.780
changing the way we work and live, and this non-technical course will teach you
"""

    segments = parse_subtitle_text(raw, "vtt")

    assert [segment.text for segment in segments] == [
        "Welcome to AI for everyone. AI is changing the way we work and live, and",
        "this non-technical course will teach you",
    ]


def test_parse_srt_keeps_numeric_text_and_cues_without_blank_lines():
    raw = """1
00:00:01,000 --> 00:00:02,000
2024
2
00:00:02,000 --> 00:00:03,000
was a good year
00:00:03,000 --> 00:00:04,000
42
"""

    segments = parse_subtitle_text(raw, "srt")

    assert [segment.model_dump() for segment in segments] == [
        {"start": 1.0, "end": 2.0, "text": "2024"},
        {"start": 2.0, "end": 3.0, "text": "was a good year"},
        {"start": 3.0, "end": 4.0, "text": "42"},
    ]


def test_parse_subtitles_keeps_a_phrase_repeated_after_a_pause():
    raw = """WEBVTT

00:00:01.000 --> 00:00:02.000
thank you very much

00:00:30.000 --> 00:00:31.000
thank you very much
"""

    segments = parse_subtitle_text(raw, "vtt")

    assert [segment.text for segment in segments] == ["thank you very much", "thank you very much"]

def test_parse_srt_keeps_a_phrase_repeated_in_the_next_cue():
    raw = """1
00:00:00,000 --> 00:00:01,000
Thank you very much.

2
00:00:02,000 --> 00:00:03,000
Thank you very much.
"""

    segments = parse_subtitle_text(raw, "srt")

    assert [segment.text for segment in segments] == ["Thank you very much.", "Thank you very much."]


def test_parse_srt_dedupes_only_cues_that_overlap_the_previous_one():
    after_gap = """1
00:00:00,000 --> 00:00:01,000
Thank you very much.

2
00:00:01,040 --> 00:00:02,000
Thank you very much.
"""
    overlapping = after_gap.replace("00:00:01,040 -->", "00:00:00,990 -->")

    assert len(parse_subtitle_text(after_gap, "srt")) == 2
    assert [segment.text for segment in parse_subtitle_text(overlapping, "srt")] == ["Thank you very much."]