from __future__ import annotations

import json
import asyncio
import logging
import os
import inspect
import ipaddress
import hashlib
import socket
from functools import wraps
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock, RLock
from urllib.parse import parse_qs, unquote
from uuid import uuid4
from weakref import WeakValueDictionary

import httpx
from fastapi import FastAPI, File as FormFile, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .ai import stamp_study_cache, study_cache_matches, LlmCancelled, _anthropic_endpoint_url, generate_study_material, regenerate_study_section, translate_transcript_material
from . import artifacts
from .asr import search_endpoint, suggest_asr_corrections
from .config import (
    AsrSearchServiceConfig,
    AsrSearchSettings,
    ModelProfileConfig,
    OnlineAsrServiceConfig,
    OnlineAsrSettings,
    Settings,
    default_env_path,
    default_web_dist_dir,
    load_settings,
)
from .cookies import normalize_cookie_text
from .library import CourseConflict, CourseLibrary
from .course_inputs import local_extraction_input, media_input, remote_extraction_input, study_input, transcript_input
from .jobs import KeyedExecutor
from .media_storage import prepared_video
from .source_operations import SourceOperations
from .source_urls import parse_source_url, try_parse_source_url, validate_source_url
from .languages import transcript_language_tag
from .llm_endpoints import llm_endpoint, llm_service_identity
from .models import (
    AsrCacheCleanupResponse,
    AsrCacheSettingsResponse,
    AsrCacheSettingsUpdate,
    CourseItem,
    CourseImportResponse,
    CourseItemUpdate,
    CourseSharePackage,
    CookieTextRequest,
    CookieTextResponse,
    AsrCorrectionRequest,
    AsrCorrectionResult,
    AsrCorrectionSearchConfig,
    AsrCorrectionSuggestion,
    AsrSearchProvider,
    AsrSearchServiceSettingsResponse,
    AsrSearchSettingsResponse,
    AsrSearchSettingsUpdate,
    DownloadRequest,
    DownloadResponse,
    ExtractRequest,
    LocalVideoFilePickerRequest,
    LocalVideoPathImportRequest,
    LibraryState,
    JobStatusValue,
    ModelListRequest,
    ModelListResponse,
    ModelSettingsResponse,
    ModelSettingsUpdate,
    ModelProfileResponse,
    OnlineAsrCustomSettingsResponse,
    OnlineAsrProvider,
    OnlineAsrServiceSettingsResponse,
    OnlineAsrSettingsResponse,
    OnlineAsrSettingsUpdate,
    StudyJobStatus,
    StudyDetailLevel,
    StudyMaterial,
    StudyRequest,
    TranscriptSegment,
    TranscriptUpdateRequest,
    VideoSourceBindingRequest,
)
from .online_asr import extract_online_asr_transcript, _transcription_endpoint
from .processes import run_hidden
from .ytdlp import YtDlpCancelled, YtDlpError, YtDlpRunner, choose_source_subtitle_language, is_subtitle_unavailable_error

logger = logging.getLogger("course_navigator.app")


class JobCancelled(Exception):
    """Raised inside job callbacks when the user cancels the current task."""


class StudyJobCancelled(JobCancelled):
    """Raised inside study generation callbacks when the user cancels the job."""


LOCAL_VIDEO_EXTENSIONS = {
    ".mp4",
    ".m4v",
    ".mov",
    ".webm",
    ".mkv",
    ".avi",
    ".wmv",
}
ASR_CACHE_AUTO_CLEANUP_THRESHOLD_BYTES = 500 * 1024 * 1024
ASR_CACHE_AUDIO_SUFFIXES = {".aac", ".flac", ".m4a", ".mp3", ".opus", ".wav", ".webm"}
MAX_ACTIVE_JOBS = 64
MAX_RETAINED_JOBS = 200
JOB_RETENTION_SECONDS = 3600
_DEFAULT_ENV_PATH = object()
_DEFAULT_WEB_DIST = object()


class _WebAssets(StaticFiles):
    """Built frontend pages served next to the API."""

    def file_response(self, full_path, stat_result, scope, status_code=200):
        response = super().file_response(full_path, stat_result, scope, status_code)
        # Asset names are content-hashed, but index.html must be revalidated so
        # an updated install never loads asset names that no longer exist.
        if str(full_path).endswith(".html"):
            response.headers["Cache-Control"] = "no-cache"
        return response


def _merge_partial_study(existing: StudyMaterial | None, partial: StudyMaterial) -> StudyMaterial:
    if not existing:
        return partial

    merged = partial.model_copy(deep=True)
    if not merged.one_line.strip():
        merged.one_line = existing.one_line
    if merged.translated_title is None:
        merged.translated_title = existing.translated_title
    if merged.context_summary is None:
        merged.context_summary = existing.context_summary
    if not merged.time_map and existing.time_map:
        merged.time_map = [entry.model_copy(deep=True) for entry in existing.time_map]
    if not merged.outline and existing.outline:
        merged.outline = [entry.model_copy(deep=True) for entry in existing.outline]
    if not merged.detailed_notes.strip():
        merged.detailed_notes = existing.detailed_notes
    if not merged.high_fidelity_text.strip():
        merged.high_fidelity_text = existing.high_fidelity_text
    if not merged.translated_transcript and existing.translated_transcript:
        merged.translated_transcript = [entry.model_copy(deep=True) for entry in existing.translated_transcript]
    if not merged.prerequisites and existing.prerequisites:
        merged.prerequisites = list(existing.prerequisites)
    if not merged.thought_prompts and existing.thought_prompts:
        merged.thought_prompts = list(existing.thought_prompts)
    if not merged.review_suggestions and existing.review_suggestions:
        merged.review_suggestions = list(existing.review_suggestions)
    if not merged.beginner_focus and existing.beginner_focus:
        merged.beginner_focus = list(existing.beginner_focus)
    if not merged.experienced_guidance and existing.experienced_guidance:
        merged.experienced_guidance = list(existing.experienced_guidance)
    return merged


