from __future__ import annotations

import math
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from .config import OnlineAsrServiceConfig, OnlineAsrSettings
from .models import ExtractRequest, OnlineAsrProvider, TranscriptSegment
from .subtitles import parse_subtitle_text
from .ytdlp import YtDlpError, build_auth_args


DEFAULT_CHUNK_LIMIT_BYTES = 20 * 1024 * 1024
TARGET_AUDIO_BITRATE = "64k"
CHUNK_OVERLAP_SECONDS = 5


def extract_online_asr_transcript(
    request: ExtractRequest,
    target_dir: Path,
    item_id: str,
    yt_dlp_binary: str,
    settings: OnlineAsrSettings,
    progress: Callable[[int, str], None] | None = None,
) -> list[TranscriptSegment]:
    if settings.provider == "none":
        raise YtDlpError("请先选择在线 ASR 服务，或把字幕来源改为原字幕优先/本地 ASR。")
    service = settings.service_for(settings.provider)
    if not service.api_key:
        raise YtDlpError("在线 ASR 需要先在模型配置中填写 API Key")
    if settings.provider == "custom" and not (service.base_url and service.model):
        raise YtDlpError("自定义在线 ASR 需要填写接口地址和模型名称")

    target_dir.mkdir(parents=True, exist_ok=True)
    _report(progress, 5, "正在为在线 ASR 抽取音频")
    source_audio = _extract_audio(request, target_dir, item_id, yt_dlp_binary)
    _report(progress, 28, "音频已抽取，正在压缩为在线 ASR 音频")
    compressed_audio = _compress_audio(source_audio, target_dir / f"{item_id}.online-asr.mp3")
    _report(progress, 38, "正在检查在线 ASR 音频分块")
    chunks = _audio_chunks(compressed_audio, item_id, target_dir, DEFAULT_CHUNK_LIMIT_BYTES)
    segments: list[TranscriptSegment] = []
    total = max(len(chunks), 1)
    for index, (chunk_path, offset) in enumerate(chunks, start=1):
        _report(progress, _scaled_progress(42, 88, index - 1, total), f"正在请求在线 ASR 第 {index}/{total} 段")
        payload = _transcribe_chunk(settings.provider, service, chunk_path, request.language)
        segments.extend(_segments_from_payload(payload, offset=offset))
        _report(progress, _scaled_progress(42, 88, index, total), f"已完成在线 ASR 第 {index}/{total} 段")
    _report(progress, 94, "在线 ASR 已返回，正在合并字幕")
    return _merge_segments(segments)


