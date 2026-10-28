"""Language tags carried by subtitle tracks and persisted transcripts."""
import re


def transcript_language_tag(value: str | None) -> str | None:
    tag = (value or "").strip().replace("_", "-")
    # Bilibili's ai-* prefix identifies the track type, not its language.
    if tag.lower().startswith("ai-"):
        tag = tag[3:]
    if tag.lower() in {"auto", "und", "mul", "zxx"}:
        return None
    return tag if re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", tag) else None


def language_family(value: str | None) -> str:
    tag = transcript_language_tag(value)
    if not tag:
        return ""
    base = tag.lower().split("-", 1)[0]
    return {"zho": "zh", "eng": "en", "jp": "ja", "jpn": "ja"}.get(base, base)