def create_app(
    data_dir: Path | None = None,
    workspace_dir: Path | None = None,
    runner: YtDlpRunner | None = None,
    settings: Settings | None = None,
    env_path: Path | None | object = _DEFAULT_ENV_PATH,
    web_dist_dir: Path | None | object = _DEFAULT_WEB_DIST,
) -> FastAPI:
    active_settings = settings or load_settings()
    settings_state = {"value": active_settings}
    settings_lock = RLock()
    import_lock = Lock()
    active_data_dir = data_dir or active_settings.data_dir
    active_env_path: Path | None
    if env_path is _DEFAULT_ENV_PATH:
        active_env_path = default_env_path()
    elif isinstance(env_path, Path):
        active_env_path = env_path
    else:
        active_env_path = None
    active_workspace_dir = workspace_dir or active_settings.workspace_dir or active_data_dir
    _prepare_workspace(active_workspace_dir, active_data_dir)
    _maybe_auto_cleanup_asr_cache(active_data_dir, active_settings)
    library = CourseLibrary(active_workspace_dir)
    ytdlp_runner = runner or YtDlpRunner(cookie_cache_dir=active_data_dir / "cookies")
    _normalize_library_at_startup(library, active_workspace_dir, ytdlp_runner)
    jobs: dict[str, StudyJobStatus] = {}
    cancellable_job_ids: set[str] = set()
    cancelled_job_ids: set[str] = set()
    job_cancel_messages: dict[str, tuple[str, str]] = {}
    asr_results: dict[str, AsrCorrectionResult] = {}
    job_instances: dict[str, str] = {}
    job_sources: dict[str, str] = {}
    source_operations = SourceOperations()
    job_source_tickets: dict[str, int] = {}
    study_drafts: dict[str, tuple[str, CourseItem, StudyMaterial]] = {}
    jobs_lock = RLock()
    stopping = Event()
    job_futures = {}
    admitted_job_ids: set[str] = set()
    asr_results_lock = Lock()
    study_item_locks = WeakValueDictionary()
    study_item_locks_lock = Lock()
    study_executor = KeyedExecutor(max_workers=2)
    download_executor = ThreadPoolExecutor(max_workers=1)
    extract_executor = ThreadPoolExecutor(max_workers=1)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            yield
        finally:
            stopping.set()
            with jobs_lock:
                for job_id, job in list(jobs.items()):
                    if job.status in {"queued", "running", "cancelling"}:
                        cancelled_job_ids.add(job_id)
                        if job.status == "queued":
                            _finish_cancelled_job(job_id)
                futures = list(job_futures.values())
            study_executor.shutdown(wait=False, cancel_futures=True)
            download_executor.shutdown(wait=False, cancel_futures=True)
            extract_executor.shutdown(wait=False, cancel_futures=True)
            if futures:
                _, pending = await asyncio.to_thread(wait, futures, timeout=3)
                if pending:
                    logger.warning("Shutdown requested cancellation; %d operations are still closing", len(pending))

    app = FastAPI(title="Course Navigator", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(CourseConflict)
    async def course_conflict_handler(_, exc: CourseConflict):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    allowed_origins = _web_origins(active_settings.web_host, active_settings.web_port)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # The API is served on the web port; the legacy API host is not listened on.
    allowed_hosts = _allowed_request_hosts(active_settings.web_host)

    # CORS only hides responses; this guard also refuses the side effects of
    # cross-site form posts and DNS-rebinding pages that reach the local port.
    @app.middleware("http")
    async def local_request_guard(request, call_next):
        rejection = _local_request_rejection(request.method, request.headers, allowed_hosts, allowed_origins)
        if rejection:
            return JSONResponse(status_code=403, content={"detail": rejection})
        return await call_next(request)

    @app.get("/api/health")
    def health() -> dict[str, bool | str]:
        return {"ok": True, "name": "Course Navigator"}

    @app.post("/api/cookies/text")
    def save_cookie_text(request: CookieTextRequest) -> CookieTextResponse:
        try:
            normalized = normalize_cookie_text(request.text)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        cookie_path = active_data_dir / "cookies" / "manual.cookies.txt"
        try:
            cookie_path.parent.mkdir(parents=True, exist_ok=True)
            cookie_path.write_text(normalized, encoding="utf-8")
            try:
                cookie_path.chmod(0o600)
            except OSError:
                pass
        except OSError as exc:
            raise HTTPException(status_code=400, detail=f"无法保存 Cookie 文件: {exc}") from exc
        return CookieTextResponse(path=str(cookie_path))

    @app.get("/api/items")
    def list_items() -> list[CourseItem]:
        return [_normalize_item_for_response(_with_study_draft(item), active_workspace_dir) for item in library.list_items()]

    @app.get("/api/items/{item_id}")
    def get_item(item_id: str) -> CourseItem:
        item = library.get(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Course item not found")
        return _normalize_item_for_response(_with_study_draft(item), active_workspace_dir)

    def _with_study_draft(item: CourseItem) -> CourseItem:
        with jobs_lock:
            draft = study_drafts.get(item.id)
            if draft:
                _, expected, study = draft
                if (item.instance_id == expected.instance_id and study_input(item) == study_input(expected)
                        and item.study == expected.study):
                    return item.model_copy(update={"study": study.model_copy(deep=True)})
        return item

    def _publish_study_draft(job_id: str, expected: CourseItem, study: StudyMaterial) -> None:
        _raise_if_job_cancelled(job_id)
        current = library.get(expected.id)
        if (current is None or current.instance_id != expected.instance_id
                or study_input(current) != study_input(expected) or current.study != expected.study):
            raise CourseConflict("Course changed during generation; discard the draft and try again")
        with jobs_lock:
            study_drafts[expected.id] = (job_id, expected, study.model_copy(deep=True))

    def _job_item(job_id: str, item_id: str) -> CourseItem:
        item = library.get(item_id)
        with jobs_lock:
            instance_id = job_instances.get(job_id)
        if item is None or (instance_id is not None and item.instance_id != instance_id):
            raise CourseConflict("Course was deleted or replaced before this job started")
        return item

    def _prune_jobs() -> None:
        with jobs_lock:
            now = datetime.now(timezone.utc).timestamp()
            completed = sorted(
                (job for job in jobs.values() if job.status in {"succeeded", "failed", "cancelled"}
                 and job.job_id not in admitted_job_ids),
                key=lambda job: job.updated_at or "",
            )
            for index, job in enumerate(completed):
                expired = bool(job.updated_at and now - datetime.fromisoformat(job.updated_at).timestamp() > JOB_RETENTION_SECONDS)
                if not expired and index >= len(completed) - MAX_RETAINED_JOBS:
                    continue
                jobs.pop(job.job_id, None)
                job_instances.pop(job.job_id, None)
                job_sources.pop(job.job_id, None)
                cancellable_job_ids.discard(job.job_id)
                cancelled_job_ids.discard(job.job_id)
                job_cancel_messages.pop(job.job_id, None)
                with asr_results_lock:
                    asr_results.pop(job.job_id, None)

    def _check_job_capacity() -> None:
        _prune_jobs()
        if stopping.is_set():
            raise HTTPException(status_code=503, detail="服务正在退出，请稍后重试。")
        if len(admitted_job_ids) >= MAX_ACTIVE_JOBS:
            raise HTTPException(status_code=429, detail="后台任务队列已满，请等待已有任务完成。")

    def _schedule(job_id: str, executor, *args) -> None:
        try:
            future = executor.submit(*args)
        except RuntimeError as exc:
            with jobs_lock:
                admitted_job_ids.discard(job_id)
                ticket = job_source_tickets.pop(job_id, None)
                if ticket is not None:
                    source_operations.finish(ticket)
            _set_job(job_id, status="failed", phase="failed", progress=100, message="无法加入任务队列", error=str(exc))
            raise HTTPException(status_code=503, detail="任务队列暂不可用，请稍后重试。") from exc
        with jobs_lock:
            job_futures[job_id] = future

        def finished(completed):
            with jobs_lock:
                ticket = job_source_tickets.pop(job_id, None)
                if ticket is not None:
                    source_operations.finish(ticket)
                # A normal completion means the work item actually left its
                # executor queue. A UI cancellation alone does not free this.
                admitted_job_ids.discard(job_id)
                job_futures.pop(job_id, None)
                if completed.cancelled():
                    _finish_cancelled_job(job_id)
                elif completed.exception() is not None:
                    _set_job(job_id, status="failed", phase="failed", progress=100,
                             message="后台任务异常结束", error=str(completed.exception()))
                _prune_jobs()

        future.add_done_callback(finished)

    def _commit_job_result(job_id: str, item: CourseItem, changes: dict[str, object], message: str,
                           *, input_key: Callable[[CourseItem], object] = study_input) -> CourseItem:
        with library.lock, jobs_lock:
            _raise_if_job_cancelled(job_id)
            updated = library.update(item, changes, input_key=input_key)
            _set_job(job_id, status="succeeded", phase="complete", progress=100, message=message)
            return updated

    def _existing_course_for_url(url: str, items: list[CourseItem] | None = None) -> CourseItem | None:
        request_keys = _source_keys(url, None)
        for item in library.list_items() if items is None else items:
            source_keys = _remote_course_source_keys(item)
            if source_keys and (source_keys & request_keys or (item.metadata and item.metadata.webpage_url == url)):
                return item
        return None

    def _guard_source_operation(function):
        @wraps(function)
        def guarded(*args, **kwargs):
            job_id = kwargs.get("job_id")
            with jobs_lock:
                ticket = job_source_tickets.get(job_id)
            owned = ticket is None
            if owned:
                ticket = source_operations.begin()
            try:
                return function(*args, **kwargs, source_ticket=ticket)
            finally:
                if owned:
                    source_operations.finish(ticket)
        return guarded

    def _commit_media_binding(item: CourseItem, updated: CourseItem) -> CourseItem:
        with library.lock:
            result = library.update(item, _changed_course_fields(item, updated), input_key=media_input)
            source_operations.invalidate(_source_keys(item.source_url, item.metadata))
            return result

    def _check_same_instance(expected: CourseItem | None, current: CourseItem | None) -> None:
        if expected and (current is None or current.instance_id != expected.instance_id):
            raise CourseConflict("Course was deleted or replaced while loading its source")

    def _bind_extract_job(job_id: str, item: CourseItem) -> None:
        with jobs_lock:
            _raise_if_job_cancelled(job_id)
            expected_instance = job_instances.get(job_id)
            if expected_instance and expected_instance != item.instance_id:
                raise CourseConflict("Course was replaced while the extraction waited in the queue")
            job_instances[job_id] = item.instance_id
            _set_job(job_id, item_id=item.id)

    @app.get("/api/library-state")
    def get_library_state() -> LibraryState:
        return library.load_state()

    @app.get("/api/library-errors")
    def get_library_errors() -> dict[str, str]:
        return dict(library.read_errors)

    @app.get("/api/library-errors/{filename}")
    def download_unreadable_record(filename: str) -> FileResponse:
        if filename not in library.read_errors or Path(filename).name != filename:
            raise HTTPException(status_code=404, detail="Unreadable course record not found")
        return FileResponse(library.items_dir / filename, filename=filename, media_type="application/octet-stream")

    @app.put("/api/library-state")
    def update_library_state(request: LibraryState) -> LibraryState:
        state = _normalized_library_state(request)
        library.save_state(state)
        return state

    def _serialize_imports(function):
        @wraps(function)
        def guarded(*args, **kwargs):
            with import_lock:
                return function(*args, **kwargs)
        return guarded

    @app.post("/api/import")
    @_serialize_imports
    def import_course_package(package: CourseSharePackage) -> CourseImportResponse:
        if package.format != "course-navigator-share" or package.version != 1:
            raise HTTPException(status_code=400, detail="Unsupported course package")
        if not package.items:
            raise HTTPException(status_code=400, detail="Course package is empty")
        imported: list[CourseItem] = []
        now = datetime.now(timezone.utc).isoformat()
        for entry in package.items:
            transcript = _validated_transcript(entry.transcript)
            preferred_id = entry.id or (entry.metadata.id if entry.metadata else "") or entry.title or entry.source_url
            item_id = _unique_import_item_id(library, preferred_id)
            item = CourseItem(
                id=item_id,
                source_url=entry.source_url,
                title=entry.title.strip() or (entry.metadata.title if entry.metadata else item_id),
                custom_title=True,
                collection_group_title=entry.collection_group_title.strip() if entry.collection_group_title else "",
                collection_title=entry.collection_title.strip() if entry.collection_title else "",
                course_index=entry.course_index,
                sort_order=entry.sort_order,
                duration=_best_duration(entry.duration, entry.metadata.duration if entry.metadata else None, _duration_from_transcript(transcript)),
                created_at=entry.created_at or now,
                transcript=transcript,
                transcript_source="imported",
                transcript_language=entry.transcript_language,
                metadata=entry.metadata,
                study=entry.study,
                video_source_type="remote",
                local_video_path=None,
            )
            library.create(item)
            imported.append(_normalize_item_for_response(item, active_workspace_dir))
        message = package.message.strip() if package.message else None
        return CourseImportResponse(items=imported, message=message or None)

    @app.post("/api/local-videos")
    @_serialize_imports
    def import_local_video(file: UploadFile = FormFile(...)) -> CourseItem:
        filename = Path(file.filename or "").name
        if not filename:
            raise HTTPException(status_code=400, detail="Local video file is required")
        extension = Path(filename).suffix.lower()
        if extension not in LOCAL_VIDEO_EXTENSIONS:
            raise HTTPException(status_code=400, detail="Unsupported local video file type")
        item_id = _unique_import_item_id(library, Path(filename).stem)
        course_index = _next_course_index(library.list_items(), "", item_id)
        item = CourseItem(
            id=item_id, source_url=f"local-video://{item_id}", title=_local_video_title(filename),
            custom_title=True, collection_title="", course_index=course_index, sort_order=course_index,
            created_at=datetime.now(timezone.utc).isoformat(), video_source_type="workspace",
        )
        try:
            with prepared_video(active_workspace_dir, item, file.file, extension) as video_path:
                item = item.model_copy(update={
                    "duration": _probe_local_video_duration(ytdlp_runner, video_path),
                    "local_video_path": _workspace_relative_path(active_workspace_dir, video_path),
                })
                library.create(item)
        except CourseConflict:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Unable to import local video: {exc}") from exc
        return _normalize_item_for_response(item, active_workspace_dir)

    @app.post("/api/local-video-paths")
    @_serialize_imports
    def import_local_video_paths(request: LocalVideoPathImportRequest) -> list[CourseItem]:
        try:
            imported = _import_video_paths(library, active_workspace_dir, ytdlp_runner, request.paths, request.mode)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return imported

    @app.post("/api/local-video-file-picker")
    @_serialize_imports
    def import_local_video_file_picker(request: LocalVideoFilePickerRequest) -> list[CourseItem]:
        try:
            paths = [str(path) for path in _pick_local_video_paths(multiple=True)]
            if not paths:
                return []
            imported = _import_video_paths(library, active_workspace_dir, ytdlp_runner, paths, request.mode)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return imported

    @app.post("/api/items/{item_id}/video-source")
    def bind_video_source(item_id: str, request: VideoSourceBindingRequest) -> CourseItem:
        item = library.get(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Course item not found")
        try:
            updated = _bind_video_source_for_item(item, active_workspace_dir, ytdlp_runner, request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        updated = _commit_media_binding(item, updated)
        return _normalize_item_for_response(updated, active_workspace_dir)

    @app.post("/api/items/{item_id}/video-source-picker")
    def bind_video_source_from_picker(item_id: str) -> CourseItem:
        item = library.get(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Course item not found")
        try:
            paths = _pick_local_video_paths(multiple=False)
            if not paths:
                return _normalize_item_for_response(item, active_workspace_dir)
            updated = _bind_video_source_for_item(
                item,
                active_workspace_dir,
                ytdlp_runner,
                VideoSourceBindingRequest(source_type="external", path=str(paths[0])),
            )
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        updated = _commit_media_binding(item, updated)
        return _normalize_item_for_response(updated, active_workspace_dir)

    @app.post("/api/items/{item_id}/workspace-video-picker")
    def import_workspace_video_from_picker(item_id: str) -> CourseItem:
        item = library.get(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Course item not found")
        if _has_workspace_video_file(active_workspace_dir, item):
            raise HTTPException(status_code=400, detail="Workspace video sources cannot be changed directly")
        try:
            paths = _pick_local_video_paths(multiple=False)
            if not paths:
                return _normalize_item_for_response(item, active_workspace_dir)
            library.validate_snapshot(item, input_key=media_input)
            with _import_workspace_video_source_for_item(
                item,
                active_workspace_dir,
                ytdlp_runner,
                paths[0],
            ) as prepared:
                updated = _commit_media_binding(item, prepared)
        except CourseConflict:
            raise
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _normalize_item_for_response(updated, active_workspace_dir)

    @app.post("/api/preview")
    def preview(request: ExtractRequest) -> CourseItem:
        return _preview_source(request)

    @_guard_source_operation
    def _preview_source(request: ExtractRequest, *, source_ticket: int) -> CourseItem:
        if _is_file_video_url(request.url):
            item = _file_video_item_for_request(request)
            if item:
                return _normalize_item_for_response(item, active_workspace_dir)
            raise HTTPException(status_code=404, detail="Local video course not found")
        expected = _existing_course_for_url(request.url)
        try:
            metadata = ytdlp_runner.fetch_metadata(request)
        except (ValueError, YtDlpError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        with library.lock:
            source_operations.check(source_ticket, _source_keys(request.url, metadata))
            existing, item = _prepare_remote_course(library, request.url, metadata)
            _check_same_instance(expected, existing)
            if existing:
                item = library.update(existing, _changed_course_fields(existing, item))
            else:
                library.create(item)
        return item

    @app.post("/api/extract")
    def extract(request: ExtractRequest) -> CourseItem:
        if _is_file_video_url(request.url):
            try:
                return _extract_and_save_local_video_course(request)
            except YtDlpError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            return _extract_and_save_course(request)
        except CourseConflict:
            raise
        except (ValueError, YtDlpError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @_guard_source_operation
    def _extract_and_save_course(
        request: ExtractRequest,
        progress: Callable[[str, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
        job_id: str | None = None,
        source_ticket: int = 0,
    ) -> CourseItem:
        if progress:
            progress("metadata", 3, "正在读取视频信息")
        with library.lock:
            initial_items = library.list_items()
            expected = _existing_course_for_url(request.url, initial_items)
            initial_inputs = {saved.instance_id: remote_extraction_input(saved) for saved in initial_items}
        del initial_items
        metadata = ytdlp_runner.fetch_metadata(request)
        with library.lock:
            source_operations.check(source_ticket, _source_keys(request.url, metadata))
            existing, item = _prepare_remote_course(library, request.url, metadata)
            _check_same_instance(expected, existing)
            if existing and initial_inputs.get(existing.instance_id) != remote_extraction_input(existing):
                raise CourseConflict("Course inputs changed while loading metadata; extract again from the updated course")
            if job_id:
                _bind_extract_job(job_id, item)
        item_id = item.id
        if progress:
            progress("metadata", 8, "已读取视频信息，正在准备字幕")
        transcript_dir = active_data_dir / "subtitles" / item_id / item.instance_id / uuid4().hex
        with artifacts.lease(transcript_dir, remove_on_error=True):
            transcript, transcript_source = _extract_transcript_with_source(
                ytdlp_runner,
                request,
                transcript_dir,
                item_id,
                metadata,
                settings_state["value"],
                progress=progress,
                should_cancel=should_cancel,
            )

            keep_existing_study = bool(existing and _same_transcript(existing.transcript, transcript))
            item = item.model_copy(update={
                "duration": _best_duration(metadata.duration, item.duration, _duration_from_transcript(transcript)),
                "transcript": transcript,
                "transcript_source": transcript_source,
                "transcript_language": _extracted_transcript_language(request, metadata, transcript_source, transcript),
                "study": existing.study if keep_existing_study else None,
            })
            if progress:
                progress("saving", 96, "正在保存字幕")
            if should_cancel and should_cancel():
                raise JobCancelled("Subtitle extraction was cancelled")
            with library.lock, jobs_lock:
                source_operations.check(source_ticket, _source_keys(request.url, metadata))
                if job_id:
                    _raise_if_job_cancelled(job_id)
                if existing:
                    item = library.update(existing, _changed_course_fields(existing, item), input_key=remote_extraction_input)
                else:
                    library.create(item)
                if job_id:
                    _set_job(job_id, status="succeeded", progress=100, phase="complete", message="字幕已提取")
        if transcript_source in {"asr", "online_asr"}:
            _maybe_auto_cleanup_asr_cache(active_data_dir, settings_state["value"])
        return item

    def _extract_and_save_local_video_course(
        request: ExtractRequest,
        progress: Callable[[str, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
        job_id: str | None = None,
    ) -> CourseItem:
        item = _file_video_item_for_request(request)
        if not item:
            raise YtDlpError("Local video course not found")
        if job_id:
            _bind_extract_job(job_id, item)
        video_path = _file_video_path_for_item(item)
        if not video_path:
            raise YtDlpError("Linked video file is unavailable" if _is_external_video_item(item) else "Local video not found")
        transcript_dir = active_data_dir / "subtitles" / item.id / item.instance_id / uuid4().hex
        with artifacts.lease(transcript_dir, remove_on_error=True):
            if request.subtitle_source == "online_asr":
                transcript = _extract_online_asr_transcript_from_file(
                    video_path,
                    request,
                    transcript_dir,
                    item.id,
                    settings_state["value"],
                    progress,
                    should_cancel=should_cancel,
                )
                transcript_source = "online_asr"
            elif request.subtitle_source == "asr":
                transcript = _extract_asr_transcript_from_file(
                    video_path,
                    request,
                    transcript_dir,
                    item.id,
                    ytdlp_runner,
                    progress,
                    should_cancel=should_cancel,
                )
                transcript_source = "asr"
            else:
                transcript, transcript_source = _extract_file_video_source_first_fallback(
                    video_path,
                    request,
                    transcript_dir,
                    item.id,
                    settings_state["value"],
                    ytdlp_runner,
                    progress,
                    should_cancel=should_cancel,
                )

            keep_existing_study = bool(_same_transcript(item.transcript, transcript))
            next_item = item.model_copy(
                update={
                    "duration": _best_duration(item.duration, _duration_from_transcript(transcript)),
                    "transcript": transcript,
                    "transcript_source": transcript_source,
                    "transcript_language": _extracted_transcript_language(request, None, transcript_source, transcript),
                    "study": item.study if keep_existing_study else None,
                }
            )
            if progress:
                progress("saving", 96, "正在保存字幕")
            if should_cancel and should_cancel():
                raise JobCancelled("Subtitle extraction was cancelled")
            changes = _changed_course_fields(item, next_item)
            next_item = (_commit_job_result(job_id, item, changes, "字幕已提取", input_key=local_extraction_input) if job_id
                         else library.update(item, changes, input_key=local_extraction_input))
        _maybe_auto_cleanup_asr_cache(active_data_dir, settings_state["value"])
        return _normalize_item_for_response(next_item, active_workspace_dir)

    def _local_video_item_for_request(request: ExtractRequest) -> CourseItem | None:
        return library.get(_local_video_item_id_from_url(request.url))

    def _local_video_path_for_item(item: CourseItem) -> Path | None:
        return _local_video_path_for_workspace_item(active_workspace_dir, item)

    def _file_video_item_for_request(request: ExtractRequest) -> CourseItem | None:
        if _is_local_video_url(request.url):
            return _local_video_item_for_request(request)
        if _is_external_video_url(request.url):
            return library.get(_external_video_item_id_from_url(request.url))
        return None

    def _file_video_path_for_item(item: CourseItem) -> Path | None:
        return _file_video_path_for_workspace_item(active_workspace_dir, item)

    @app.patch("/api/items/{item_id}")
    def update_item_title(item_id: str, request: CourseItemUpdate) -> CourseItem:
        item = library.get(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Course item not found")
        updates: dict[str, object] = {}
        fields = request.model_fields_set
        if "title" in fields and request.title is not None:
            title = request.title.strip()
            if not title:
                raise HTTPException(status_code=400, detail="Course title is required")
            updates["title"] = title
            updates["custom_title"] = True
            if "translated_title" not in fields and item.study:
                updates["study"] = item.study.model_copy(update={"translated_title": None})
        if "translated_title" in fields:
            translated_title = request.translated_title.strip() if request.translated_title else ""
            if item.study:
                updates["study"] = item.study.model_copy(update={"translated_title": translated_title or None})
            elif translated_title:
                updates["study"] = StudyMaterial(
                    one_line=f"{item.title} 已更新标题译文。",
                    translated_title=translated_title,
                    time_map=[],
                    outline=[],
                    detailed_notes="",
                    high_fidelity_text="",
                    translated_transcript=[],
                    prerequisites=[],
                    thought_prompts=[],
                    review_suggestions=[],
                )
        if "collection_title" in fields:
            collection_title = request.collection_title.strip() if request.collection_title else ""
            updates["collection_title"] = collection_title
        if "collection_group_title" in fields:
            collection_group_title = request.collection_group_title.strip() if request.collection_group_title else ""
            updates["collection_group_title"] = collection_group_title
        if "course_index" in fields:
            updates["course_index"] = request.course_index
        if "sort_order" in fields:
            updates["sort_order"] = request.sort_order
        if not updates:
            raise HTTPException(status_code=400, detail="No course updates provided")
        item = library.update(item, updates)
        return _normalize_item_for_response(item, active_workspace_dir)

    @app.put("/api/items/{item_id}/transcript")
    def update_transcript(item_id: str, request: TranscriptUpdateRequest) -> CourseItem:
        item = library.get(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Course item not found")
        transcript = _validated_transcript(request.transcript)
        updates: dict[str, object] = {"transcript": transcript}
        # Edits keep the known track language; only an explicit value (including
        # null for a replacement of unknown language) changes it.
        if "language" in request.model_fields_set:
            updates["transcript_language"] = request.language
        if item.study:
            updates["study"] = item.study.model_copy(
                update={
                    "translated_transcript": [],
                    "context_summary": None,
                }
            )
        item = library.update(item, updates)
        return _normalize_item_for_response(item, active_workspace_dir)

    @app.delete("/api/items/{item_id}")
    def delete_item(item_id: str) -> dict[str, bool]:
        with library.lock:
            item = library.get(item_id)
            if not item:
                raise HTTPException(status_code=404, detail="Course item not found")
            deleted = library.delete(item_id)
            source_operations.invalidate(_source_keys(item.source_url, item.metadata))
            with jobs_lock:
                for job_id, job in list(jobs.items()):
                    if ((job.item_id == item_id and job_instances.get(job_id) == item.instance_id
                         or job_sources.get(job_id) == item.source_url)
                            and job.status in {"queued", "running", "cancelling"}):
                        cancelled_job_ids.add(job_id)
                        if job.status == "queued":
                            _finish_cancelled_job(job_id)
            _delete_course_artifacts(active_data_dir, active_workspace_dir, item)
        return {"deleted": deleted}

    @app.delete("/api/items/{item_id}/local-video")
    def delete_local_video(item_id: str) -> CourseItem:
        item = library.get(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Course item not found")
        if _is_external_video_item(item):
            raise HTTPException(status_code=400, detail="Linked video imports must be deleted from the course library")
        was_local_import = _is_local_video_item(item)
        item = _detach_local_video(library, active_workspace_dir, item,
                                  "workspace" if was_local_import else "remote")
        return _normalize_item_for_response(item, active_workspace_dir)

    @app.post("/api/items/{item_id}/study")
    def generate_study(item_id: str, request: StudyRequest | None = None) -> StudyMaterial:
        with _study_item_lock(item_id):
            item = library.get(item_id)
            if not item:
                raise HTTPException(status_code=404, detail="Course item not found")
            output_language = request.output_language if request else "zh-CN"
            section = request.section if request else "all"
            detail_level = request.detail_level if request and request.detail_level else settings_state["value"].study_detail_level
            if section == "all":
                study = generate_study_material(
                    title=item.title,
                    transcript=item.transcript,
                    provider=settings_state["value"].provider_set,
                    output_language=output_language,
                    detail_level=detail_level,
                    existing_translation=item.study.translated_transcript if item.study else None,
                    existing_context_summary=item.study.context_summary if item.study else None,
                    existing_translated_title=item.study.translated_title if item.study else None,
                    existing_study=item.study,
                    source_language=item.transcript_language,
                    metadata=item.metadata,
                )
            else:
                study = regenerate_study_section(
                    title=item.title,
                    transcript=item.transcript,
                    existing_study=item.study,
                    provider=settings_state["value"].provider_set,
                    output_language=output_language,
                    section=section,
                    detail_level=detail_level,
                    source_language=item.transcript_language,
                    metadata=item.metadata,
                )
            study = stamp_study_cache(study, item.title, item.transcript, output_language,
                                      item.transcript_language, item.metadata)
            library.update(item, {"study": study}, input_key=study_input)
            return study

    @app.post("/api/items/{item_id}/study-jobs")
    def create_study_job(item_id: str, request: StudyRequest | None = None) -> StudyJobStatus:
        item = library.get(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Course item not found")
        job_id = uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        job = StudyJobStatus(
            job_id=job_id,
            item_id=item_id,
            status="queued",
            progress=0,
            phase="queued",
            message="已加入后台生成队列",
            started_at=now,
            updated_at=now,
        )
        with jobs_lock:
            _check_job_capacity()
            jobs[job_id] = job
            admitted_job_ids.add(job_id)
            job_instances[job_id] = item.instance_id
            cancellable_job_ids.add(job_id)
            job_cancel_messages[job_id] = ("学习地图生成已取消", "正在取消学习地图生成")
        output_language = request.output_language if request else "zh-CN"
        section = request.section if request else "all"
        detail_level = request.detail_level if request and request.detail_level else settings_state["value"].study_detail_level
        _schedule(job_id, study_executor, item_id, _run_study_job, job_id, item_id, output_language, section, detail_level)
        return job

    @app.post("/api/items/{item_id}/translation-jobs")
    def create_translation_job(item_id: str, request: StudyRequest | None = None) -> StudyJobStatus:
        item = library.get(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Course item not found")
        if not item.transcript:
            raise HTTPException(status_code=400, detail="请先提取字幕，再翻译字幕")
        job_id = uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        job = StudyJobStatus(
            job_id=job_id,
            item_id=item_id,
            status="queued",
            progress=0,
            phase="queued",
            message="已加入字幕翻译队列",
            started_at=now,
            updated_at=now,
        )
        with jobs_lock:
            _check_job_capacity()
            jobs[job_id] = job
            admitted_job_ids.add(job_id)
            job_instances[job_id] = item.instance_id
            cancellable_job_ids.add(job_id)
            job_cancel_messages[job_id] = ("字幕翻译已取消", "正在取消字幕翻译")
        output_language = request.output_language if request else "zh-CN"
        _schedule(job_id, study_executor, item_id, _run_translation_job, job_id, item_id, output_language)
        return job

    @app.post("/api/items/{item_id}/download-jobs")
    def create_download_job(item_id: str, request: DownloadRequest) -> StudyJobStatus:
        item = library.get(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Course item not found")
        if _is_local_video_item(item) or _is_external_video_item(item):
            raise HTTPException(status_code=400, detail="本地视频已经在 Workspace 中，无需再次缓存。")
        job_id = uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        job = StudyJobStatus(
            job_id=job_id,
            item_id=item_id,
            status="queued",
            progress=0,
            phase="queued",
            message="已加入视频缓存队列",
            started_at=now,
            updated_at=now,
        )
        with jobs_lock:
            _check_job_capacity()
            jobs[job_id] = job
            admitted_job_ids.add(job_id)
            job_instances[job_id] = item.instance_id
            cancellable_job_ids.add(job_id)
            job_cancel_messages[job_id] = ("视频缓存已取消", "正在取消视频缓存")
        _schedule(job_id, download_executor, _run_download_job, job_id, item_id, request)
        return job

    @app.post("/api/extract-jobs")
    def create_extract_job(request: ExtractRequest) -> StudyJobStatus:
        ticket = source_operations.begin()
        try:
            return _admit_extract_job(request, ticket)
        except BaseException:
            source_operations.finish(ticket)
            raise

    def _admit_extract_job(request: ExtractRequest, ticket: int) -> StudyJobStatus:
        if _is_file_video_url(request.url):
            item = _file_video_item_for_request(request)
            if not item:
                raise HTTPException(status_code=404, detail="Local video course not found")
            item_id = item.id
        else:
            item = _existing_course_for_url(request.url)
            item_id = item.id if item else ""
        job_id = uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        job = StudyJobStatus(
            job_id=job_id,
            item_id=item_id,
            status="queued",
            progress=0,
            phase="queued",
            message="已加入字幕提取队列",
            started_at=now,
            updated_at=now,
        )
        with jobs_lock:
            _check_job_capacity()
            jobs[job_id] = job
            admitted_job_ids.add(job_id)
            job_sources[job_id] = request.url
            job_source_tickets[job_id] = ticket
            if item:
                job_instances[job_id] = item.instance_id
            cancellable_job_ids.add(job_id)
            job_cancel_messages[job_id] = ("字幕提取已取消", "正在取消字幕提取")
        _schedule(job_id, extract_executor, _run_extract_job, job_id, request)
        return job

    @app.post("/api/items/{item_id}/asr-correction-jobs")
    def create_asr_correction_job(item_id: str, request: AsrCorrectionRequest | None = None) -> StudyJobStatus:
        item = library.get(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Course item not found")
        active_request = request or AsrCorrectionRequest()
        transcript = active_request.transcript if active_request.transcript is not None else item.transcript
        if not transcript:
            raise HTTPException(status_code=400, detail="请先提取字幕，再校正 ASR")
        transcript = _validated_transcript(transcript)
        model_id = (active_request.model_id or settings_state["value"].asr_model_id).strip()
        provider = settings_state["value"].provider_for(model_id)
        if not provider:
            raise HTTPException(status_code=400, detail="请先为 ASR 校正配置可用模型")
        active_request.search = _effective_asr_search_config(active_request.search, settings_state["value"])
        job_id = uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        job = StudyJobStatus(
            job_id=job_id,
            item_id=item_id,
            status="queued",
            progress=0,
            phase="queued",
            message="已加入 ASR 校正队列",
            started_at=now,
            updated_at=now,
        )
        with jobs_lock:
            _check_job_capacity()
            jobs[job_id] = job
            admitted_job_ids.add(job_id)
            job_instances[job_id] = item.instance_id
            cancellable_job_ids.add(job_id)
            job_cancel_messages[job_id] = ("ASR 校正已取消", "正在取消 ASR 校正")
        with asr_results_lock:
            asr_results.pop(job_id, None)
        _schedule(job_id, study_executor, item_id, _run_asr_correction_job, job_id, item_id, transcript, model_id, active_request, item)
        return job

    @app.get("/api/jobs/{job_id}")
    def get_study_job(job_id: str) -> StudyJobStatus:
        _prune_jobs()
        with jobs_lock:
            job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Study job not found")
        return job

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_study_job(job_id: str) -> StudyJobStatus:
        with jobs_lock:
            job = jobs.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="Study job not found")
            if job_id not in cancellable_job_ids:
                raise HTTPException(status_code=400, detail="This job cannot be cancelled")
            if job.status in {"succeeded", "failed", "cancelled"}:
                return job
            cancelled_job_ids.add(job_id)
            status: JobStatusValue = "cancelled" if job.status == "queued" else "cancelling"
            cancelled_message, cancelling_message = job_cancel_messages.get(job_id, ("任务已取消", "正在取消任务"))
            next_job = job.model_copy(
                update={
                    "status": status,
                    "progress": 100 if status == "cancelled" else job.progress,
                    "phase": "cancelled" if status == "cancelled" else "cancelling",
                    "message": cancelled_message if status == "cancelled" else cancelling_message,
                    "error": None,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            jobs[job_id] = next_job
            return next_job

    @app.get("/api/asr-correction-jobs/{job_id}/result")
    def get_asr_correction_result(job_id: str) -> AsrCorrectionResult:
        with asr_results_lock:
            result = asr_results.get(job_id)
        if not result:
            raise HTTPException(status_code=404, detail="ASR correction result not found")
        return result

    @app.get("/api/settings/model")
    def get_model_settings() -> ModelSettingsResponse:
        return _model_settings_response(settings_state["value"])

    def _commit_settings(next_settings: Settings) -> None:
        if active_env_path:
            try:
                _write_model_env(active_env_path, next_settings)
            except OSError as exc:
                raise HTTPException(status_code=500, detail="无法保存设置，原设置保持不变。请检查磁盘空间和写入权限。") from exc
        settings_state["value"] = next_settings

    @app.get("/api/settings/asr-search")
    def get_asr_search_settings() -> AsrSearchSettingsResponse:
        return _asr_search_settings_response(settings_state["value"])

    @app.put("/api/settings/asr-search")
    def update_asr_search_settings(request: AsrSearchSettingsUpdate) -> AsrSearchSettingsResponse:
        with settings_lock:
            current = settings_state["value"]
            next_search = _updated_asr_search_settings(current.asr_search, request)
            next_settings = current.model_copy(update={"asr_search": next_search})
            _commit_settings(next_settings)
            return _asr_search_settings_response(next_settings)

    @app.get("/api/settings/online-asr")
    def get_online_asr_settings() -> OnlineAsrSettingsResponse:
        return _online_asr_settings_response(settings_state["value"])

    @app.put("/api/settings/online-asr")
    def update_online_asr_settings(request: OnlineAsrSettingsUpdate) -> OnlineAsrSettingsResponse:
        with settings_lock:
            current = settings_state["value"]
            next_online_asr = _updated_online_asr_settings(current.online_asr, request)
            next_settings = current.model_copy(update={"online_asr": next_online_asr})
            _commit_settings(next_settings)
            return _online_asr_settings_response(next_settings)

    @app.get("/api/settings/asr-cache")
    def get_asr_cache_settings() -> AsrCacheSettingsResponse:
        return _asr_cache_settings_response(active_data_dir, settings_state["value"])

    @app.put("/api/settings/asr-cache")
    def update_asr_cache_settings(request: AsrCacheSettingsUpdate) -> AsrCacheSettingsResponse:
        with settings_lock:
            current = settings_state["value"]
            next_settings = current.model_copy(
                update={"asr_cache_auto_cleanup_enabled": request.auto_cleanup_enabled}
            )
            _commit_settings(next_settings)
            if next_settings.asr_cache_auto_cleanup_enabled:
                _maybe_auto_cleanup_asr_cache(active_data_dir, next_settings)
            return _asr_cache_settings_response(active_data_dir, next_settings)

    @app.post("/api/settings/asr-cache/cleanup")
    def cleanup_asr_cache() -> AsrCacheCleanupResponse:
        cleaned_bytes = _cleanup_asr_cache(active_data_dir)
        settings = settings_state["value"]
        return AsrCacheCleanupResponse(
            size_bytes=_asr_cache_size_bytes(active_data_dir),
            threshold_bytes=ASR_CACHE_AUTO_CLEANUP_THRESHOLD_BYTES,
            auto_cleanup_enabled=settings.asr_cache_auto_cleanup_enabled,
            cleaned_bytes=cleaned_bytes,
        )

    @app.put("/api/settings/model")
    def update_model_settings(request: ModelSettingsUpdate) -> ModelSettingsResponse:
        with settings_lock:
            current = settings_state["value"]
            current_by_id = {profile.id: profile for profile in current.effective_model_profiles}
            profiles: list[ModelProfileConfig] = []
            for profile in request.profiles:
                profile_id = profile.id.strip()
                name = profile.name.strip() or profile.model.strip() or profile_id
                base_url = profile.base_url.strip().rstrip("/")
                model = profile.model.strip()
                previous = current_by_id.get(profile_id)
                same_service = (previous and llm_service_identity(previous.base_url, previous.provider_type)
                                == llm_service_identity(base_url, profile.provider_type))
                api_key = profile.api_key.strip() if profile.api_key else (previous.api_key if same_service else None)
                if not profile_id or not base_url or not model:
                    raise HTTPException(status_code=400, detail="Profile id, Base URL, and model are required")
                profiles.append(
                    ModelProfileConfig(
                        id=profile_id,
                        name=name,
                        provider_type=profile.provider_type,
                        base_url=base_url,
                        model=model,
                        context_window=profile.context_window,
                        max_tokens=profile.max_tokens,
                        api_key=api_key,
                    )
                )
            if not profiles:
                raise HTTPException(status_code=400, detail="At least one model profile is required")
            profile_ids = {profile.id for profile in profiles}
            translation_model_id = request.translation_model_id.strip()
            learning_model_id = request.learning_model_id.strip()
            global_model_id = request.global_model_id.strip()
            asr_model_id = request.asr_model_id.strip()
            if "asr_model_id" not in request.model_fields_set and asr_model_id not in profile_ids:
                asr_model_id = global_model_id if global_model_id in profile_ids else profiles[0].id
            role_ids = {translation_model_id, learning_model_id, global_model_id, asr_model_id}
            if not role_ids <= profile_ids:
                raise HTTPException(status_code=400, detail="Every model slot must reference an existing profile")
            default_profile = next((profile for profile in profiles if profile.id == learning_model_id), profiles[0])
            next_settings = current.model_copy(
                update={
                    "llm_base_url": default_profile.base_url,
                    "llm_model": default_profile.model,
                    "llm_api_key": default_profile.api_key,
                    "model_profiles": profiles,
                    "translation_model_id": translation_model_id,
                    "learning_model_id": learning_model_id,
                    "global_model_id": global_model_id,
                    "asr_model_id": asr_model_id,
                    "study_detail_level": request.study_detail_level,
                    "task_parameters": request.task_parameters,
                }
            )
            _commit_settings(next_settings)
            return _model_settings_response(next_settings)

    @app.post("/api/settings/models")
    def list_available_models(request: ModelListRequest) -> ModelListResponse:
        base_url = request.base_url.strip().rstrip("/")
        if not base_url:
            raise HTTPException(status_code=400, detail="Base URL is required")
        api_key = request.api_key
        if not api_key and request.profile_id:
            profile = next(
                (
                    candidate
                    for candidate in settings_state["value"].effective_model_profiles
                    if candidate.id == request.profile_id
                ),
                None,
            )
            if profile and (llm_service_identity(profile.base_url, profile.provider_type)
                            != llm_service_identity(base_url, request.provider_type)):
                raise HTTPException(status_code=400, detail="服务地址或类型已更改，请为新服务重新填写 API Key。")
            api_key = profile.api_key if profile else None
        try:
            if request.provider_type == "anthropic":
                headers = {"anthropic-version": "2023-06-01"}
                if api_key:
                    headers["x-api-key"] = api_key
                response = httpx.get(
                    _anthropic_endpoint_url(base_url, "models"),
                    headers=headers,
                    timeout=30,
                )
            else:
                headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
                response = httpx.get(
                    llm_endpoint(base_url, request.provider_type, "models"),
                    headers=headers,
                    timeout=30,
                )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Unable to fetch models: {exc}") from exc
        return ModelListResponse(models=_extract_model_ids(payload))

    def _download_and_commit(item: CourseItem, request: DownloadRequest, progress=None, should_cancel=None, job_id: str | None = None) -> CourseItem:
        if _is_file_video_url(item.source_url):
            raise HTTPException(status_code=400, detail="本地视频已经在 Workspace 中，无需再次缓存。")
        if request.url != item.source_url:
            raise HTTPException(status_code=400, detail="视频来源已变化，请刷新课程后重试。")
        task_dir = active_workspace_dir / "downloads" / item.instance_id / uuid4().hex
        with artifacts.lease(task_dir):
            try:
                kwargs = _supported_call_kwargs(ytdlp_runner.download_video,
                                                {"progress": progress, "should_cancel": should_cancel})
                video_path = ytdlp_runner.download_video(request, task_dir, item.id, **kwargs)
                if not video_path.resolve().is_relative_to(task_dir.resolve()) or not video_path.is_file():
                    raise ValueError("Downloaded video is outside its task directory or is missing")
                with library.lock:
                    if should_cancel and should_cancel():
                        raise JobCancelled("Video caching was cancelled")
                    changes = {
                        "local_video_path": _workspace_relative_path(active_workspace_dir, video_path),
                        "video_source_type": "workspace",
                    }
                    updated = (_commit_job_result(job_id, item, changes, "视频缓存完成", input_key=media_input) if job_id
                               else library.update(item, changes, input_key=media_input))
                return updated
            except BaseException:
                artifacts.remove_tree(task_dir)
                raise

    @app.post("/api/items/{item_id}/download")
    def download_video(item_id: str, request: DownloadRequest) -> DownloadResponse:
        item = library.get(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Course item not found")
        try:
            updated = _download_and_commit(item, request)
        except CourseConflict:
            raise
        except (ValueError, YtDlpError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return DownloadResponse(path=str(updated.local_video_path))

    @app.post("/api/items/{item_id}/playback-source")
    def resolve_playback_source(item_id: str, force: bool = False) -> CourseItem:
        item = library.get(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Course item not found")
        if item.local_video_path or (not force and _metadata_playback_url(item)):
            return _normalize_item_for_response(item, active_workspace_dir)
        try:
            metadata = ytdlp_runner.fetch_metadata(
                ExtractRequest(
                    url=item.source_url,
                    mode="browser",
                    browser="chrome",
                )
            )
        except (ValueError, YtDlpError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not metadata.stream_url and not metadata.hls_manifest_url:
            raise HTTPException(status_code=400, detail="No playable online video URL found")
        with library.lock:
            current = library.validate_snapshot(item, input_key=media_input)
            item = library.update(item, {
                "metadata": metadata,
                "duration": _best_duration(current.duration, metadata.duration, _duration_from_transcript(current.transcript)),
            }, input_key=media_input)
        return _normalize_item_for_response(item, active_workspace_dir)

    @app.get("/api/items/{item_id}/video")
    def serve_video(item_id: str) -> FileResponse:
        item = library.get(item_id)
        if not item or not item.local_video_path:
            raise HTTPException(status_code=404, detail="Local video not found")
        video_path = _file_video_path_for_item(item)
        if not video_path:
            detail = "Linked video file is unavailable" if _is_external_video_item(item) else "Local video not found"
            raise HTTPException(status_code=404, detail=detail)
        return FileResponse(video_path)

    def _set_job(job_id: str, **updates: object) -> StudyJobStatus | None:
        with jobs_lock:
            job = jobs.get(job_id)
            if not job:
                return None
            if job.status in {"succeeded", "failed", "cancelled"} and updates.get("status", job.status) != job.status:
                return job
            if job.status == "cancelling" and updates.get("status") == "running":
                return job
            updates.setdefault("updated_at", datetime.now(timezone.utc).isoformat())
            next_job = job.model_copy(update=updates)
            jobs[job_id] = next_job
            if next_job.status in {"succeeded", "failed", "cancelled"}:
                draft = study_drafts.get(next_job.item_id)
                if draft and draft[0] == job_id:
                    study_drafts.pop(next_job.item_id, None)
                cancelled_job_ids.discard(job_id)
            return next_job

    def _job_cancel_requested(job_id: str) -> bool:
        with jobs_lock:
            job = jobs.get(job_id)
            return stopping.is_set() or job_id in cancelled_job_ids or bool(job and job.status in {"cancelling", "cancelled"})

    def _raise_if_job_cancelled(job_id: str) -> None:
        if _job_cancel_requested(job_id):
            raise JobCancelled("Job was cancelled")

    def _finish_cancelled_job(job_id: str) -> None:
        with jobs_lock:
            cancelled_job_ids.discard(job_id)
            cancelled_message = job_cancel_messages.get(job_id, ("任务已取消", "正在取消任务"))[0]
        _set_job(
            job_id,
            status="cancelled",
            progress=100,
            phase="cancelled",
            message=cancelled_message,
            error=None,
        )

    def _study_job_cancel_requested(job_id: str) -> bool:
        return _job_cancel_requested(job_id)

    def _raise_if_study_job_cancelled(job_id: str) -> None:
        if _study_job_cancel_requested(job_id):
            raise StudyJobCancelled("Study job was cancelled")

    def _finish_cancelled_study_job(job_id: str) -> None:
        _finish_cancelled_job(job_id)

    def _run_extract_job(job_id: str, request: ExtractRequest) -> None:
        if _job_cancel_requested(job_id):
            _finish_cancelled_job(job_id)
            return
        _set_job(
            job_id,
            status="running",
            progress=1,
            phase="preparing",
            message="正在启动字幕提取",
        )

        def update_progress(phase: str, progress: int, message: str) -> None:
            _raise_if_job_cancelled(job_id)
            _set_job(
                job_id,
                status="running",
                progress=max(1, min(99, progress)),
                phase=phase,
                message=message,
            )

        try:
            should_cancel = lambda: _job_cancel_requested(job_id)
            if _is_file_video_url(request.url):
                item = _extract_and_save_local_video_course(request, progress=update_progress, should_cancel=should_cancel, job_id=job_id)
            else:
                item = _extract_and_save_course(request, progress=update_progress, should_cancel=should_cancel, job_id=job_id)
            _set_job(
                job_id,
                item_id=item.id,
                status="succeeded",
                progress=100,
                phase="complete",
                message="字幕已提取",
            )
        except (JobCancelled, YtDlpCancelled):
            _finish_cancelled_job(job_id)
        except Exception as exc:
            logger.exception("Extract job failed: job_id=%s url=%s", job_id, request.url)
            _set_job(
                job_id,
                status="failed",
                progress=100,
                phase="failed",
                message="字幕提取失败",
                error=str(exc),
            )

    def _study_item_lock(item_id: str) -> Lock:
        with study_item_locks_lock:
            lock = study_item_locks.get(item_id)
            if lock is None:
                lock = Lock()
                study_item_locks[item_id] = lock
            return lock

    def _run_study_job(job_id: str, item_id: str, output_language: str, section: str, detail_level: StudyDetailLevel) -> None:
        with _study_item_lock(item_id):
            _run_study_job_locked(job_id, item_id, output_language, section, detail_level)

    def _run_study_job_locked(job_id: str, item_id: str, output_language: str, section: str, detail_level: StudyDetailLevel) -> None:
        if _study_job_cancel_requested(job_id):
            _finish_cancelled_study_job(job_id)
            return
        _set_job(job_id, status="running", progress=1, phase="preparing",
                 message="正在启动后台学习材料生成" if section == "all" else "正在启动局部重新生成")

        def update_progress(phase: str, progress: int, message: str) -> None:
            _raise_if_study_job_cancelled(job_id)
            _set_job(job_id, status="running", progress=progress, phase=phase, message=message)

        try:
            _raise_if_study_job_cancelled(job_id)
            item = _job_item(job_id, item_id)
            draft = item.study.model_copy(deep=True) if item.study else None

            def save_partial_translation(segments) -> None:
                nonlocal draft
                draft = _study_with_translation(item.model_copy(update={"study": draft}), segments,
                                                draft.translated_title if draft else None,
                                                draft.context_summary if draft else None)
                _publish_study_draft(job_id, item, draft)

            def save_partial_study(partial: StudyMaterial) -> None:
                nonlocal draft
                draft = _merge_partial_study(draft, partial)
                _publish_study_draft(job_id, item, draft)

            if section == "all":
                study = generate_study_material(
                    title=item.title, transcript=item.transcript,
                    provider=settings_state["value"].provider_set,
                    output_language=output_language, detail_level=detail_level,
                    progress=update_progress, partial_translation=save_partial_translation,
                    partial_study=save_partial_study,
                    existing_translation=item.study.translated_transcript if item.study else None,
                    existing_context_summary=item.study.context_summary if item.study else None,
                    existing_translated_title=item.study.translated_title if item.study else None,
                    existing_study=item.study,
                    source_language=item.transcript_language,
                    metadata=item.metadata, should_cancel=lambda: _study_job_cancel_requested(job_id),
                )
            else:
                study = regenerate_study_section(
                    title=item.title, transcript=item.transcript, existing_study=item.study,
                    provider=settings_state["value"].provider_set,
                    output_language=output_language, section=section, detail_level=detail_level,
                    progress=update_progress, source_language=item.transcript_language,
                    metadata=item.metadata, should_cancel=lambda: _study_job_cancel_requested(job_id),
                )
            _raise_if_study_job_cancelled(job_id)
            study = stamp_study_cache(study, item.title, item.transcript, output_language,
                                      item.transcript_language, item.metadata)
            _commit_job_result(job_id, item, {"study": study}, "学习材料已生成")
        except (StudyJobCancelled, JobCancelled, LlmCancelled):
            _finish_cancelled_study_job(job_id)
            return
        except Exception as exc:
            logger.exception("Study job failed: job_id=%s item_id=%s", job_id, item_id)
            _set_job(job_id, status="failed", progress=100, phase="failed", message="学习材料生成失败", error=str(exc))
            return
        _set_job(job_id, status="succeeded", progress=100, phase="complete",
                 message="学习材料已生成" if section == "all" else "学习材料局部已更新")

    def _run_translation_job(job_id: str, item_id: str, output_language: str) -> None:
        with _study_item_lock(item_id):
            _run_translation_job_locked(job_id, item_id, output_language)

    def _run_translation_job_locked(job_id: str, item_id: str, output_language: str) -> None:
        if _job_cancel_requested(job_id):
            _finish_cancelled_job(job_id)
            return
        _set_job(job_id, status="running", progress=1, phase="preparing", message="正在启动字幕翻译")

        def update_progress(phase: str, progress: int, message: str) -> None:
            _raise_if_job_cancelled(job_id)
            _set_job(job_id, status="running", progress=progress, phase=phase, message=message)

        try:
            _raise_if_job_cancelled(job_id)
            item = _job_item(job_id, item_id)
            translated_title = None
            context_summary = None
            partial_segments = []

            def publish() -> None:
                _publish_study_draft(job_id, item, _study_with_translation(
                    item, partial_segments, translated_title, context_summary))

            def save_translated_title(title: str | None) -> None:
                nonlocal translated_title
                translated_title = title
                publish()

            def save_context_summary(summary: str) -> None:
                nonlocal context_summary
                context_summary = summary
                publish()

            def save_partial_translation(segments) -> None:
                nonlocal partial_segments
                partial_segments = segments
                publish()

            translated = translate_transcript_material(
                title=item.title, transcript=item.transcript,
                provider=settings_state["value"].provider_set, output_language=output_language,
                progress=update_progress, partial_translation=save_partial_translation,
                title_translation=save_translated_title, context_summary_created=save_context_summary,
                source_language=item.transcript_language,
                metadata=item.metadata, should_cancel=lambda: _job_cancel_requested(job_id),
            )
            _raise_if_job_cancelled(job_id)
            study = _study_with_translation(item, translated, translated_title, context_summary)
            if not _translated_transcript_complete(item.transcript, translated, allow_source_echo=True):
                raise ValueError("字幕翻译结果不完整，请重试。")
            study.translation_complete = True
            source_language = item.transcript_language
            learning_complete = bool(item.study and item.study.learning_complete and study_cache_matches(
                item.study, item.title, item.transcript, output_language, source_language, item.metadata))
            study = stamp_study_cache(study, item.title, item.transcript, output_language,
                                      source_language, item.metadata, learning_complete=learning_complete)
            _commit_job_result(job_id, item, {"study": study}, "字幕译文已生成")
        except (JobCancelled, LlmCancelled):
            _finish_cancelled_job(job_id)
            return
        except Exception as exc:
            _set_job(job_id, status="failed", progress=100, phase="failed", message="字幕翻译失败", error=str(exc))
            return
        _set_job(job_id, status="succeeded", progress=100, phase="complete", message="字幕译文已生成")

    def _run_download_job(job_id: str, item_id: str, request: DownloadRequest) -> None:
        if _job_cancel_requested(job_id):
            _finish_cancelled_job(job_id)
            return
        _set_job(
            job_id,
            status="running",
            progress=1,
            phase="preparing",
            message="正在准备缓存视频",
        )

        def update_progress(progress: int, message: str) -> None:
            _raise_if_job_cancelled(job_id)
            _set_job(
                job_id,
                status="running",
                progress=max(1, min(99, progress)),
                phase="download",
                message=message,
            )

        try:
            item = _job_item(job_id, item_id)
            _download_and_commit(item, request, update_progress, lambda: _job_cancel_requested(job_id), job_id)
        except (JobCancelled, YtDlpCancelled):
            _finish_cancelled_job(job_id)
            return
        except Exception as exc:
            _set_job(job_id, status="failed", progress=100, phase="failed", message="视频缓存失败", error=str(exc))
            return
        _set_job(
            job_id,
            status="succeeded",
            progress=100,
            phase="complete",
            message="视频缓存完成",
        )

    def _run_asr_correction_job(
        job_id: str,
        item_id: str,
        transcript: list[TranscriptSegment],
        model_id: str,
        request: AsrCorrectionRequest,
        expected: CourseItem,
    ) -> None:
        if _job_cancel_requested(job_id):
            _finish_cancelled_job(job_id)
            return
        _set_job(
            job_id,
            status="running",
            progress=1,
            phase="preparing",
            message="正在启动 ASR 校正",
        )

        def update_progress(phase: str, progress: int, message: str) -> None:
            _raise_if_job_cancelled(job_id)
            _set_job(
                job_id,
                status="running",
                progress=max(1, min(99, progress)),
                phase=phase,
                message=message,
            )

        try:
            should_cancel = lambda: _job_cancel_requested(job_id)
            _raise_if_job_cancelled(job_id)
            item = _job_item(job_id, item_id)
            if _asr_correction_input(item) != _asr_correction_input(expected):
                raise CourseConflict("Course inputs changed while ASR correction waited in the queue")
            provider = settings_state["value"].provider_for(model_id)
            if not provider:
                raise ValueError("请先为 ASR 校正配置可用模型")
            suggestions = suggest_asr_corrections(
                title=item.title,
                transcript=transcript,
                provider=provider,
                search_config=request.search,
                context=_asr_context_for_item(item, request.user_context),
                output_language=request.output_language,
                progress=update_progress,
                should_cancel=should_cancel,
            )
            _raise_if_job_cancelled(job_id)
            update_progress("finalizing", 96, "正在整理校正建议和置信度")
            normalized = _coerce_asr_suggestions(suggestions, transcript)
            result = AsrCorrectionResult(
                job_id=job_id,
                item_id=item_id,
                generated_at=datetime.now(timezone.utc).isoformat(),
                search_enabled=request.search.enabled,
                search_provider=request.search.provider if request.search.enabled else None,
                suggestions=normalized,
            )
            with library.lock, jobs_lock:
                _raise_if_job_cancelled(job_id)
                current = _job_item(job_id, item_id)
                if _asr_correction_input(current) != _asr_correction_input(item):
                    raise CourseConflict("Course inputs changed during ASR correction")
                with asr_results_lock:
                    asr_results[job_id] = result
                _set_job(job_id, status="succeeded", progress=100, phase="complete", message="ASR 校正建议已生成")
        except (JobCancelled, LlmCancelled):
            with asr_results_lock:
                asr_results.pop(job_id, None)
            _finish_cancelled_job(job_id)
            return
        except Exception as exc:
            _set_job(
                job_id,
                status="failed",
                progress=100,
                phase="failed",
                message="ASR 校正失败",
                error=str(exc),
            )
            return
        _set_job(
            job_id,
            status="succeeded",
            progress=100,
            phase="complete",
            message="ASR 校正建议已生成",
        )

    # The launcher serves the built pages from this process; development uses
    # the Vite dev server instead. Mounted last so every API route wins.
    active_web_dist_dir = default_web_dist_dir() if web_dist_dir is _DEFAULT_WEB_DIST else web_dist_dir
    if isinstance(active_web_dist_dir, Path) and (active_web_dist_dir / "index.html").is_file():
        app.mount("/", _WebAssets(directory=active_web_dist_dir, html=True), name="web")

    return app


def _prepare_workspace(workspace_dir: Path, legacy_data_dir: Path) -> None:
    workspace_dir.mkdir(parents=True, exist_ok=True)
    if workspace_dir.resolve() == legacy_data_dir.resolve():
        return
    marker = workspace_dir / ".legacy-migration-v1.json"
    if marker.exists():
        return
    _copy_legacy_child_dir(legacy_data_dir / "items", workspace_dir / "items")
    _copy_legacy_child_dir(legacy_data_dir / "downloads", workspace_dir / "downloads")
    temporary = marker.with_name(f".{marker.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps({"version": 1, "source": str(legacy_data_dir.resolve()),
                                         "completed_at": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
        temporary.replace(marker)
    finally:
        temporary.unlink(missing_ok=True)


def _web_origins(host: str, port: int) -> list[str]:
    hosts = {host}
    if host == "127.0.0.1":
        hosts.add("localhost")
    if host == "localhost":
        hosts.add("127.0.0.1")
    return [f"http://{candidate}:{port}" for candidate in sorted(hosts)]


LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
WILDCARD_HOSTS = frozenset({"", "0.0.0.0", "::"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _allowed_request_hosts(bind_host: str) -> frozenset[str] | None:
    """Host names the service answers to; None when it listens on every address."""
    host = bind_host.strip().strip("[]").lower()
    if host in WILDCARD_HOSTS:
        return None
    return frozenset({host} | LOOPBACK_HOSTS)


def _is_lan_host(host: str) -> bool:
    """With a wildcard bind, LAN clients use an IP address or this machine's
    name; any other domain name may be a DNS-rebinding page."""
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    machine = socket.gethostname().lower()
    return host in LOOPBACK_HOSTS or host in {machine, f"{machine}.local"}


def _split_host_header(value: str) -> str:
    value = value.strip().lower()
    if value.startswith("["):
        return value[1:].split("]", 1)[0]
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def _local_request_rejection(method: str, headers, allowed_hosts: frozenset[str] | None, allowed_origins: list[str]) -> str | None:
    host_header = headers.get("host", "")
    host = _split_host_header(host_header)
    if not (host in allowed_hosts if allowed_hosts is not None else _is_lan_host(host)):
        return "Request host is not allowed."
    if method.upper() in SAFE_METHODS:
        return None
    if headers.get("sec-fetch-site", "").lower() == "cross-site":
        return "Cross-site requests are not allowed."
    origin = headers.get("origin")
    if origin is None:
        # Non-browser clients such as the launcher send no Origin.
        return None
    origin = origin.strip().rstrip("/").lower()
    same_origin = {f"http://{host_header.strip().lower()}", f"https://{host_header.strip().lower()}"}
    if origin in same_origin or origin in {allowed.lower() for allowed in allowed_origins}:
        return None
    return "Request origin is not allowed."


def _copy_legacy_child_dir(source: Path, target: Path) -> None:
    if not source.exists() or not source.is_dir():
        return
    if target.exists() and any(target.iterdir()):
        return
    staging = target.with_name(f".legacy-{target.name}-{uuid4().hex}.tmp")
    try:
        shutil.copytree(source, staging)
        if target.exists():
            target.rmdir()
        staging.replace(target)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _expected_video_source_type(workspace_dir: Path, item: CourseItem):
    if _is_external_video_url(item.source_url) or item.video_source_type == "external":
        return "external"
    if _is_local_video_url(item.source_url):
        return "workspace"
    if item.local_video_path and _local_video_path_for_workspace_item(workspace_dir, item):
        return "workspace"
    return "remote"


def _normalize_library_at_startup(library: CourseLibrary, workspace_dir: Path, runner: YtDlpRunner) -> None:
    items = library.list_items()
    next_unfiled_index = _next_course_index(items, "", "")
    for item in items:
        normalized = item.model_copy(deep=True)
        if not _is_external_video_item(normalized):
            path = _normalized_local_video_reference(workspace_dir, normalized)
            if path is not None:
                normalized.local_video_path = path
        normalized.video_source_type = _expected_video_source_type(workspace_dir, normalized)
        if _is_local_video_item(normalized):
            video_path = _local_video_path_for_workspace_item(workspace_dir, normalized)
            if normalized.duration is None and video_path:
                normalized.duration = _probe_local_video_duration(runner, video_path)
            if normalized.course_index is None:
                normalized.course_index = next_unfiled_index
                next_unfiled_index += 1
            if normalized.sort_order is None:
                normalized.sort_order = normalized.course_index
        changes = _changed_course_fields(item, normalized)
        missing_guidance = bool(item.study and not {"beginner_focus", "experienced_guidance"} <= item.study.model_fields_set)
        if changes or missing_guidance:
            library.update(item, changes)


def _import_video_paths(
    library: CourseLibrary,
    workspace_dir: Path,
    runner: YtDlpRunner,
    paths: list[str],
    mode: str,
) -> list[CourseItem]:
    imported: list[CourseItem] = []
    for raw_path in paths:
        source_path = Path(raw_path).expanduser()
        _validate_local_video_source_path(source_path)
        item = _course_item_from_video_path(library, workspace_dir, runner, source_path, mode)
        if mode == "workspace":
            with prepared_video(workspace_dir, item, source_path, source_path.suffix.lower()) as video_path:
                item = item.model_copy(update={"local_video_path": _workspace_relative_path(workspace_dir, video_path)})
                library.create(item)
        else:
            library.create(item)
        imported.append(_normalize_item_for_response(item, workspace_dir))
    return imported


def _validate_local_video_source_path(path: Path) -> None:
    if not path.exists() or not path.is_file():
        raise ValueError("Local video file not found")
    if path.suffix.lower() not in LOCAL_VIDEO_EXTENSIONS:
        raise ValueError("Unsupported local video file type")


def _pick_local_video_paths(*, multiple: bool) -> list[Path]:
    if sys.platform == "darwin":
        return _pick_local_video_paths_with_osascript(multiple=multiple)
    if sys.platform.startswith("win"):
        return _pick_local_video_paths_with_windows_dialog(multiple=multiple)
    raise ValueError("Local video picker is not supported on this platform")


def _pick_local_video_paths_with_osascript(*, multiple: bool) -> list[Path]:
    multiple_selection_clause = " with multiple selections allowed" if multiple else ""
    script = """
set chosenFiles to choose file with prompt "选择要导入的课程视频" of type {"public.movie"}MULTIPLE_SELECTION_CLAUSE
set output to ""
if class of chosenFiles is list then
  repeat with chosenFile in chosenFiles
    set output to output & POSIX path of chosenFile & linefeed
  end repeat
else
  set output to POSIX path of chosenFiles & linefeed
end if
return output
""".replace("MULTIPLE_SELECTION_CLAUSE", multiple_selection_clause)
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        error = result.stderr.strip()
        if "User canceled" in error or "用户已取消" in error or "-128" in error:
            return []
        raise ValueError(error or "Unable to open Finder video picker")
    return [Path(line) for line in result.stdout.splitlines() if line.strip()]


def _pick_local_video_paths_with_windows_dialog(*, multiple: bool) -> list[Path]:
    extensions = sorted(LOCAL_VIDEO_EXTENSIONS)
    wildcard = ";".join(f"*{extension}" for extension in extensions)
    filter_label = f"Video files ({wildcard})|{wildcard}|All files (*.*)|*.*"
    allow_multiple = "$true" if multiple else "$false"
    script = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class NativeDpi {{
  [DllImport("user32.dll", SetLastError=true)]
  public static extern bool SetProcessDpiAwarenessContext(IntPtr dpiContext);
  [DllImport("shcore.dll", SetLastError=true)]
  public static extern int SetProcessDpiAwareness(int awareness);
}}
"@
try {{
  [NativeDpi]::SetProcessDpiAwarenessContext([IntPtr](-4)) | Out-Null
}} catch {{
  try {{ [NativeDpi]::SetProcessDpiAwareness(2) | Out-Null }} catch {{}}
}}
[System.Windows.Forms.Application]::EnableVisualStyles()
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$owner.ShowInTaskbar = $false
$owner.StartPosition = 'CenterScreen'
$owner.Width = 1
$owner.Height = 1
$owner.Opacity = 0
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = '选择要导入的课程视频'
$dialog.Filter = '{filter_label}'
$dialog.Multiselect = {allow_multiple}
$dialog.RestoreDirectory = $true
try {{
  $owner.Show()
  $owner.Activate()
  if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {{
    $dialog.FileNames | ForEach-Object {{ Write-Output $_ }}
  }}
}} finally {{
  $dialog.Dispose()
  $owner.Close()
  $owner.Dispose()
}}
"""
    result = run_hidden(
        ["powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        error = result.stderr.strip()
        raise ValueError(error or "Unable to open Windows video picker")
    return [Path(line.strip()) for line in result.stdout.splitlines() if line.strip()]


def _bind_video_source_for_item(
    item: CourseItem,
    workspace_dir: Path,
    runner: YtDlpRunner,
    request: VideoSourceBindingRequest,
) -> CourseItem:
    if _has_workspace_video_file(workspace_dir, item):
        raise ValueError("Workspace video sources cannot be changed directly")
    if request.source_type == "external":
        if not request.path or not request.path.strip():
            raise ValueError("Local video file path is required")
        source_path = Path(request.path).expanduser()
        _validate_local_video_source_path(source_path)
        resolved_source = source_path.resolve()
        duration = _probe_local_video_duration(runner, resolved_source)
        return item.model_copy(
            update={
                "source_url": f"external-video://{item.id}",
                "source_identity": None,
                "media_revision": item.media_revision + 1,
                "metadata": None,
                "video_source_type": "external",
                "local_video_path": resolved_source,
                "duration": duration if duration is not None else item.duration,
            }
        )
    if request.source_type == "remote":
        if not request.url or not request.url.strip():
            raise ValueError("Online video URL is required")
        source_url = validate_source_url(request.url)
        if _is_file_video_url(source_url):
            raise ValueError("Use the Finder picker to bind local or NAS video files")
        return item.model_copy(
            update={
                "source_url": source_url,
                "source_identity": None,
                "media_revision": item.media_revision + 1,
                "metadata": item.metadata if source_url == item.source_url else None,
                "video_source_type": "remote",
                "local_video_path": None,
            }
        )
    raise ValueError("Unsupported video source type")


def _has_workspace_video_file(workspace_dir: Path, item: CourseItem) -> bool:
    return _local_video_path_for_workspace_item(workspace_dir, item) is not None


@contextmanager
def _import_workspace_video_source_for_item(
    item: CourseItem,
    workspace_dir: Path,
    runner: YtDlpRunner,
    source_path: Path,
) -> Iterator[CourseItem]:
    if _has_workspace_video_file(workspace_dir, item):
        raise ValueError("Workspace video sources cannot be changed directly")
    source_path = source_path.expanduser()
    _validate_local_video_source_path(source_path)
    with prepared_video(workspace_dir, item, source_path, source_path.suffix.lower()) as video_path:
        duration = _probe_local_video_duration(runner, video_path)
        yield item.model_copy(update={
            "source_url": f"local-video://{item.id}", "source_identity": None, "metadata": None,
            "media_revision": item.media_revision + 1, "video_source_type": "workspace",
            "local_video_path": _workspace_relative_path(workspace_dir, video_path),
            "duration": duration if duration is not None else item.duration,
        })


def _course_item_from_video_path(
    library: CourseLibrary,
    workspace_dir: Path,
    runner: YtDlpRunner,
    source_path: Path,
    mode: str,
) -> CourseItem:
    filename = source_path.name
    item_id = _unique_import_item_id(library, source_path.stem)
    course_index = _next_course_index(library.list_items(), "", item_id)
    if mode == "workspace":
        source_url = f"local-video://{item_id}"
        local_video_path = None
        video_source_type = "workspace"
    elif mode == "external":
        source_url = f"external-video://{item_id}"
        local_video_path = source_path.resolve()
        video_source_type = "external"
    else:
        raise ValueError("Unsupported local video import mode")
    return CourseItem(
        id=item_id,
        source_url=source_url,
        title=_local_video_title(filename),
        custom_title=True,
        collection_group_title="",
        collection_title="",
        course_index=course_index,
        sort_order=course_index,
        duration=_probe_local_video_duration(runner, source_path.resolve()),
        created_at=datetime.now(timezone.utc).isoformat(),
        transcript=[],
        transcript_source=None,
        metadata=None,
        study=None,
        video_source_type=video_source_type,
        local_video_path=local_video_path,
    )


def _normalized_local_video_reference(workspace_dir: Path, item: CourseItem) -> Path | None:
    if not item.local_video_path:
        return None
    raw_path = Path(item.local_video_path)
    resolved = _resolve_workspace_path(workspace_dir, raw_path)
    downloads_dir = (workspace_dir / "downloads").resolve()
    if resolved.exists() and downloads_dir in resolved.parents:
        return _workspace_relative_path(workspace_dir, resolved)
    basename_candidate = downloads_dir / raw_path.name
    if basename_candidate.exists():
        return _workspace_relative_path(workspace_dir, basename_candidate)
    prefix = f"{item.id}."
    if downloads_dir.exists():
        for candidate in sorted(downloads_dir.iterdir()):
            if candidate.is_file() and (candidate.name == item.id or candidate.name.startswith(prefix)):
                return _workspace_relative_path(workspace_dir, candidate)
    return None


def _local_video_path_for_workspace_item(workspace_dir: Path, item: CourseItem) -> Path | None:
    if not item.local_video_path:
        return None
    video_path = _resolve_workspace_path(workspace_dir, Path(item.local_video_path))
    downloads_dir = (workspace_dir / "downloads").resolve()
    if video_path.exists() and downloads_dir in video_path.parents:
        return video_path
    return None


def _file_video_path_for_workspace_item(workspace_dir: Path, item: CourseItem) -> Path | None:
    if _is_external_video_item(item):
        return _external_video_path_for_item(item)
    return _local_video_path_for_workspace_item(workspace_dir, item)


def _external_video_path_for_item(item: CourseItem) -> Path | None:
    if not item.local_video_path:
        return None
    video_path = Path(item.local_video_path).expanduser()
    if not video_path.exists() or not video_path.is_file():
        return None
    if video_path.suffix.lower() not in LOCAL_VIDEO_EXTENSIONS:
        return None
    return video_path.resolve()


def _resolve_workspace_path(workspace_dir: Path, path: Path) -> Path:
    path = path.expanduser()
    if path.is_absolute():
        return path.resolve()
    workspace_candidate = workspace_dir / path
    if workspace_candidate.exists():
        return workspace_candidate.resolve()
    return path.resolve()


def _workspace_relative_path(workspace_dir: Path, path: Path) -> Path:
    resolved = path.expanduser().resolve()
    try:
        return resolved.relative_to(workspace_dir.resolve())
    except ValueError:
        return resolved


def _is_local_video_url(value: str) -> bool:
    return value.startswith("local-video://")


def _is_external_video_url(value: str) -> bool:
    return value.startswith("external-video://")


def _is_file_video_url(value: str) -> bool:
    return _is_local_video_url(value) or _is_external_video_url(value)


def _is_local_video_item(item: CourseItem) -> bool:
    return _is_local_video_url(item.source_url)


def _is_external_video_item(item: CourseItem) -> bool:
    return item.video_source_type == "external" or _is_external_video_url(item.source_url)


def _local_video_item_id_from_url(value: str) -> str:
    return unquote(value.removeprefix("local-video://")).strip("/")


def _external_video_item_id_from_url(value: str) -> str:
    return unquote(value.removeprefix("external-video://")).strip("/")


def _probe_local_video_duration(runner: YtDlpRunner, video_path: Path) -> float | None:
    probe = getattr(runner, "probe_local_video_duration", None)
    if callable(probe):
        duration = probe(video_path)
        return duration if isinstance(duration, (int, float)) and duration > 0 else None
    return None


def _changed_course_fields(before: CourseItem, after: CourseItem) -> dict[str, object]:
    return {name: getattr(after, name) for name in CourseItem.model_fields
            if name not in {"id", "instance_id"} and getattr(before, name) != getattr(after, name)}


def _source_origin(source_url: str) -> tuple[str, str, int | None]:
    parsed = parse_source_url(source_url)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    default_port = {"http": 80, "https": 443}.get(scheme)
    port = parsed.port if parsed.port is not None else default_port
    if (host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
            and scheme in {"http", "https"} and port == default_port):
        return "https", "youtube.com", 443
    return scheme, host, port


def _has_platform_identity(metadata) -> bool:
    return bool(metadata and metadata.id and metadata.id != "unknown"
                and (metadata.extractor or "").lower() not in {"", "generic", "unknown"})


def _source_identity(source_url: str, metadata) -> str:
    try:
        parsed = parse_source_url(source_url)
        origin = _source_origin(source_url)
    except ValueError:
        # Preserve malformed legacy records for editing/deletion, but never
        # compare them as if they belonged to a healthy source origin.
        return json.dumps(["invalid-source-url", source_url], ensure_ascii=False)
    extractor = (metadata.extractor or "").lower() if metadata else ""
    if _has_platform_identity(metadata):
        parts = [2, origin, extractor, metadata.id]
    else:
        parts = [2, origin, parsed.path or "/", parsed.query]
    return json.dumps(parts, ensure_ascii=False, separators=(",", ":"))


def _source_keys(source_url: str, metadata) -> set[str]:
    try:
        origin = _source_origin(source_url)
    except ValueError:
        return set()
    keys = {_source_identity(source_url, metadata), _source_identity(source_url, None)}
    if origin == ("https", "youtube.com", 443):
        parsed = parse_source_url(source_url)
        parts = parsed.path.strip("/").split("/")
        video_id = None
        if parsed.hostname == "youtu.be" and len(parts) == 1:
            video_id = parts[0]
        elif parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [None])[0]
        elif len(parts) == 2 and parts[0] in {"shorts", "embed", "live"}:
            video_id = parts[1]
        if video_id:
            keys.add(json.dumps(["youtube-video", video_id]))
    return keys


def _remote_course_source_keys(item: CourseItem) -> set[str]:
    if _is_file_video_url(item.source_url) or _is_external_video_item(item):
        return set()
    return _source_keys(item.source_url, None)


def _prepare_remote_course(library: CourseLibrary, source_url: str, metadata) -> tuple[CourseItem | None, CourseItem]:
    """Resolve source identity without renaming existing courses or their assets.

    Caller holds library.lock across resolution and any immediate create/update.
    Extraction retains the returned instance until its final guarded commit.
    """
    identity = _source_identity(source_url, metadata)
    items = library.list_items()
    remote_items = [item for item in items if _remote_course_source_keys(item)]
    # Recompute from the saved origin and metadata so legacy identity formats
    # can be upgraded without renaming records or trusting an obsolete key.
    existing = next((item for item in remote_items if _source_identity(item.source_url, item.metadata) == identity), None)
    if existing is None:
        pending_keys = _source_keys(source_url, None)
        existing = next((item for item in remote_items if not _has_platform_identity(item.metadata)
                         and _source_keys(item.source_url, None) & pending_keys), None)
    if existing:
        updates = {
            "source_identity": identity,
            "metadata": metadata,
            "duration": _best_duration(metadata.duration, existing.duration, _duration_from_transcript(existing.transcript)),
            "title": _display_title(metadata, source_url, existing),
            "collection_title": _display_collection_title(metadata, source_url, existing),
            "course_index": _display_course_index(metadata, existing),
        }
        return existing, existing.model_copy(update=updates)
    item_id = _safe_item_id(metadata.id)
    # The preferred legacy-style id is only a name, never a source identity.
    if (library.items_dir / f"{item_id}.json").exists():
        item_id = f"{item_id[:80]}-{hashlib.sha256(identity.encode()).hexdigest()[:16]}"
    while (library.items_dir / f"{item_id}.json").exists():
        item_id = uuid4().hex
    collection_title = _display_collection_title(metadata, source_url, None)
    course_index = _display_course_index(metadata, None)
    if course_index is None:
        course_index = _next_course_index(items, collection_title, item_id)
    return None, CourseItem(
        id=item_id, source_identity=identity, source_url=source_url,
        title=_display_title(metadata, source_url, None), collection_title=collection_title,
        course_index=course_index, sort_order=course_index or _default_sort_order(metadata),
        duration=metadata.duration, created_at=datetime.now(timezone.utc).isoformat(), metadata=metadata,
    )


def _safe_item_id(value: str) -> str:
    safe = "".join(ch if ch.isascii() and (ch.isalnum() or ch in "_-") else "-" for ch in value)
    return safe if safe.strip("-_") else "course"


def _unique_import_item_id(library: CourseLibrary, preferred: str) -> str:
    base = _safe_item_id(preferred).strip("-_") or "course"
    candidates = [base, f"{base}-imported"]
    candidates.extend(f"{base}-imported-{index}" for index in range(2, 10000))
    for candidate in candidates:
        if not library.get(candidate):
            return candidate
    return f"{base}-imported-{uuid4().hex[:8]}"


def _local_video_title(filename: str) -> str:
    stem = Path(filename).stem.strip()
    return stem or "Local video"


def _same_transcript(left: list[TranscriptSegment], right: list[TranscriptSegment]) -> bool:
    if len(left) != len(right):
        return False
    return all(
        abs(first.start - second.start) <= 0.001
        and abs(first.end - second.end) <= 0.001
        and first.text == second.text
        for first, second in zip(left, right)
    )


def _validated_transcript(transcript: list[TranscriptSegment]) -> list[TranscriptSegment]:
    if not transcript:
        raise HTTPException(status_code=400, detail="字幕不能为空")
    normalized: list[TranscriptSegment] = []
    previous_start = -1.0
    for segment in transcript:
        text = segment.text.strip()
        if not text:
            continue
        if segment.end < segment.start:
            raise HTTPException(status_code=400, detail="字幕结束时间不能早于开始时间")
        if segment.start < previous_start:
            raise HTTPException(status_code=400, detail="字幕时间轴必须保持递增")
        normalized.append(TranscriptSegment(start=segment.start, end=segment.end, text=text))
        previous_start = segment.start
    if not normalized:
        raise HTTPException(status_code=400, detail="字幕不能为空")
    return normalized


def _coerce_asr_suggestions(
    suggestions: list[AsrCorrectionSuggestion] | list[dict[str, object]],
    transcript: list[TranscriptSegment],
) -> list[AsrCorrectionSuggestion]:
    normalized: list[AsrCorrectionSuggestion] = []
    for index, suggestion in enumerate(suggestions):
        if isinstance(suggestion, AsrCorrectionSuggestion):
            normalized.append(suggestion)
            continue
        segment_index = int(suggestion.get("segment_index", -1)) if isinstance(suggestion.get("segment_index"), int) else -1
        if segment_index < 0 or segment_index >= len(transcript):
            continue
        segment = transcript[segment_index]
        original_text = str(suggestion.get("original_text") or "").strip()
        corrected_text = str(suggestion.get("corrected_text") or "").strip()
        if not original_text or not corrected_text:
            continue
        normalized.append(
            AsrCorrectionSuggestion(
                id=str(suggestion.get("id") or f"asr-{segment_index}-{index}"),
                segment_index=segment_index,
                start=segment.start,
                end=segment.end,
                original_text=original_text,
                corrected_text=corrected_text,
                confidence=float(suggestion.get("confidence") or 0),
                reason=str(suggestion.get("reason") or "模型建议校正此 ASR 片段。"),
                evidence=str(suggestion.get("evidence") or "").strip() or None,
                status="pending",
                source="search" if suggestion.get("source") == "search" else "model",
            )
        )
    return normalized


def _asr_context_for_item(item: CourseItem, user_context: str | None = None) -> dict[str, object]:
    metadata = item.metadata
    context: dict[str, object] = {
        "title": item.title,
        "collection_group_title": item.collection_group_title,
        "collection_title": item.collection_title,
        "source_url": item.source_url,
        "duration": item.duration,
        "user_context": user_context.strip() if user_context else None,
    }
    if metadata:
        context.update(
            {
                "metadata_title": metadata.title,
                "uploader": metadata.uploader,
                "channel": metadata.channel,
                "creator": metadata.creator,
                "description": _truncate_for_prompt(metadata.description, 1200),
                "webpage_url": metadata.webpage_url,
                "extractor": metadata.extractor,
                "language": metadata.language,
                "playlist_title": metadata.playlist_title,
                "playlist_index": metadata.playlist_index,
                "duration": metadata.duration or item.duration,
                "subtitles": metadata.subtitles,
                "automatic_captions": metadata.automatic_captions,
            }
        )
    return context


def _asr_correction_input(item: CourseItem) -> tuple:
    return transcript_input(item), _asr_context_for_item(item)


def _truncate_for_prompt(value: str | None, limit: int) -> str | None:
    if not value:
        return None
    text = value.strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}\n...truncated..."


def _extract_transcript_with_source(
    runner: YtDlpRunner,
    request: ExtractRequest,
    transcript_dir: Path,
    item_id: str,
    metadata,
    settings: Settings,
    progress: Callable[[str, int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[list[TranscriptSegment], str | None]:
    asr_request = _request_with_metadata_language(request, metadata)
    if request.subtitle_source == "asr":
        return _extract_asr_transcript(runner, asr_request, transcript_dir, item_id, progress, should_cancel=should_cancel), "asr"
    if request.subtitle_source == "online_asr":
        return (
            _extract_online_asr_transcript(
                runner,
                asr_request,
                transcript_dir,
                item_id,
                settings,
                progress,
                should_cancel=should_cancel,
            ),
            "online_asr",
        )

    try:
        if progress:
            progress("subtitles", 15, "正在下载站方字幕")
        transcript = runner.extract_subtitles(request, transcript_dir, metadata)
        if progress:
            progress("subtitles", 88, "站方字幕已下载")
        return transcript, "subtitles" if transcript else None
    except YtDlpError as exc:
        if not is_subtitle_unavailable_error(exc):
            raise
        if _metadata_has_source_subtitles(metadata):
            raise YtDlpError("站方字幕存在，但当前访问方式没有下载到字幕；请使用浏览器模式或 cookies 重新提取。") from exc

    return _extract_source_first_asr_fallback(
        runner,
        asr_request,
        transcript_dir,
        item_id,
        settings,
        progress,
        should_cancel=should_cancel,
    )


def _extracted_transcript_language(request: ExtractRequest, metadata, source: str | None,
                                   transcript: list[TranscriptSegment] | None = None) -> str | None:
    if source == "subtitles":
        if hasattr(transcript, "language"):
            return transcript_language_tag(transcript.language)
        language = choose_source_subtitle_language(metadata, request.language)
        available = [*metadata.subtitles, *metadata.automatic_captions] if metadata else []
        if request.language in {"", "auto"} and language not in available:
            return None
    elif source in {"asr", "online_asr"}:
        language = _request_with_metadata_language(request, metadata).language
    else:
        return None
    return transcript_language_tag(language)


def _request_with_metadata_language(request: ExtractRequest, metadata) -> ExtractRequest:
    if request.language and request.language != "auto":
        return request
    metadata_language = getattr(metadata, "language", None)
    if isinstance(metadata_language, str) and metadata_language.strip():
        return request.model_copy(update={"language": metadata_language.strip()})
    return request


def _metadata_has_source_subtitles(metadata: VideoMetadata | None) -> bool:
    if not metadata:
        return False
    return any(
        language.strip().lower() not in {"danmaku", "live_chat", "comments", "rechat"}
        for language in [*metadata.subtitles, *metadata.automatic_captions]
    )


def _extract_source_first_asr_fallback(
    runner: YtDlpRunner,
    request: ExtractRequest,
    transcript_dir: Path,
    item_id: str,
    settings: Settings,
    progress: Callable[[str, int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[list[TranscriptSegment], str | None]:
    fallback_errors: list[str] = []
    if _online_asr_is_available(settings.online_asr):
        try:
            if progress:
                progress("online_asr", 32, "站方字幕不可用，正在切换在线 ASR")
            transcript = _extract_online_asr_transcript(
                runner,
                request,
                transcript_dir,
                item_id,
                settings,
                progress,
                should_cancel=should_cancel,
            )
            if transcript:
                return transcript, "online_asr"
            fallback_errors.append("在线 ASR 没有返回字幕")
        except YtDlpCancelled:
            raise
        except YtDlpError as exc:
            fallback_errors.append(f"在线 ASR 失败：{exc}")
            if progress:
                progress("asr", 39, "在线 ASR 不可用，正在切换本地 ASR")

    try:
        transcript = _extract_asr_transcript(runner, request, transcript_dir, item_id, progress, should_cancel=should_cancel)
    except YtDlpCancelled:
        raise
    except YtDlpError as exc:
        fallback_errors.append(f"本地 ASR 失败：{exc}")
        _raise_source_first_fallback_error("站方字幕不可用", fallback_errors)
    if transcript:
        return transcript, "asr"
    fallback_errors.append("本地 ASR 没有返回字幕")
    _raise_source_first_fallback_error("站方字幕不可用", fallback_errors)


def _extract_file_video_source_first_fallback(
    video_path: Path,
    request: ExtractRequest,
    transcript_dir: Path,
    item_id: str,
    settings: Settings,
    runner: YtDlpRunner,
    progress: Callable[[str, int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[list[TranscriptSegment], str | None]:
    fallback_errors: list[str] = []
    if _online_asr_is_available(settings.online_asr):
        try:
            if progress:
                progress("online_asr", 32, "本地视频无站方字幕，正在切换在线 ASR")
            transcript = _extract_online_asr_transcript_from_file(
                video_path,
                request,
                transcript_dir,
                item_id,
                settings,
                progress,
                should_cancel=should_cancel,
            )
            if transcript:
                return transcript, "online_asr"
            fallback_errors.append("在线 ASR 没有返回字幕")
        except YtDlpCancelled:
            raise
        except YtDlpError as exc:
            fallback_errors.append(f"在线 ASR 失败：{exc}")
            if progress:
                progress("asr", 39, "在线 ASR 不可用，正在切换本地 ASR")

    try:
        transcript = _extract_asr_transcript_from_file(
            video_path,
            request,
            transcript_dir,
            item_id,
            runner,
            progress,
            should_cancel=should_cancel,
        )
    except YtDlpCancelled:
        raise
    except YtDlpError as exc:
        fallback_errors.append(f"本地 ASR 失败：{exc}")
        _raise_source_first_fallback_error("本地视频无站方字幕", fallback_errors)
    if transcript:
        return transcript, "asr"
    fallback_errors.append("本地 ASR 没有返回字幕")
    _raise_source_first_fallback_error("本地视频无站方字幕", fallback_errors)


def _raise_source_first_fallback_error(reason: str, fallback_errors: list[str]) -> None:
    details = "；".join(error for error in fallback_errors if error)
    if details:
        raise YtDlpError(f"{reason}，且字幕兜底失败：{details}")
    raise YtDlpError(f"{reason}，且字幕兜底失败。")


def _online_asr_is_available(settings: OnlineAsrSettings) -> bool:
    if settings.provider == "none":
        return False
    service = settings.service_for(settings.provider)
    if not service.api_key:
        return False
    if settings.provider == "custom" and not (service.base_url and service.model):
        return False
    return True


def _extract_asr_transcript(
    runner: YtDlpRunner,
    request: ExtractRequest,
    transcript_dir: Path,
    item_id: str,
    progress: Callable[[str, int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> list[TranscriptSegment]:
    extractor = getattr(runner, "extract_asr", None)
    if not callable(extractor):
        if request.subtitle_source == "asr":
            raise YtDlpError("当前提取器不支持本地 ASR")
        return []
    if progress:
        return _call_extract_asr(
            extractor,
            request,
            transcript_dir,
            item_id,
            progress=lambda value, message: progress("asr", value, message),
            should_cancel=should_cancel,
        )
    return _call_extract_asr(extractor, request, transcript_dir, item_id, should_cancel=should_cancel)


def _extract_online_asr_transcript(
    runner: YtDlpRunner,
    request: ExtractRequest,
    transcript_dir: Path,
    item_id: str,
    settings: Settings,
    progress: Callable[[str, int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> list[TranscriptSegment]:
    if progress:
        return extract_online_asr_transcript(
            request,
            transcript_dir,
            item_id,
            getattr(runner, "binary", None),
            settings.online_asr,
            progress=lambda value, message: progress("online_asr", value, message),
            should_cancel=should_cancel,
        )
    return extract_online_asr_transcript(
        request,
        transcript_dir,
        item_id,
        getattr(runner, "binary", None),
        settings.online_asr,
        should_cancel=should_cancel,
    )


def _extract_asr_transcript_from_file(
    video_path: Path,
    request: ExtractRequest,
    transcript_dir: Path,
    item_id: str,
    runner: YtDlpRunner,
    progress: Callable[[str, int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> list[TranscriptSegment]:
    extractor = getattr(runner, "extract_asr_from_file", None)
    if not callable(extractor):
        raise YtDlpError("当前提取器不支持本地视频 ASR")
    if progress:
        return _call_extract_asr_from_file(
            extractor,
            video_path,
            transcript_dir,
            item_id,
            language=request.language,
            progress=lambda value, message: progress("asr", value, message),
            should_cancel=should_cancel,
        )
    return _call_extract_asr_from_file(
        extractor,
        video_path,
        transcript_dir,
        item_id,
        language=request.language,
        should_cancel=should_cancel,
    )


def _supported_call_kwargs(func: Callable[..., object], kwargs: dict[str, object]) -> dict[str, object]:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return {key: value for key, value in kwargs.items() if value is not None}
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()):
        return {key: value for key, value in kwargs.items() if value is not None}
    return {
        key: value
        for key, value in kwargs.items()
        if value is not None and key in signature.parameters
    }


def _call_extract_asr(
    extractor: Callable[..., list[TranscriptSegment]],
    request: ExtractRequest,
    transcript_dir: Path,
    item_id: str,
    *,
    progress: Callable[[int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> list[TranscriptSegment]:
    kwargs = _supported_call_kwargs(extractor, {"progress": progress, "should_cancel": should_cancel})
    return extractor(request, transcript_dir, item_id, **kwargs)


def _call_extract_asr_from_file(
    extractor: Callable[..., list[TranscriptSegment]],
    video_path: Path,
    transcript_dir: Path,
    item_id: str,
    *,
    language: str,
    progress: Callable[[int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> list[TranscriptSegment]:
    kwargs = _supported_call_kwargs(
        extractor,
        {"language": language, "progress": progress, "should_cancel": should_cancel},
    )
    return extractor(video_path, transcript_dir, item_id, **kwargs)


def _extract_online_asr_transcript_from_file(
    video_path: Path,
    request: ExtractRequest,
    transcript_dir: Path,
    item_id: str,
    settings: Settings,
    progress: Callable[[str, int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> list[TranscriptSegment]:
    if progress:
        return extract_online_asr_transcript(
            request,
            transcript_dir,
            item_id,
            None,
            settings.online_asr,
            source_video_path=video_path,
            progress=lambda value, message: progress("online_asr", value, message),
            should_cancel=should_cancel,
        )
    return extract_online_asr_transcript(
        request,
        transcript_dir,
        item_id,
        None,
        settings.online_asr,
        source_video_path=video_path,
        should_cancel=should_cancel,
    )


def _normalize_item_for_response(item: CourseItem, workspace_dir: Path | None = None) -> CourseItem:
    item = _with_available_video_source_for_response(item, workspace_dir)
    item = _with_duration_fallback(item)
    item = _with_display_title_fallback(item)
    item = _with_complete_translation_for_response(item)
    return _with_course_defaults(item)


def _normalized_library_state(state: LibraryState) -> LibraryState:
    return LibraryState(
        manual_collections=_deduped_strings(state.manual_collections),
        manual_collection_groups=_deduped_strings(state.manual_collection_groups),
        collection_order=_deduped_strings(state.collection_order),
        collection_group_order=_deduped_strings(state.collection_group_order),
        collection_group_assignments={
            key.strip(): value.strip()
            for key, value in state.collection_group_assignments.items()
            if key.strip() and value.strip()
        },
    )


def _deduped_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        result.append(normalized)
        seen.add(normalized)
    return result


def _with_available_video_source_for_response(item: CourseItem, workspace_dir: Path | None) -> CourseItem:
    if workspace_dir is None or not item.local_video_path or _is_external_video_item(item):
        return item
    if (item.video_source_type == "workspace" or _is_local_video_item(item)) and not _local_video_path_for_workspace_item(
        workspace_dir,
        item,
    ):
        return item.model_copy(update={"local_video_path": None})
    return item


def _with_duration_fallback(item: CourseItem) -> CourseItem:
    duration = _best_duration(item.duration, item.metadata.duration if item.metadata else None, _duration_from_transcript(item.transcript))
    if duration == item.duration:
        return item
    return item.model_copy(update={"duration": duration})


def _with_display_title_fallback(item: CourseItem) -> CourseItem:
    if item.custom_title:
        return item
    title = _title_from_supported_lesson_url(item.source_url)
    if not title or title == item.title:
        return item
    return item.model_copy(update={"title": title})


def _with_complete_translation_for_response(item: CourseItem) -> CourseItem:
    if not item.study or not item.study.translated_transcript:
        return item
    verified = bool(item.study.translation_complete and item.study.output_language and study_cache_matches(
        item.study, item.title, item.transcript, item.study.output_language, item.transcript_language, item.metadata))
    if _translated_transcript_complete(item.transcript, item.study.translated_transcript, allow_source_echo=verified):
        return item
    study = item.study.model_copy(update={"translated_transcript": []})
    return item.model_copy(update={"study": study})


def _translated_transcript_complete(
    source: list[TranscriptSegment],
    translated: list[TranscriptSegment],
    *,
    allow_source_echo: bool = False,
) -> bool:
    if not source or len(source) != len(translated):
        return False
    for source_segment, translated_segment in zip(source, translated):
        if abs(source_segment.start - translated_segment.start) > 0.4:
            return False
        if abs(source_segment.end - translated_segment.end) > 0.4:
            return False
        if not translated_segment.text.strip():
            return False
        source_text = re.sub(r"\s+", " ", source_segment.text).strip().lower()
        translated_text = re.sub(r"\s+", " ", translated_segment.text).strip().lower()
        if (not allow_source_echo and source_text == translated_text
                and any(character.isalpha() for character in source_text)):
            return False
    return True


def _display_title(metadata: VideoMetadata, source_url: str, existing: CourseItem | None) -> str:
    if existing and existing.custom_title:
        return existing.title
    return _title_from_supported_lesson_url(source_url) or metadata.title


def _with_course_defaults(item: CourseItem) -> CourseItem:
    updates: dict[str, object] = {}
    if item.collection_title is None:
        collection_title = _collection_title_from_supported_url(item.source_url)
        if collection_title:
            updates["collection_title"] = collection_title
    if item.course_index is None and item.metadata and item.metadata.playlist_index:
        updates["course_index"] = float(item.metadata.playlist_index)
    if item.sort_order is None:
        updates["sort_order"] = _default_sort_order(item.metadata)
    return item.model_copy(update=updates) if updates else item


def _display_collection_title(metadata: VideoMetadata, source_url: str, existing: CourseItem | None) -> str | None:
    if existing and existing.collection_title is not None:
        return existing.collection_title
    return _collection_title_from_supported_url(source_url) or _collection_title_from_metadata(metadata)


def _display_course_index(metadata: VideoMetadata, existing: CourseItem | None) -> float | None:
    if existing and existing.course_index is not None:
        return existing.course_index
    return float(metadata.playlist_index) if metadata.playlist_index else None


def _next_course_index(items: list[CourseItem], collection_title: str | None, item_id: str) -> float:
    collection_key = (collection_title or "").strip().casefold()
    indices = [
        item.course_index
        for item in items
        if item.id != item_id
        and item.course_index is not None
        and ((item.collection_title or "").strip().casefold() == collection_key)
    ]
    return float(max(indices, default=0) + 1)


def _default_sort_order(metadata: VideoMetadata | None) -> float | None:
    if metadata and metadata.playlist_index:
        return float(metadata.playlist_index)
    return None


def _metadata_playback_url(item: CourseItem) -> str | None:
    if not item.metadata:
        return None
    return item.metadata.hls_manifest_url or item.metadata.stream_url


def _title_from_supported_lesson_url(source_url: str) -> str | None:
    parsed = try_parse_source_url(source_url)
    if parsed is None:
        return None
    hostname = (parsed.hostname or "").lower()
    if hostname != "learn.deeplearning.ai":
        return None
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if "lesson" not in parts:
        return None
    lesson_index = parts.index("lesson")
    if len(parts) <= lesson_index + 2:
        return None
    slug = parts[-1].strip()
    lesson_id = parts[lesson_index + 1].strip()
    if not slug or slug == lesson_id or not re.search(r"[A-Za-z]", slug):
        return None
    return _sentence_title_from_slug(slug)


def _collection_title_from_supported_url(source_url: str) -> str | None:
    parsed = try_parse_source_url(source_url)
    if parsed is None:
        return None
    hostname = (parsed.hostname or "").lower()
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if hostname == "learn.deeplearning.ai" and "courses" in parts:
        course_index = parts.index("courses")
        if len(parts) > course_index + 1:
            return _title_from_course_slug(parts[course_index + 1])
    return None


def _collection_title_from_metadata(metadata: VideoMetadata) -> str | None:
    return metadata.playlist_title.strip() if metadata.playlist_title else None


def _title_from_course_slug(slug: str) -> str:
    title = _sentence_title_from_slug(slug)
    return " ".join(
        word if word.isupper() else word.capitalize()
        for word in title.split()
    )


def _sentence_title_from_slug(slug: str) -> str:
    acronyms = {
        "agi": "AGI",
        "ai": "AI",
        "api": "API",
        "asr": "ASR",
        "gpt": "GPT",
        "llm": "LLM",
        "ml": "ML",
        "rag": "RAG",
        "url": "URL",
    }
    words = re.split(r"[-_\s]+", slug)
    normalized_words = [acronyms.get(word.lower(), word.lower()) for word in words if word]
    title = " ".join(normalized_words).strip()
    if not title:
        return slug
    return f"{title[0].upper()}{title[1:]}"


def _best_duration(*values: float | None) -> float | None:
    for value in values:
        if value is not None and value > 0:
            return value
    return None


def _duration_from_transcript(transcript: list[TranscriptSegment]) -> float | None:
    if not transcript:
        return None
    end = max((segment.end for segment in transcript), default=0)
    return end if end > 0 else None


def _study_with_translation(
    item: CourseItem,
    segments,
    translated_title: str | None = None,
    context_summary: str | None = None,
) -> StudyMaterial:
    existing = item.study
    return StudyMaterial(
        one_line=existing.one_line if existing else f"{item.title} 已生成字幕译文。",
        translated_title=translated_title,
        context_summary=context_summary,
        time_map=existing.time_map if existing else [],
        outline=existing.outline if existing else [],
        detailed_notes=existing.detailed_notes if existing else "",
        high_fidelity_text=existing.high_fidelity_text if existing else "",
        translated_transcript=segments,
        prerequisites=existing.prerequisites if existing else [],
        thought_prompts=existing.thought_prompts if existing else [],
        review_suggestions=existing.review_suggestions if existing else [],
        beginner_focus=existing.beginner_focus if existing else [],
        experienced_guidance=existing.experienced_guidance if existing else [],
    )


def _delete_course_artifacts(data_dir: Path, workspace_dir: Path, item: CourseItem) -> None:
    if not _is_external_video_item(item):
        _delete_local_video(workspace_dir, item)
        _delete_download_files_for_item(workspace_dir, item.id)
        artifacts.remove_tree(workspace_dir / "downloads" / item.instance_id)
    subtitle_dir = (data_dir / "subtitles" / item.id).resolve()
    subtitles_root = (data_dir / "subtitles").resolve()
    if subtitles_root in subtitle_dir.parents:
        artifacts.remove_tree(subtitle_dir)


def _delete_local_video(workspace_dir: Path, item: CourseItem) -> None:
    if not item.local_video_path:
        return
    _delete_download_path(workspace_dir, _resolve_workspace_path(workspace_dir, Path(item.local_video_path)))


def _detach_local_video(library: CourseLibrary, workspace_dir: Path, expected: CourseItem, source_type: str) -> CourseItem:
    retired: Path | None = None
    original_path: Path | None = None
    with library.lock:
        current = library.validate_snapshot(expected)
        if (current.local_video_path != expected.local_video_path or current.media_revision != expected.media_revision
                or current.source_url != expected.source_url or current.video_source_type != expected.video_source_type):
            raise CourseConflict("Video binding changed; reload before deleting the cached video")
        if current.local_video_path:
            candidate = _resolve_workspace_path(workspace_dir, current.local_video_path).resolve()
            downloads = (workspace_dir / "downloads").resolve()
            if candidate.is_file() and downloads in candidate.parents:
                # A legacy flat filename can be reused by a later import. Move
                # it while ownership is still locked, then only delete the
                # unique retired path after committing the record change.
                original_path = candidate
                retirement_dir = downloads / ".retired" / uuid4().hex
                retirement_dir.mkdir(parents=True)
                retired = retirement_dir / candidate.name
                candidate.replace(retired)
        try:
            updated = library.update(current, {"local_video_path": None, "video_source_type": source_type,
                                               "media_revision": current.media_revision + 1})
        except BaseException:
            if retired is not None and original_path is not None:
                retired.replace(original_path)
                retired.parent.rmdir()
            raise
    if retired is not None:
        artifacts.remove_tree(retired.parent)
    return updated


def _delete_download_path(workspace_dir: Path, path: Path) -> None:
    video_path = path.expanduser().resolve()
    downloads_dir = (workspace_dir / "downloads").resolve()
    if video_path.exists() and downloads_dir in video_path.parents:
        video_path.unlink()


def _delete_download_files_for_item(workspace_dir: Path, item_id: str) -> None:
    downloads_dir = (workspace_dir / "downloads").resolve()
    if not downloads_dir.exists():
        return
    prefix = f"{item_id}."
    for path in downloads_dir.iterdir():
        if path.is_file() and (path.name == item_id or path.name.startswith(prefix)):
            _delete_download_path(workspace_dir, path)


def _asr_cache_settings_response(data_dir: Path, settings: Settings) -> AsrCacheSettingsResponse:
    return AsrCacheSettingsResponse(
        size_bytes=_asr_cache_size_bytes(data_dir),
        threshold_bytes=ASR_CACHE_AUTO_CLEANUP_THRESHOLD_BYTES,
        auto_cleanup_enabled=settings.asr_cache_auto_cleanup_enabled,
    )


def _maybe_auto_cleanup_asr_cache(data_dir: Path, settings: Settings) -> None:
    if not settings.asr_cache_auto_cleanup_enabled:
        return
    if _asr_cache_size_bytes(data_dir) <= ASR_CACHE_AUTO_CLEANUP_THRESHOLD_BYTES:
        return
    _cleanup_asr_cache(data_dir)


def _asr_cache_size_bytes(data_dir: Path) -> int:
    total = 0
    for path in _iter_asr_cache_files(data_dir):
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return total


def _cleanup_asr_cache(data_dir: Path) -> int:
    cleaned_bytes = 0
    root = _asr_cache_root(data_dir)
    with artifacts.lock:
        for path in list(_iter_asr_cache_files(data_dir)):
            if artifacts.is_active(path):
                continue
            try:
                size = path.stat().st_size
                path.unlink()
            except OSError:
                continue
            cleaned_bytes += size
    _prune_empty_dirs(root)
    return cleaned_bytes


def _iter_asr_cache_files(data_dir: Path):
    root = _asr_cache_root(data_dir)
    if not root.exists():
        return
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in ASR_CACHE_AUDIO_SUFFIXES:
            yield path


def _asr_cache_root(data_dir: Path) -> Path:
    return data_dir / "subtitles"


def _prune_empty_dirs(root: Path) -> None:
    with artifacts.lock:
        if not root.exists():
            return
        directories = [path for path in root.rglob("*") if path.is_dir()]
        for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
            if artifacts.is_active(directory) or artifacts.contains_active(directory):
                continue
            try:
                directory.rmdir()
            except OSError:
                pass
        if not artifacts.contains_active(root):
            try:
                root.rmdir()
            except OSError:
                pass


def _model_settings_response(settings: Settings) -> ModelSettingsResponse:
    profiles = settings.effective_model_profiles
    return ModelSettingsResponse(
        profiles=[
            ModelProfileResponse(
                id=profile.id,
                name=profile.name,
                provider_type=profile.provider_type,
                base_url=profile.base_url,
                model=profile.model,
                context_window=profile.context_window,
                max_tokens=profile.max_tokens,
                has_api_key=bool(profile.api_key),
                api_key_preview=_preview_key(profile.api_key),
            )
            for profile in profiles
        ],
        translation_model_id=_role_id_or_first(settings.translation_model_id, profiles),
        learning_model_id=_role_id_or_first(settings.learning_model_id, profiles),
        global_model_id=_role_id_or_first(settings.global_model_id, profiles),
        asr_model_id=_role_id_or_first(settings.asr_model_id, profiles),
        study_detail_level=settings.study_detail_level,
        task_parameters=settings.task_parameters,
    )


def _asr_search_settings_response(settings: Settings) -> AsrSearchSettingsResponse:
    search = settings.asr_search
    return AsrSearchSettingsResponse(
        enabled=search.enabled,
        provider=search.provider,
        result_limit=search.result_limit,
        tavily=_asr_search_service_response(search.tavily),
        firecrawl=_asr_search_service_response(search.firecrawl),
    )


def _asr_search_service_response(service: AsrSearchServiceConfig) -> AsrSearchServiceSettingsResponse:
    return AsrSearchServiceSettingsResponse(
        base_url=service.base_url,
        has_api_key=bool(service.api_key),
        api_key_preview=_preview_key(service.api_key),
    )


def _online_asr_settings_response(settings: Settings) -> OnlineAsrSettingsResponse:
    online_asr = settings.online_asr
    return OnlineAsrSettingsResponse(
        provider=online_asr.provider,
        openai=_online_asr_service_response(online_asr.openai),
        groq=_online_asr_service_response(online_asr.groq),
        xai=_online_asr_service_response(online_asr.xai),
        custom=_online_asr_custom_response(online_asr.custom),
    )


def _online_asr_service_response(service: OnlineAsrServiceConfig) -> OnlineAsrServiceSettingsResponse:
    return OnlineAsrServiceSettingsResponse(
        has_api_key=bool(service.api_key),
        api_key_preview=_preview_key(service.api_key),
    )


def _online_asr_custom_response(service: OnlineAsrServiceConfig) -> OnlineAsrCustomSettingsResponse:
    return OnlineAsrCustomSettingsResponse(
        base_url=service.base_url,
        model=service.model,
        has_api_key=bool(service.api_key),
        api_key_preview=_preview_key(service.api_key),
    )


def _updated_asr_search_settings(current: AsrSearchSettings, request: AsrSearchSettingsUpdate) -> AsrSearchSettings:
    provider = request.provider if "provider" in request.model_fields_set and request.provider else current.provider
    result_limit = request.result_limit if "result_limit" in request.model_fields_set and request.result_limit else current.result_limit
    enabled = request.enabled if "enabled" in request.model_fields_set and request.enabled is not None else current.enabled
    return current.model_copy(
        update={
            "enabled": enabled,
            "provider": provider,
            "result_limit": result_limit,
            "tavily": _updated_asr_search_service(current.tavily, request.tavily, "tavily"),
            "firecrawl": _updated_asr_search_service(current.firecrawl, request.firecrawl, "firecrawl"),
        }
    )


def _updated_asr_search_service(
    current: AsrSearchServiceConfig,
    request: object | None,
    provider: str,
) -> AsrSearchServiceConfig:
    if request is None:
        return current
    fields = getattr(request, "model_fields_set", set())
    base_url = current.base_url
    api_key = current.api_key
    if "base_url" in fields:
        raw_base_url = getattr(request, "base_url", None)
        base_url = raw_base_url.strip() if isinstance(raw_base_url, str) and raw_base_url.strip() else None
    if search_endpoint(provider, base_url) != search_endpoint(provider, current.base_url):
        api_key = None
    if "api_key" in fields:
        raw_api_key = getattr(request, "api_key", None)
        if isinstance(raw_api_key, str) and raw_api_key.strip():
            api_key = raw_api_key.strip()
    return current.model_copy(update={"base_url": base_url, "api_key": api_key})


def _updated_online_asr_settings(current: OnlineAsrSettings, request: OnlineAsrSettingsUpdate) -> OnlineAsrSettings:
    provider = request.provider if "provider" in request.model_fields_set and request.provider is not None else current.provider
    return current.model_copy(
        update={
            "provider": provider,
            "openai": _updated_online_asr_service(current.openai, request.openai, keep_base=True),
            "groq": _updated_online_asr_service(current.groq, request.groq, keep_base=True),
            "xai": _updated_online_asr_service(current.xai, request.xai, keep_base=True),
            "custom": _updated_online_asr_service(current.custom, request.custom, keep_base=False),
        }
    )


def _updated_online_asr_service(
    current: OnlineAsrServiceConfig,
    request: object | None,
    *,
    keep_base: bool,
) -> OnlineAsrServiceConfig:
    if request is None:
        return current
    fields = getattr(request, "model_fields_set", set())
    base_url = current.base_url
    model = current.model
    api_key = current.api_key
    if not keep_base and "base_url" in fields:
        raw_base_url = getattr(request, "base_url", None)
        base_url = raw_base_url.strip() if isinstance(raw_base_url, str) and raw_base_url.strip() else None
    if "model" in fields:
        raw_model = getattr(request, "model", None)
        model = raw_model.strip() if isinstance(raw_model, str) and raw_model.strip() else None
    if (not keep_base and _transcription_endpoint("custom", (base_url or "").rstrip("/"))
            != _transcription_endpoint("custom", (current.base_url or "").rstrip("/"))):
        api_key = None
    if "api_key" in fields:
        raw_api_key = getattr(request, "api_key", None)
        if isinstance(raw_api_key, str) and raw_api_key.strip():
            api_key = raw_api_key.strip()
    return current.model_copy(update={"base_url": base_url, "model": model, "api_key": api_key})


def _effective_asr_search_config(
    request: AsrCorrectionSearchConfig,
    settings: Settings,
) -> AsrCorrectionSearchConfig:
    if not request.enabled:
        return request
    provider: AsrSearchProvider = request.provider
    saved = settings.asr_search.service_for(provider)
    if (not request.api_key and request.base_url
            and search_endpoint(provider, request.base_url) != search_endpoint(provider, saved.base_url)):
        raise HTTPException(status_code=400, detail="搜索服务地址已更改，请重新填写该服务的 API Key。")
    return request.model_copy(
        update={
            "api_key": request.api_key or saved.api_key,
            "base_url": request.base_url or saved.base_url,
            "result_limit": request.result_limit or settings.asr_search.result_limit,
        }
    )


def _preview_key(api_key: str | None) -> str | None:
    if not api_key:
        return None
    if len(api_key) <= 10:
        return "*" * len(api_key)
    return f"{api_key[:4]}{'*' * 8}{api_key[-4:]}"


def _write_model_env(path: Path, settings: Settings) -> None:
    profiles = settings.effective_model_profiles
    profile_payload = [
        {
            "id": profile.id,
            "name": profile.name,
            "provider_type": profile.provider_type,
            "base_url": profile.base_url,
            "model": profile.model,
            "context_window": profile.context_window,
            "max_tokens": profile.max_tokens,
            "api_key": profile.api_key or "",
        }
        for profile in profiles
    ]
    task_parameters_payload = {
        key: value.model_dump(exclude_none=True)
        for key, value in settings.task_parameters.items()
        if value.temperature is not None or value.max_tokens is not None
    }
    updates = {
        "COURSE_NAVIGATOR_DATA_DIR": str(settings.data_dir),
        "COURSE_NAVIGATOR_LLM_BASE_URL": settings.llm_base_url or "",
        "COURSE_NAVIGATOR_LLM_API_KEY": settings.llm_api_key or "",
        "COURSE_NAVIGATOR_LLM_MODEL": settings.llm_model or "",
        "COURSE_NAVIGATOR_MODEL_PROFILES": json.dumps(profile_payload, ensure_ascii=False),
        "COURSE_NAVIGATOR_TRANSLATION_MODEL_ID": settings.translation_model_id,
        "COURSE_NAVIGATOR_LEARNING_MODEL_ID": settings.learning_model_id,
        "COURSE_NAVIGATOR_GLOBAL_MODEL_ID": settings.global_model_id,
        "COURSE_NAVIGATOR_ASR_MODEL_ID": settings.asr_model_id,
        "COURSE_NAVIGATOR_ASR_SEARCH_ENABLED": "true" if settings.asr_search.enabled else "false",
        "COURSE_NAVIGATOR_ASR_SEARCH_PROVIDER": settings.asr_search.provider,
        "COURSE_NAVIGATOR_ASR_SEARCH_RESULT_LIMIT": str(settings.asr_search.result_limit),
        "COURSE_NAVIGATOR_TAVILY_BASE_URL": settings.asr_search.tavily.base_url or "",
        "COURSE_NAVIGATOR_TAVILY_API_KEY": settings.asr_search.tavily.api_key or "",
        "COURSE_NAVIGATOR_FIRECRAWL_BASE_URL": settings.asr_search.firecrawl.base_url or "",
        "COURSE_NAVIGATOR_FIRECRAWL_API_KEY": settings.asr_search.firecrawl.api_key or "",
        "COURSE_NAVIGATOR_ONLINE_ASR_PROVIDER": settings.online_asr.provider,
        "COURSE_NAVIGATOR_OPENAI_ASR_API_KEY": settings.online_asr.openai.api_key or "",
        "COURSE_NAVIGATOR_GROQ_ASR_API_KEY": settings.online_asr.groq.api_key or "",
        "COURSE_NAVIGATOR_XAI_ASR_API_KEY": settings.online_asr.xai.api_key or "",
        "COURSE_NAVIGATOR_XAI_ASR_MODEL": settings.online_asr.xai.model or "",
        "COURSE_NAVIGATOR_CUSTOM_ASR_BASE_URL": settings.online_asr.custom.base_url or "",
        "COURSE_NAVIGATOR_CUSTOM_ASR_MODEL": settings.online_asr.custom.model or "",
        "COURSE_NAVIGATOR_CUSTOM_ASR_API_KEY": settings.online_asr.custom.api_key or "",
        "COURSE_NAVIGATOR_ASR_CACHE_AUTO_CLEANUP_ENABLED": (
            "true" if settings.asr_cache_auto_cleanup_enabled else "false"
        ),
        "COURSE_NAVIGATOR_STUDY_DETAIL_LEVEL": settings.study_detail_level,
        "COURSE_NAVIGATOR_TASK_PARAMETERS": json.dumps(task_parameters_payload, ensure_ascii=False),
    }
    if settings.workspace_dir is not None:
        updates["COURSE_NAVIGATOR_WORKSPACE_DIR"] = str(settings.workspace_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    next_lines: list[str] = []
    for line in existing_lines:
        key = line.split("=", 1)[0].strip()
        if key in updates:
            next_lines.append(f"{key}={_quote_env_value(updates[key])}")
            seen.add(key)
        else:
            next_lines.append(line)
    for key, value in updates.items():
        if key not in seen:
            next_lines.append(f"{key}={_quote_env_value(value)}")
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as output:
            output.write("\n".join(next_lines) + "\n")
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _quote_env_value(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _extract_model_ids(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return []
    raw_models = payload.get("data") or payload.get("models") or []
    if not isinstance(raw_models, list):
        return []
    models: list[str] = []
    for item in raw_models:
        if isinstance(item, str):
            models.append(item)
        elif isinstance(item, dict):
            candidate = item.get("id") or item.get("name")
            if isinstance(candidate, str) and candidate.strip():
                models.append(candidate.strip())
    return sorted(dict.fromkeys(models), key=str.lower)


def _role_id_or_first(role_id: str, profiles: list[ModelProfileConfig]) -> str:
    if any(profile.id == role_id for profile in profiles):
        return role_id
    return profiles[0].id if profiles else role_id


app = create_app()
