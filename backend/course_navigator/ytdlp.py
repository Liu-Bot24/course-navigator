from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from .models import DownloadRequest, ExtractRequest, TranscriptSegment, VideoMetadata
from .subtitles import parse_subtitle_text


class YtDlpError(RuntimeError):
    pass


NON_AUXILIARY_SUBTITLE_SELECTOR = "all,-danmaku,-live_chat,-comments,-rechat"
DEFAULT_SUBTITLE_LANGUAGE_PRIORITY = (
    "zh-Hans",
    "zh-CN",
    "ai-zh",
    "zh",
    "zh-Hant",
    "zh-TW",
    "en",
    "ja",
)


def build_auth_args(request: ExtractRequest | DownloadRequest) -> list[str]:
    if request.mode == "normal":
        return []
    if request.mode == "browser":
        browser = (request.browser or "chrome").strip() or "chrome"
        return ["--cookies-from-browser", browser]
    if request.mode == "cookies":
        if not request.cookies_path:
            raise ValueError("cookies_path is required when mode is cookies")
        return ["--cookies", str(Path(request.cookies_path).expanduser())]
    raise ValueError(f"Unsupported extraction mode: {request.mode}")


class YtDlpRunner:
    def __init__(self, binary: str = "yt-dlp") -> None:
        self.binary = binary

    def fetch_metadata(self, request: ExtractRequest) -> VideoMetadata:
        cmd = [
            self.binary,
            "--skip-download",
            "--dump-json",
            "--no-warnings",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs",
            "all",
            "--sub-format",
            "vtt/srt/best",
            *build_auth_args(request),
            str(request.url),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise YtDlpError(_friendly_error(result.stderr.strip(), request, "yt-dlp metadata extraction failed"))

        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise YtDlpError("yt-dlp returned invalid JSON") from exc

        return VideoMetadata(
            id=str(payload.get("id") or "unknown"),
            title=str(payload.get("title") or "Untitled"),
            duration=payload.get("duration"),
            uploader=_safe_str(payload.get("uploader")),
            channel=_safe_str(payload.get("channel")),
            creator=_safe_str(payload.get("creator")),
            description=_safe_str(payload.get("description")),
            playlist_title=_safe_str(payload.get("playlist_title") or payload.get("playlist")),
            playlist_index=_safe_int(payload.get("playlist_index")),
            webpage_url=str(payload.get("webpage_url") or request.url),
            extractor=str(payload.get("extractor") or "unknown"),
            stream_url=_extract_stream_url(payload),
            hls_manifest_url=_extract_hls_manifest_url(payload),
            language=payload.get("language") or payload.get("original_language"),
            subtitles=sorted((payload.get("subtitles") or {}).keys()),
            automatic_captions=sorted((payload.get("automatic_captions") or {}).keys()),
        )

    def extract_subtitles(
        self,
        request: ExtractRequest,
        target_dir: Path,
        metadata: VideoMetadata | None = None,
    ) -> list[TranscriptSegment]:
        target_dir.mkdir(parents=True, exist_ok=True)
        _clear_subtitle_files(target_dir)
        output_template = str(target_dir / "%(id)s.%(ext)s")
        subtitle_language = choose_source_subtitle_language(metadata, request.language)
        cmd = [
            self.binary,
            "--skip-download",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs",
            subtitle_language,
            "--sub-format",
            "vtt/srt/best",
            "--convert-subs",
            "vtt",
            "--output",
            output_template,
            *build_auth_args(request),
            str(request.url),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise YtDlpError(_friendly_error(result.stderr.strip(), request, "yt-dlp subtitle extraction failed"))

        subtitle_file = _find_newest_subtitle(target_dir)
        if not subtitle_file:
            fallback_segments = _extract_hls_manifest_subtitles(metadata, subtitle_language, target_dir)
            if fallback_segments:
                return fallback_segments
        if not subtitle_file:
            raise YtDlpError("yt-dlp did not produce a subtitle file")

        return parse_subtitle_text(
            subtitle_file.read_text(encoding="utf-8", errors="replace"),
            subtitle_file.suffix.lstrip("."),
        )

    def download_video(
        self,
        request: DownloadRequest,
        target_dir: Path,
        item_id: str,
        progress: Callable[[int, str], None] | None = None,
    ) -> Path:
        target_dir.mkdir(parents=True, exist_ok=True)
        output_template = str(target_dir / f"{item_id}.%(ext)s")
        cmd = [
            self.binary,
            "--newline",
            "--format",
            "bv*+ba/b",
            "--merge-output-format",
            "mp4",
            "--output",
            output_template,
            *build_auth_args(request),
            str(request.url),
        ]
        if progress:
            progress(1, "正在准备缓存视频")
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        output_lines: list[str] = []
        if process.stdout:
            for line in process.stdout:
                output_lines.append(line)
                percent = _download_percent(line)
                if percent is not None and progress:
                    progress(max(1, min(95, percent)), "正在缓存视频")
        returncode = process.wait()
        output = "".join(output_lines).strip()
        if returncode != 0:
            raise YtDlpError(_friendly_error(output, request, "yt-dlp video download failed"))
        if progress:
            progress(98, "正在整理缓存文件")
        candidates = list(target_dir.glob(f"{item_id}.*"))
        if not candidates:
            raise YtDlpError("yt-dlp did not produce a video file")
        return max(candidates, key=lambda path: path.stat().st_mtime)

    def extract_asr(self, request: ExtractRequest, target_dir: Path, item_id: str) -> list[TranscriptSegment]:
        target_dir.mkdir(parents=True, exist_ok=True)
        audio_template = str(target_dir / f"{item_id}.%(ext)s")
        audio_cmd = [
            self.binary,
            "--extract-audio",
            "--audio-format",
            "wav",
            "--output",
            audio_template,
            *build_auth_args(request),
            str(request.url),
        ]
        audio_result = subprocess.run(audio_cmd, capture_output=True, text=True, check=False)
        if audio_result.returncode != 0:
            raise YtDlpError(_friendly_error(audio_result.stderr.strip(), request, "yt-dlp audio extraction failed"))

        audio_file = _find_newest_audio(target_dir, item_id)
        if not audio_file:
            raise YtDlpError("yt-dlp did not produce an audio file for ASR")

        whisper_binary = "whisper"
        resolved_whisper = shutil.which(whisper_binary)
        if not resolved_whisper:
            raise YtDlpError("Local ASR requires the whisper command, but it was not found in PATH")

        asr_cmd = [
            resolved_whisper,
            str(audio_file),
            "--model",
            "base",
            "--output_format",
            "vtt",
            "--output_dir",
            str(target_dir),
        ]
        if request.language and request.language != "auto":
            asr_cmd.extend(["--language", request.language])
        asr_result = subprocess.run(asr_cmd, capture_output=True, text=True, check=False)
        if asr_result.returncode != 0:
            raise YtDlpError(asr_result.stderr.strip() or "Local ASR failed")

        subtitle_file = _find_newest_subtitle(target_dir)
        if not subtitle_file:
            raise YtDlpError("Local ASR did not produce a subtitle file")
        return parse_subtitle_text(
            subtitle_file.read_text(encoding="utf-8", errors="replace"),
            subtitle_file.suffix.lstrip("."),
        )


def choose_source_subtitle_language(metadata: VideoMetadata | None, requested: str = "auto") -> str:
    if requested and requested != "auto":
        return requested
    if not metadata:
        return "en"

    subtitles = [language for language in metadata.subtitles if not _is_auxiliary_subtitle_language(language)]
    automatic_captions = [
        language for language in metadata.automatic_captions if not _is_auxiliary_subtitle_language(language)
    ]
    available = [*subtitles, *automatic_captions]
    source_language = (metadata.language or "").strip()
    if source_language:
        match = _match_available_language(source_language, available)
        if match:
            return match

    if _metadata_looks_chinese(metadata):
        match = _best_preferred_language(available, ("ai-zh", "zh-Hans", "zh-CN", "zh", "zh-Hant", "zh-TW"))
        if match:
            return match

    if subtitles:
        return _best_preferred_language(subtitles, DEFAULT_SUBTITLE_LANGUAGE_PRIORITY) or subtitles[0]
    if automatic_captions:
        return _best_preferred_language(automatic_captions, DEFAULT_SUBTITLE_LANGUAGE_PRIORITY) or automatic_captions[0]
    if metadata.subtitles:
        return NON_AUXILIARY_SUBTITLE_SELECTOR
    if metadata.automatic_captions:
        return NON_AUXILIARY_SUBTITLE_SELECTOR
    return source_language or "en"


def is_subtitle_unavailable_error(error: Exception) -> bool:
    message = str(error).lower()
    return (
        "did not produce a subtitle file" in message
        or "there are no subtitles" in message
        or "no subtitles" in message
        or "no automatic captions" in message
    )


def _extract_stream_url(payload: dict) -> str | None:
    value = payload.get("url")
    has_split_requested_formats = isinstance(payload.get("requested_formats"), list)
    if (
        isinstance(value, str)
        and value.startswith(("http://", "https://"))
        and not has_split_requested_formats
        and not _is_video_only_format(payload)
    ):
        return value
    formats = payload.get("formats")
    if isinstance(formats, list):
        for item in reversed(formats):
            if not isinstance(item, dict):
                continue
            candidate = item.get("url")
            if (
                isinstance(candidate, str)
                and candidate.startswith(("http://", "https://"))
                and _has_audio_and_video(item)
            ):
                return candidate
    return None


def _download_percent(line: str) -> int | None:
    match = re.search(r"(?P<percent>\d+(?:\.\d+)?)%", line)
    if not match:
        return None
    try:
        return int(float(match.group("percent")))
    except ValueError:
        return None


def _is_auxiliary_subtitle_language(language: str) -> bool:
    normalized = language.strip().lower()
    return normalized in {"danmaku", "live_chat", "comments", "rechat"}


def _metadata_looks_chinese(metadata: VideoMetadata) -> bool:
    if (metadata.extractor or "").lower().startswith("bili"):
        return True
    fields = (
        metadata.title,
        metadata.uploader or "",
        metadata.channel or "",
        metadata.creator or "",
    )
    return any(re.search(r"[\u4e00-\u9fff]", field) for field in fields)


def _best_preferred_language(available: list[str], priority: tuple[str, ...]) -> str | None:
    if not available:
        return None
    lowered = {language.lower(): language for language in available}
    for preferred in priority:
        exact = lowered.get(preferred.lower())
        if exact:
            return exact
    for preferred in priority:
        preferred_base = preferred.split("-", 1)[0].lower()
        for candidate in available:
            normalized = candidate.lower()
            if normalized == f"ai-{preferred_base}" or normalized.split("-", 1)[0] == preferred_base:
                return candidate
    return None


def _clear_subtitle_files(target_dir: Path) -> None:
    if not target_dir.exists():
        return
    for path in target_dir.iterdir():
        if path.is_file() and path.suffix.lower() in {".vtt", ".srt"}:
            path.unlink()


def _has_audio_and_video(format_payload: dict) -> bool:
    vcodec = str(format_payload.get("vcodec") or "")
    acodec = str(format_payload.get("acodec") or "")
    return vcodec not in {"", "none"} and acodec not in {"", "none"}


def _is_video_only_format(format_payload: dict) -> bool:
    vcodec = str(format_payload.get("vcodec") or "")
    acodec = str(format_payload.get("acodec") or "")
    return vcodec not in {"", "none"} and acodec == "none"


def _safe_int(value: object) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _extract_hls_manifest_url(payload: dict) -> str | None:
    formats = payload.get("formats")
    if isinstance(formats, list):
        for item in formats:
            if not isinstance(item, dict):
                continue
            candidate = item.get("manifest_url")
            if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                return candidate
    value = payload.get("manifest_url")
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return value
    return None


def _extract_hls_manifest_subtitles(
    metadata: VideoMetadata | None,
    requested_language: str,
    target_dir: Path,
) -> list[TranscriptSegment]:
    if not metadata:
        return []
    manifest_url = metadata.hls_manifest_url or metadata.stream_url
    if not manifest_url or ".m3u8" not in manifest_url:
        return []
    try:
        manifest = _download_text(manifest_url)
        subtitle_uri = _choose_hls_subtitle_uri(manifest, manifest_url, requested_language)
        if not subtitle_uri:
            return []
        subtitle_manifest_or_vtt = _download_text(subtitle_uri)
        raw_vtt = (
            subtitle_manifest_or_vtt
            if subtitle_manifest_or_vtt.lstrip().startswith("WEBVTT")
            else _download_hls_subtitle_segments(subtitle_manifest_or_vtt, subtitle_uri)
        )
        if not raw_vtt.strip():
            return []
    except Exception:
        return []

    language = requested_language.replace("*", "auto") or "auto"
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", metadata.id).strip("_") or "subtitle"
    target_file = target_dir / f"{safe_id}.{language}.hls.vtt"
    target_file.write_text(raw_vtt, encoding="utf-8")
    return parse_subtitle_text(raw_vtt, "vtt")


def _choose_hls_subtitle_uri(manifest: str, manifest_url: str, requested_language: str) -> str | None:
    subtitle_tracks: list[dict[str, str]] = []
    for line in manifest.splitlines():
        if not line.startswith("#EXT-X-MEDIA:"):
            continue
        attrs = _parse_hls_attrs(line.split(":", 1)[1])
        if attrs.get("TYPE", "").upper() != "SUBTITLES":
            continue
        uri = attrs.get("URI")
        if not uri:
            continue
        subtitle_tracks.append(attrs | {"URI": urljoin(manifest_url, uri)})

    if not subtitle_tracks:
        return None

    requested_base = requested_language.split(",", 1)[0].split("-", 1)[0].lower()
    if requested_base and requested_base not in {"auto", "*"}:
        for track in subtitle_tracks:
            language = (track.get("LANGUAGE") or track.get("NAME") or "").lower()
            if language == requested_language.lower() or language.split("-", 1)[0] == requested_base:
                return track["URI"]
    return subtitle_tracks[0]["URI"]


def _download_hls_subtitle_segments(playlist: str, playlist_url: str) -> str:
    chunks: list[str] = []
    for line in playlist.splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        chunks.append(_download_text(urljoin(playlist_url, value)))
    return "\n\n".join(chunks)


def _parse_hls_attrs(value: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in re.finditer(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)', value):
        raw = match.group(2).strip()
        attrs[match.group(1)] = raw[1:-1] if raw.startswith('"') and raw.endswith('"') else raw
    return attrs


def _download_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "CourseNavigator/0.1 yt-dlp-fallback"})
    with urlopen(request, timeout=15) as response:
        return response.read().decode("utf-8", errors="replace")


def _match_available_language(language: str, available: list[str]) -> str | None:
    if language in available:
        return language
    language_base = language.split("-", 1)[0]
    for candidate in available:
        candidate_base = candidate.split("-", 1)[0]
        if candidate_base == language_base:
            return candidate
    return None


def _find_newest_subtitle(target_dir: Path) -> Path | None:
    if not target_dir.exists():
        return None
    candidates = [
        path
        for path in target_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".vtt", ".srt"}
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _find_newest_audio(target_dir: Path, item_id: str) -> Path | None:
    if not target_dir.exists():
        return None
    candidates = [
        path
        for path in target_dir.glob(f"{item_id}.*")
        if path.is_file() and path.suffix.lower() in {".wav", ".m4a", ".mp3", ".aac", ".opus", ".webm"}
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _friendly_error(
    stderr: str,
    request: ExtractRequest | DownloadRequest,
    fallback: str,
) -> str:
    message = stderr or fallback
    if _looks_like_missing_ffmpeg(message):
        return (
            "缺少 ffmpeg，当前操作需要合并或转换媒体文件。"
            "请安装 ffmpeg 后重试；字幕提取、字幕浏览和 AI 校正仍可继续使用。"
            f"原始错误：{message}"
        )
    if "Sign in to confirm" not in message:
        return message
    if request.mode == "browser":
        browser = (request.browser or "chrome").strip() or "chrome"
        return (
            f"yt-dlp 已按浏览器 Cookie 来源 {browser} 调用，但 YouTube 仍要求登录验证。"
            "这通常表示该来源没有读到可用的 YouTube 登录态。请确认桌面浏览器已登录 YouTube；"
            "如果使用 Chrome 多用户配置，可以尝试 chrome:Default 或 chrome:Profile 1；"
            "也可以改用 Cookies 文件模式。"
            f"原始错误：{message}"
        )
    if request.mode == "cookies":
        return (
            "yt-dlp 已使用 --cookies，但 YouTube 仍要求登录验证。"
            "请确认 cookies.txt 来自已登录 YouTube 的浏览器且没有过期。"
            f"原始错误：{message}"
        )
    return (
        "YouTube 要求登录验证。请在 Course Navigator 中把提取登录改为浏览器 Cookie "
        f"或 Cookies 文件后重试。原始错误：{message}"
    )


def _looks_like_missing_ffmpeg(message: str) -> bool:
    normalized = message.lower()
    return "ffmpeg" in normalized and (
        "not found" in normalized
        or "not installed" in normalized
        or "please install" in normalized
        or "install ffmpeg" in normalized
        or "ffmpeg-location" in normalized
    )
