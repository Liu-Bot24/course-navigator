"""Validate incoming source URLs without making old records unreadable."""
from urllib.parse import ParseResult, urlparse


def validate_source_url(value: str) -> str:
    value = value.strip()
    # A leading dash would be read by yt-dlp as an option, not as a source.
    if value.startswith("-"):
        raise ValueError("Source URL cannot start with '-'")
    parse_source_url(value)
    return value


def parse_source_url(value: str) -> ParseResult:
    parsed = urlparse(value)
    # Accessing .port validates both numeric syntax and its allowed range.
    # Keep yt-dlp's existing bare IDs, schemeless URLs and extractor prefixes;
    # the downloader remains responsible for deciding whether it supports them.
    parsed.port
    return parsed


def try_parse_source_url(value: str) -> ParseResult | None:
    """Malformed legacy sources have no URL-derived display information."""
    try:
        return parse_source_url(value)
    except ValueError:
        return None