def _extract_audio(request: ExtractRequest, target_dir: Path, item_id: str, yt_dlp_binary: str) -> Path:
    output_template = str(target_dir / f"{item_id}.online-source.%(ext)s")
    cmd = [
        yt_dlp_binary,
        "--extract-audio",
        "--audio-format",
        "wav",
        "--output",
        output_template,
        *build_auth_args(request),
        str(request.url),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise YtDlpError(result.stderr.strip() or "yt-dlp audio extraction failed")
    candidates = sorted(target_dir.glob(f"{item_id}.online-source.*"), key=lambda path: path.stat().st_mtime)
    if not candidates:
        raise YtDlpError("yt-dlp did not produce an audio file for online ASR")
    return candidates[-1]


def _compress_audio(source: Path, target: Path) -> Path:
    if not shutil.which("ffmpeg"):
        raise YtDlpError("在线 ASR 需要 ffmpeg 来抽取并压缩音频")
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-b:a",
        TARGET_AUDIO_BITRATE,
        str(target),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0 or not target.exists():
        raise YtDlpError(result.stderr.strip() or "ffmpeg failed to compress audio for online ASR")
    return target


def _audio_chunks(audio_path: Path, item_id: str, target_dir: Path, limit_bytes: int) -> list[tuple[Path, float]]:
    if audio_path.stat().st_size <= limit_bytes:
        return [(audio_path, 0.0)]
    duration = _audio_duration(audio_path)
    if duration <= 0:
        raise YtDlpError("无法读取音频时长，不能为在线 ASR 分块")
    chunk_count = min(24, max(2, math.ceil(audio_path.stat().st_size / limit_bytes)))
    chunk_length = duration / chunk_count
    chunks: list[tuple[Path, float]] = []
    for index in range(chunk_count):
        start = max(0.0, index * chunk_length - (CHUNK_OVERLAP_SECONDS if index else 0))
        end = min(duration, (index + 1) * chunk_length + (CHUNK_OVERLAP_SECONDS if index < chunk_count - 1 else 0))
        if end <= start:
            continue
        chunk_path = target_dir / f"{item_id}.online-asr.part-{index + 1:03d}.mp3"
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            f"{start:.3f}",
            "-i",
            str(audio_path),
            "-t",
            f"{end - start:.3f}",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            TARGET_AUDIO_BITRATE,
            str(chunk_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0 or not chunk_path.exists():
            raise YtDlpError(result.stderr.strip() or "ffmpeg failed to split audio for online ASR")
        chunks.append((chunk_path, start))
    return chunks


def _audio_duration(audio_path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return 0.0
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def _transcribe_chunk(
    provider: OnlineAsrProvider,
    service: OnlineAsrServiceConfig,
    audio_path: Path,
    language: str,
) -> object:
    base_url = (service.base_url or _default_base_url(provider)).rstrip("/")
    endpoint = _transcription_endpoint(provider, base_url)
    with audio_path.open("rb") as audio_file:
        files = {"file": (audio_path.name, audio_file, "audio/mpeg")}
        data: dict[str, str] = {}
        if provider != "xai":
            data["model"] = service.model or _default_model(provider)
        if provider in {"openai", "groq", "custom"}:
            data["response_format"] = "verbose_json"
            data["timestamp_granularities[]"] = "segment"
        normalized_language = _normalize_asr_language(language) if language and language != "auto" else ""
        if provider == "xai":
            xai_language = _xai_format_language(normalized_language)
            if xai_language:
                data["language"] = xai_language
                data["format"] = "true"
        elif normalized_language:
            data["language"] = normalized_language
        try:
            response = httpx.post(
                endpoint,
                headers={"Authorization": f"Bearer {service.api_key}"},
                data=data,
                files=files,
                timeout=300,
            )
        except httpx.TimeoutException as exc:
            raise YtDlpError(f"{_provider_label(provider)} 在线 ASR 请求超时，请稍后重试或换用更短的视频。") from exc
        except httpx.RequestError as exc:
            raise YtDlpError(f"{_provider_label(provider)} 在线 ASR 请求失败：{exc}") from exc
    if response.status_code >= 400:
        raise YtDlpError(
            f"{_provider_label(provider)} 在线 ASR 请求失败（HTTP {response.status_code}）：{_response_error_detail(response)}"
        )
    content_type = response.headers.get("content-type", "")
    if "json" in content_type:
        return response.json()
    return response.text


def _transcription_endpoint(provider: OnlineAsrProvider, base_url: str) -> str:
    if provider == "xai":
        return f"{base_url}/stt"
    if base_url.endswith("/audio/transcriptions"):
        return base_url
    return f"{base_url}/audio/transcriptions"


def _default_base_url(provider: OnlineAsrProvider) -> str:
    return {
        "none": "",
        "openai": "https://api.openai.com/v1",
        "groq": "https://api.groq.com/openai/v1",
        "xai": "https://api.x.ai/v1",
        "custom": "",
    }[provider]


def _default_model(provider: OnlineAsrProvider) -> str:
    return {
        "none": "",
        "openai": "whisper-1",
        "groq": "whisper-large-v3-turbo",
        "xai": "grok-2-voice-1212",
        "custom": "",
    }[provider]


def _provider_label(provider: OnlineAsrProvider) -> str:
    return {
        "none": "在线 ASR",
        "openai": "OpenAI",
        "groq": "Groq",
        "xai": "xAI",
        "custom": "自定义",
    }[provider]


def _response_error_detail(response: httpx.Response) -> str:
    content_type = response.headers.get("content-type", "")
    if "json" in content_type:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        detail = _json_error_message(payload)
        if detail:
            return detail
    text = response.text.strip()
    return text[:500] if text else "接口没有返回错误详情"


def _json_error_message(payload: object) -> str:
    if isinstance(payload, dict):
        for key in ("message", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        error = payload.get("error")
        if isinstance(error, str) and error.strip():
            return error.strip()
        if isinstance(error, dict):
            return _json_error_message(error)
    return ""


def _normalize_asr_language(language: str) -> str:
    normalized = language.strip()
    return {
        "zh-CN": "zh",
        "zh-Hans": "zh",
        "zh-Hant": "zh",
        "zh-cn": "zh",
        "zh-hans": "zh",
        "zh-hant": "zh",
    }.get(normalized, normalized.split("-")[0].lower())


def _xai_format_language(language: str) -> str | None:
    supported = {
        "en",
        "fr",
        "de",
        "it",
        "pt",
        "pl",
        "tr",
        "ru",
        "nl",
        "cs",
        "ar",
        "es",
        "ja",
        "ko",
        "hi",
        "th",
        "vi",
    }
    return language if language in supported else None


def _segments_from_payload(payload: object, *, offset: float) -> list[TranscriptSegment]:
    if isinstance(payload, str):
        text = payload.strip()
        if "-->" in text:
            subtitle_format = "vtt" if text.upper().startswith("WEBVTT") else "srt"
            return _offset_segments(parse_subtitle_text(text, subtitle_format), offset)
        raise YtDlpError("在线 ASR 接口只返回了纯文本，没有可用于字幕的时间戳")
    if not isinstance(payload, dict):
        raise YtDlpError("在线 ASR 返回格式无法识别")
    segments = _segments_from_segment_payload(payload)
    if segments:
        return _offset_segments(segments, offset)
    words = _word_items(payload)
    if words:
        return _offset_segments(_segments_from_words(words), offset)
    text = str(payload.get("text") or "").strip()
    if text and "-->" in text:
        return _offset_segments(parse_subtitle_text(text, "vtt" if text.upper().startswith("WEBVTT") else "srt"), offset)
    raise YtDlpError("在线 ASR 返回结果没有 segment 或 word 时间戳，无法生成字幕")


def _segments_from_segment_payload(payload: dict[str, Any]) -> list[TranscriptSegment]:
    raw_segments = payload.get("segments") or payload.get("results") or payload.get("chunks")
    if not isinstance(raw_segments, list):
        return []
    segments: list[TranscriptSegment] = []
    for item in raw_segments:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or item.get("transcript") or "").strip()
        start = _float_value(item.get("start"))
        end = _float_value(item.get("end"))
        if text and start is not None and end is not None and end > start:
            segments.append(TranscriptSegment(start=start, end=end, text=text))
    return segments


def _word_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("words", "word_timestamps"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    result = payload.get("result")
    if isinstance(result, dict):
        value = result.get("words")
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _segments_from_words(words: list[dict[str, Any]]) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    current_words: list[str] = []
    current_start: float | None = None
    current_end: float | None = None
    for word in words:
        text = str(word.get("word") or word.get("text") or "").strip()
        start = _first_float(word, "start", "start_time")
        end = _first_float(word, "end", "end_time")
        if not text or start is None or end is None or end <= start:
            continue
        if current_start is None:
            current_start = start
        should_flush = (
            current_words
            and (
                len("".join(current_words)) >= 32
                or (current_end is not None and start - current_end >= 0.8)
                or (current_end is not None and end - current_start >= 7.0)
            )
        )
        if should_flush and current_start is not None and current_end is not None:
            segments.append(TranscriptSegment(start=current_start, end=current_end, text=_join_words(current_words)))
            current_words = []
            current_start = start
        current_words.append(text)
        current_end = end
    if current_words and current_start is not None and current_end is not None:
        segments.append(TranscriptSegment(start=current_start, end=current_end, text=_join_words(current_words)))
    return segments


def _join_words(words: list[str]) -> str:
    if any(_contains_cjk(word) for word in words):
        return "".join(words)
    return " ".join(words)


def _contains_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def _offset_segments(segments: list[TranscriptSegment], offset: float) -> list[TranscriptSegment]:
    if offset <= 0:
        return segments
    return [
        TranscriptSegment(start=segment.start + offset, end=segment.end + offset, text=segment.text)
        for segment in segments
    ]


def _merge_segments(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    merged: list[TranscriptSegment] = []
    seen: set[tuple[int, str]] = set()
    for segment in sorted(segments, key=lambda item: (item.start, item.end)):
        key = (round(segment.start), segment.text.strip())
        if key in seen:
            continue
        seen.add(key)
        if merged and abs(segment.start - merged[-1].start) <= 0.5 and segment.text.strip() == merged[-1].text.strip():
            continue
        merged.append(segment)
    return merged


def _scaled_progress(start: int, end: int, index: int, total: int) -> int:
    if total <= 0:
        return end
    return start + round((max(0, min(index, total)) / total) * (end - start))


def _report(progress: Callable[[int, str], None] | None, value: int, message: str) -> None:
    if progress:
        progress(max(1, min(99, value)), message)


def _float_value(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_float(payload: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key in payload:
            value = _float_value(payload.get(key))
            if value is not None:
                return value
    return None
