from __future__ import annotations

import json
import logging
import os
import re
import shutil
from collections.abc import Callable
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from urllib.parse import unquote, urlparse
from uuid import uuid4

import httpx
from fastapi import FastAPI, File as FormFile, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from .ai import _anthropic_endpoint_url, generate_study_material, regenerate_study_section, translate_transcript_material
from .asr import suggest_asr_corrections
from .config import (
    AsrSearchServiceConfig,
    AsrSearchSettings,
    ModelProfileConfig,
    OnlineAsrServiceConfig,
    OnlineAsrSettings,
    Settings,
    load_settings,
)
from .library import CourseLibrary
from .models import (
    CourseItem,
    CourseImportResponse,
    CourseItemUpdate,
    CourseSharePackage,
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
    StudyMaterial,
    StudyRequest,
    TranscriptSegment,
    TranscriptUpdateRequest,
)
from .online_asr import extract_online_asr_transcript
from .ytdlp import YtDlpError, YtDlpRunner, is_subtitle_unavailable_error

logger = logging.getLogger("course_navigator.app")

LOCAL_VIDEO_EXTENSIONS = {
    ".mp4",
    ".m4v",
    ".mov",
    ".webm",
    ".mkv",
    ".avi",
    ".wmv",
}


def create_app(
    data_dir: Path | None = None,
    workspace_dir: Path | None = None,
    runner: YtDlpRunner | None = None,
    settings: Settings | None = None,
    env_path: Path | None = Path(".env"),
) -> FastAPI:
    active_settings = settings or load_settings()
    settings_state = {"value": active_settings}
    active_data_dir = data_dir or active_settings.data_dir
    active_workspace_dir = workspace_dir or active_settings.workspace_dir or active_data_dir
    _prepare_workspace(active_workspace_dir, active_data_dir)
    library = CourseLibrary(active_workspace_dir)
    _normalize_library_video_paths(library, active_workspace_dir)
    ytdlp_runner = runner or YtDlpRunner()
    _backfill_local_video_items(library, active_workspace_dir, ytdlp_runner)
    jobs: dict[str, StudyJobStatus] = {}
    asr_results: dict[str, AsrCorrectionResult] = {}
    jobs_lock = Lock()
    asr_results_lock = Lock()
    deleted_items: set[str] = set()
    deleted_items_lock = Lock()
    study_executor = ThreadPoolExecutor(max_workers=2)
    download_executor = ThreadPoolExecutor(max_workers=1)
    extract_executor = ThreadPoolExecutor(max_workers=1)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        study_executor.shutdown(wait=False, cancel_futures=True)
        download_executor.shutdown(wait=False, cancel_futures=True)
        extract_executor.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="Course Navigator", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, bool | str]:
        return {"ok": True, "name": "Course Navigator"}

    @app.get("/api/items")
    def list_items() -> list[CourseItem]:
        return [_normalize_item_for_response(item) for item in library.list_items()]

    @app.get("/api/items/{item_id}")
    def get_item(item_id: str) -> CourseItem:
        item = library.get(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Course item not found")
        return _normalize_item_for_response(item)

    @app.post("/api/import")
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
                collection_title=entry.collection_title.strip() if entry.collection_title else "",
                course_index=entry.course_index,
                sort_order=entry.sort_order,
                duration=_best_duration(entry.duration, entry.metadata.duration if entry.metadata else None, _duration_from_transcript(transcript)),
                created_at=entry.created_at or now,
                transcript=transcript,
                transcript_source="imported",
                metadata=entry.metadata,
                study=entry.study,
                local_video_path=None,
            )
            library.save(item)
            with deleted_items_lock:
                deleted_items.discard(item.id)
            imported.append(_normalize_item_for_response(item))
        message = package.message.strip() if package.message else None
        return CourseImportResponse(items=imported, message=message or None)

    @app.post("/api/local-videos")
    def import_local_video(file: UploadFile = FormFile(...)) -> CourseItem:
        filename = Path(file.filename or "").name
        if not filename:
            raise HTTPException(status_code=400, detail="Local video file is required")
        extension = Path(filename).suffix.lower()
        if extension not in LOCAL_VIDEO_EXTENSIONS:
            raise HTTPException(status_code=400, detail="Unsupported local video file type")

        item_id = _unique_import_item_id(library, Path(filename).stem)
        downloads_dir = active_workspace_dir / "downloads"
        downloads_dir.mkdir(parents=True, exist_ok=True)
        video_path = downloads_dir / f"{item_id}{extension}"
        try:
            with video_path.open("wb") as output:
                shutil.copyfileobj(file.file, output)
        except Exception as exc:
            _delete_download_path(active_workspace_dir, video_path)
            raise HTTPException(status_code=400, detail=f"Unable to import local video: {exc}") from exc

        course_index = _next_course_index(library.list_items(), "", item_id)
        item = CourseItem(
            id=item_id,
            source_url=f"local-video://{item_id}",
            title=_local_video_title(filename),
            custom_title=True,
            collection_title="",
            course_index=course_index,
            sort_order=course_index,
            duration=_probe_local_video_duration(ytdlp_runner, video_path),
            created_at=datetime.now(timezone.utc).isoformat(),
            transcript=[],
            transcript_source=None,
            metadata=None,
            study=None,
            local_video_path=_workspace_relative_path(active_workspace_dir, video_path),
        )
        with deleted_items_lock:
            deleted_items.discard(item.id)
        library.save(item)
        return _normalize_item_for_response(item)

    @app.post("/api/preview")
    def preview(request: ExtractRequest) -> CourseItem:
        if _is_local_video_url(request.url):
            item = _local_video_item_for_request(request)
            if item:
                return _normalize_item_for_response(item)
            raise HTTPException(status_code=404, detail="Local video course not found")
        try:
            metadata = ytdlp_runner.fetch_metadata(request)
        except (ValueError, YtDlpError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        item_id = _safe_item_id(metadata.id)
        existing = library.get(item_id)
        title = _display_title(metadata, str(request.url), existing)
        collection_title = _display_collection_title(metadata, str(request.url), existing)
        course_index = _display_course_index(metadata, existing)
        if course_index is None:
            course_index = _next_course_index(library.list_items(), collection_title, item_id)
        sort_order = existing.sort_order if existing and existing.sort_order is not None else course_index or _default_sort_order(metadata)
        item = CourseItem(
            id=item_id,
            source_url=str(request.url),
            title=title,
            custom_title=existing.custom_title if existing else False,
            collection_title=collection_title,
            course_index=course_index,
            sort_order=sort_order,
            duration=_best_duration(
                metadata.duration,
                existing.duration if existing else None,
                _duration_from_transcript(existing.transcript if existing else []),
            ),
            created_at=existing.created_at if existing else datetime.now(timezone.utc).isoformat(),
            transcript=existing.transcript if existing else [],
            transcript_source=existing.transcript_source if existing else None,
            metadata=metadata,
            study=existing.study if existing else None,
            local_video_path=existing.local_video_path if existing else None,
        )
        with deleted_items_lock:
            deleted_items.discard(item.id)
        library.save(item)
        return item

    @app.post("/api/extract")
    def extract(request: ExtractRequest) -> CourseItem:
        if _is_local_video_url(request.url):
            try:
                return _extract_and_save_local_video_course(request)
            except YtDlpError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            return _extract_and_save_course(request)
        except (ValueError, YtDlpError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def _extract_and_save_course(
        request: ExtractRequest,
        progress: Callable[[str, int, str], None] | None = None,
    ) -> CourseItem:
        if progress:
            progress("metadata", 3, "正在读取视频信息")
        metadata = ytdlp_runner.fetch_metadata(request)
        item_id = _safe_item_id(metadata.id)
        if progress:
            progress("metadata", 8, "已读取视频信息，正在准备字幕")
        transcript_dir = active_data_dir / "subtitles" / item_id
        transcript, transcript_source = _extract_transcript_with_source(
            ytdlp_runner,
            request,
            transcript_dir,
            item_id,
            metadata,
            settings_state["value"],
            progress=progress,
        )

        existing = library.get(item_id)
        keep_existing_study = bool(existing and _same_transcript(existing.transcript, transcript))
        title = _display_title(metadata, str(request.url), existing)
        collection_title = _display_collection_title(metadata, str(request.url), existing)
        course_index = _display_course_index(metadata, existing)
        if course_index is None:
            course_index = _next_course_index(library.list_items(), collection_title, item_id)
        sort_order = existing.sort_order if existing and existing.sort_order is not None else course_index or _default_sort_order(metadata)
        item = CourseItem(
            id=item_id,
            source_url=str(request.url),
            title=title,
            custom_title=existing.custom_title if existing else False,
            collection_title=collection_title,
            course_index=course_index,
            sort_order=sort_order,
            duration=_best_duration(metadata.duration, existing.duration if existing else None, _duration_from_transcript(transcript)),
            created_at=existing.created_at if existing else datetime.now(timezone.utc).isoformat(),
            transcript=transcript,
            transcript_source=transcript_source,
            metadata=metadata,
            study=existing.study if keep_existing_study else None,
            local_video_path=existing.local_video_path if existing else None,
        )
        if progress:
            progress("saving", 96, "正在保存字幕")
        with deleted_items_lock:
            deleted_items.discard(item.id)
        library.save(item)
        return item

    def _extract_and_save_local_video_course(
        request: ExtractRequest,
        progress: Callable[[str, int, str], None] | None = None,
    ) -> CourseItem:
        item = _local_video_item_for_request(request)
        if not item:
            raise YtDlpError("Local video course not found")
        video_path = _local_video_path_for_item(item)
        if not video_path:
            raise YtDlpError("Local video not found")
        transcript_dir = active_data_dir / "subtitles" / item.id
        source = request.subtitle_source if request.subtitle_source in {"asr", "online_asr"} else "asr"
        if source == "online_asr":
            transcript = _extract_online_asr_transcript_from_file(
                video_path,
                request,
                transcript_dir,
                item.id,
                settings_state["value"],
                progress,
            )
            transcript_source = "online_asr"
        else:
            transcript = _extract_asr_transcript_from_file(
                video_path,
                request,
                transcript_dir,
                item.id,
                ytdlp_runner,
                progress,
            )
            transcript_source = "asr"

        keep_existing_study = bool(_same_transcript(item.transcript, transcript))
        next_item = item.model_copy(
            update={
                "duration": _best_duration(item.duration, _duration_from_transcript(transcript)),
                "transcript": transcript,
                "transcript_source": transcript_source,
                "study": item.study if keep_existing_study else None,
            }
        )
        library.save(next_item)
        return _normalize_item_for_response(next_item)

    def _local_video_item_for_request(request: ExtractRequest) -> CourseItem | None:
        return library.get(_local_video_item_id_from_url(request.url))

    def _local_video_path_for_item(item: CourseItem) -> Path | None:
        return _local_video_path_for_workspace_item(active_workspace_dir, item)

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
        if "course_index" in fields:
            updates["course_index"] = request.course_index
        if "sort_order" in fields:
            updates["sort_order"] = request.sort_order
        if not updates:
            raise HTTPException(status_code=400, detail="No course updates provided")
        item = item.model_copy(update=updates)
        library.save(item)
        return _normalize_item_for_response(item)

    @app.put("/api/items/{item_id}/transcript")
    def update_transcript(item_id: str, request: TranscriptUpdateRequest) -> CourseItem:
        item = library.get(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Course item not found")
        transcript = _validated_transcript(request.transcript)
        item.transcript = transcript
        if item.study:
            item.study = item.study.model_copy(
                update={
                    "translated_transcript": [],
                    "context_summary": None,
                }
            )
        library.save(item)
        return _normalize_item_for_response(item)

    @app.delete("/api/items/{item_id}")
    def delete_item(item_id: str) -> dict[str, bool]:
        item = library.get(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Course item not found")
        with deleted_items_lock:
            deleted_items.add(item_id)
        _delete_course_artifacts(active_data_dir, active_workspace_dir, item)
        deleted = library.delete(item_id)
        return {"deleted": deleted}

    @app.delete("/api/items/{item_id}/local-video")
    def delete_local_video(item_id: str) -> CourseItem:
        item = library.get(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Course item not found")
        if _is_local_video_item(item):
            raise HTTPException(status_code=400, detail="Local video imports must be deleted from the course library")
        _delete_local_video(active_workspace_dir, item)
        item.local_video_path = None
        library.save(item)
        return item

    @app.post("/api/items/{item_id}/study")
    def generate_study(item_id: str, request: StudyRequest | None = None) -> StudyMaterial:
        item = library.get(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Course item not found")
        output_language = request.output_language if request else "zh-CN"
        section = request.section if request else "all"
        if section == "all":
            study = generate_study_material(
                title=item.title,
                transcript=item.transcript,
                provider=settings_state["value"].provider_set,
                output_language=output_language,
                detail_level=settings_state["value"].study_detail_level,
                existing_translation=item.study.translated_transcript if item.study else None,
                existing_context_summary=item.study.context_summary if item.study else None,
                existing_translated_title=item.study.translated_title if item.study else None,
                source_language=item.metadata.language if item.metadata else None,
            )
        else:
            study = regenerate_study_section(
                title=item.title,
                transcript=item.transcript,
                existing_study=item.study,
                provider=settings_state["value"].provider_set,
                output_language=output_language,
                section=section,
                detail_level=settings_state["value"].study_detail_level,
                source_language=item.metadata.language if item.metadata else None,
            )
        item.study = study
        library.save(item)
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
            jobs[job_id] = job
        output_language = request.output_language if request else "zh-CN"
        section = request.section if request else "all"
        study_executor.submit(_run_study_job, job_id, item_id, output_language, section)
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
            jobs[job_id] = job
        output_language = request.output_language if request else "zh-CN"
        study_executor.submit(_run_translation_job, job_id, item_id, output_language)
        return job

    @app.post("/api/items/{item_id}/download-jobs")
    def create_download_job(item_id: str, request: DownloadRequest) -> StudyJobStatus:
        item = library.get(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Course item not found")
        if _is_local_video_item(item):
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
            jobs[job_id] = job
        download_executor.submit(_run_download_job, job_id, item_id, request)
        return job

    @app.post("/api/extract-jobs")
    def create_extract_job(request: ExtractRequest) -> StudyJobStatus:
        if _is_local_video_url(request.url):
            item = _local_video_item_for_request(request)
            if not item:
                raise HTTPException(status_code=404, detail="Local video course not found")
            if request.subtitle_source not in {"asr", "online_asr"}:
                request = request.model_copy(update={"subtitle_source": "asr"})
            item_id = item.id
        else:
            item_id = ""
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
            jobs[job_id] = job
        extract_executor.submit(_run_extract_job, job_id, request)
        return job

    @app.post("/api/items/{item_id}/asr-correction-jobs")
    def create_asr_correction_job(item_id: str, request: AsrCorrectionRequest | None = None) -> StudyJobStatus:
        item = library.get(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Course item not found")
        active_request = request or AsrCorrectionRequest()
        transcript = active_request.transcript or item.transcript
        if not transcript:
            raise HTTPException(status_code=400, detail="请先提取字幕，再校正 ASR")
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
            jobs[job_id] = job
        with asr_results_lock:
            asr_results.pop(job_id, None)
        study_executor.submit(_run_asr_correction_job, job_id, item_id, _validated_transcript(transcript), model_id, active_request)
        return job

    @app.get("/api/jobs/{job_id}")
    def get_study_job(job_id: str) -> StudyJobStatus:
        with jobs_lock:
            job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Study job not found")
        return job

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

    @app.get("/api/settings/asr-search")
    def get_asr_search_settings() -> AsrSearchSettingsResponse:
        return _asr_search_settings_response(settings_state["value"])

    @app.put("/api/settings/asr-search")
    def update_asr_search_settings(request: AsrSearchSettingsUpdate) -> AsrSearchSettingsResponse:
        current = settings_state["value"]
        next_search = _updated_asr_search_settings(current.asr_search, request)
        next_settings = current.model_copy(update={"asr_search": next_search})
        settings_state["value"] = next_settings
        if env_path:
            _write_model_env(env_path, next_settings)
        return _asr_search_settings_response(next_settings)

    @app.get("/api/settings/online-asr")
    def get_online_asr_settings() -> OnlineAsrSettingsResponse:
        return _online_asr_settings_response(settings_state["value"])

    @app.put("/api/settings/online-asr")
    def update_online_asr_settings(request: OnlineAsrSettingsUpdate) -> OnlineAsrSettingsResponse:
        current = settings_state["value"]
        next_online_asr = _updated_online_asr_settings(current.online_asr, request)
        next_settings = current.model_copy(update={"online_asr": next_online_asr})
        settings_state["value"] = next_settings
        if env_path:
            _write_model_env(env_path, next_settings)
        return _online_asr_settings_response(next_settings)

    @app.put("/api/settings/model")
    def update_model_settings(request: ModelSettingsUpdate) -> ModelSettingsResponse:
        current = settings_state["value"]
        current_by_id = {profile.id: profile for profile in current.effective_model_profiles}
        profiles: list[ModelProfileConfig] = []
        for profile in request.profiles:
            profile_id = profile.id.strip()
            name = profile.name.strip() or profile.model.strip() or profile_id
            base_url = profile.base_url.strip()
            model = profile.model.strip()
            api_key = profile.api_key.strip() if profile.api_key else current_by_id.get(profile_id, ModelProfileConfig(id="", name="", base_url="", model="")).api_key
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
        settings_state["value"] = next_settings
        if env_path:
            _write_model_env(env_path, next_settings)
        return _model_settings_response(next_settings)

    @app.post("/api/settings/models")
    def list_available_models(request: ModelListRequest) -> ModelListResponse:
        base_url = _normalize_model_base_url(request.base_url)
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
                    f"{base_url}/models",
                    headers=headers,
                    timeout=30,
                )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Unable to fetch models: {exc}") from exc
        return ModelListResponse(models=_extract_model_ids(payload))

    @app.post("/api/items/{item_id}/download")
    def download_video(item_id: str, request: DownloadRequest) -> DownloadResponse:
        item = library.get(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Course item not found")
        if _is_local_video_item(item):
            raise HTTPException(status_code=400, detail="本地视频已经在 Workspace 中，无需再次缓存。")
        try:
            video_path = ytdlp_runner.download_video(
                request,
                active_workspace_dir / "downloads",
                item_id,
            )
        except (ValueError, YtDlpError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        item.local_video_path = _workspace_relative_path(active_workspace_dir, video_path)
        library.save(item)
        return DownloadResponse(path=str(item.local_video_path))

    @app.get("/api/items/{item_id}/video")
    def serve_video(item_id: str) -> FileResponse:
        item = library.get(item_id)
        if not item or not item.local_video_path:
            raise HTTPException(status_code=404, detail="Local video not found")
        video_path = _resolve_workspace_path(active_workspace_dir, Path(item.local_video_path))
        downloads_dir = (active_workspace_dir / "downloads").resolve()
        if not video_path.exists() or downloads_dir not in video_path.parents:
            raise HTTPException(status_code=404, detail="Local video not found")
        return FileResponse(video_path)

    def _set_job(job_id: str, **updates: object) -> StudyJobStatus | None:
        with jobs_lock:
            job = jobs.get(job_id)
            if not job:
                return None
            updates.setdefault("updated_at", datetime.now(timezone.utc).isoformat())
            next_job = job.model_copy(update=updates)
            jobs[job_id] = next_job
            return next_job

    def _run_extract_job(job_id: str, request: ExtractRequest) -> None:
        _set_job(
            job_id,
            status="running",
            progress=1,
            phase="preparing",
            message="正在启动字幕提取",
        )

        def update_progress(phase: str, progress: int, message: str) -> None:
            _set_job(
                job_id,
                status="running",
                progress=max(1, min(99, progress)),
                phase=phase,
                message=message,
            )

        try:
            if _is_local_video_url(request.url):
                item = _extract_and_save_local_video_course(request, progress=update_progress)
            else:
                item = _extract_and_save_course(request, progress=update_progress)
            _set_job(
                job_id,
                item_id=item.id,
                status="succeeded",
                progress=100,
                phase="complete",
                message="字幕已提取",
            )
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

    def _run_study_job(job_id: str, item_id: str, output_language: str, section: str) -> None:
        _set_job(
            job_id,
            status="running",
            progress=1,
            phase="preparing",
            message="正在启动后台学习材料生成" if section == "all" else "正在启动局部重新生成",
        )

        def update_progress(phase: str, progress: int, message: str) -> None:
            _set_job(
                job_id,
                status="running",
                progress=progress,
                phase=phase,
                message=message,
            )

        def save_partial_translation(segments) -> None:
            with deleted_items_lock:
                if item_id in deleted_items:
                    return
            item = library.get(item_id)
            if not item:
                return
            existing = item.study
            item.study = StudyMaterial(
                one_line=existing.one_line if existing else f"{item.title} 正在翻译字幕...",
                time_map=existing.time_map if existing else [],
                outline=existing.outline if existing else [],
                detailed_notes=existing.detailed_notes if existing else "",
                high_fidelity_text=existing.high_fidelity_text if existing else "",
                translated_title=existing.translated_title if existing else None,
                context_summary=existing.context_summary if existing else None,
                translated_transcript=segments,
                prerequisites=existing.prerequisites if existing else [],
                thought_prompts=existing.thought_prompts if existing else [],
                review_suggestions=existing.review_suggestions if existing else [],
            )
            library.save(item)

        try:
            item = library.get(item_id)
            if not item:
                raise ValueError("Course item not found")
            if section == "all":
                existing_translation = item.study.translated_transcript if item.study else None
                existing_context_summary = item.study.context_summary if item.study else None
                existing_translated_title = item.study.translated_title if item.study else None
                study = generate_study_material(
                    title=item.title,
                    transcript=item.transcript,
                    provider=settings_state["value"].provider_set,
                    output_language=output_language,  # type: ignore[arg-type]
                    detail_level=settings_state["value"].study_detail_level,
                    progress=update_progress,
                    partial_translation=save_partial_translation,
                    existing_translation=existing_translation,
                    existing_context_summary=existing_context_summary,
                    existing_translated_title=existing_translated_title,
                    source_language=item.metadata.language if item.metadata else None,
                )
            else:
                study = regenerate_study_section(
                    title=item.title,
                    transcript=item.transcript,
                    existing_study=item.study,
                    provider=settings_state["value"].provider_set,
                    output_language=output_language,  # type: ignore[arg-type]
                    section=section,  # type: ignore[arg-type]
                    detail_level=settings_state["value"].study_detail_level,
                    progress=update_progress,
                    source_language=item.metadata.language if item.metadata else None,
                )
            with deleted_items_lock:
                if item_id in deleted_items:
                    raise ValueError("Course item was deleted")
            item.study = study
            library.save(item)
        except Exception as exc:
            logger.exception("Study job failed: job_id=%s item_id=%s", job_id, item_id)
            _set_job(
                job_id,
                status="failed",
                progress=100,
                phase="failed",
                message="学习材料生成失败",
                error=str(exc),
            )
            return
        _set_job(
            job_id,
            status="succeeded",
            progress=100,
            phase="complete",
            message="学习材料已生成" if section == "all" else "学习材料局部已更新",
        )

    def _run_translation_job(job_id: str, item_id: str, output_language: str) -> None:
        _set_job(
            job_id,
            status="running",
            progress=1,
            phase="preparing",
            message="正在启动字幕翻译",
        )

        def update_progress(phase: str, progress: int, message: str) -> None:
            _set_job(
                job_id,
                status="running",
                progress=progress,
                phase=phase,
                message=message,
            )

        translated_title_state: dict[str, str | None] = {"value": None}
        context_summary_state: dict[str, str | None] = {"value": None}

        def save_translated_title(title: str | None) -> None:
            if not title:
                return
            translated_title_state["value"] = title
            item = library.get(item_id)
            if not item:
                return
            item.study = _study_with_translation(
                item,
                item.study.translated_transcript if item.study else [],
                title,
                context_summary_state["value"],
            )
            library.save(item)

        def save_context_summary(summary: str) -> None:
            if not summary:
                return
            context_summary_state["value"] = summary
            item = library.get(item_id)
            if not item:
                return
            item.study = _study_with_translation(
                item,
                item.study.translated_transcript if item.study else [],
                translated_title_state["value"],
                summary,
            )
            library.save(item)

        def save_partial_translation(segments) -> None:
            with deleted_items_lock:
                if item_id in deleted_items:
                    return
            item = library.get(item_id)
            if not item:
                return
            item.study = _study_with_translation(
                item,
                segments,
                translated_title_state["value"],
                context_summary_state["value"],
            )
            library.save(item)

        try:
            item = library.get(item_id)
            if not item:
                raise ValueError("Course item not found")
            translated_title_state["value"] = item.study.translated_title if item.study else None
            context_summary_state["value"] = item.study.context_summary if item.study else None
            translated = translate_transcript_material(
                title=item.title,
                transcript=item.transcript,
                provider=settings_state["value"].provider_set,
                output_language=output_language,  # type: ignore[arg-type]
                progress=update_progress,
                partial_translation=save_partial_translation,
                title_translation=save_translated_title,
                context_summary_created=save_context_summary,
                source_language=item.metadata.language if item.metadata else None,
            )
            with deleted_items_lock:
                if item_id in deleted_items:
                    raise ValueError("Course item was deleted")
            item = library.get(item_id)
            if not item:
                raise ValueError("Course item not found")
            item.study = _study_with_translation(
                item,
                translated,
                translated_title_state["value"],
                context_summary_state["value"],
            )
            library.save(item)
        except Exception as exc:
            _set_job(
                job_id,
                status="failed",
                progress=100,
                phase="failed",
                message="字幕翻译失败",
                error=str(exc),
            )
            return
        _set_job(
            job_id,
            status="succeeded",
            progress=100,
            phase="complete",
            message="字幕译文已生成",
        )

    def _run_download_job(job_id: str, item_id: str, request: DownloadRequest) -> None:
        _set_job(
            job_id,
            status="running",
            progress=1,
            phase="preparing",
            message="正在准备缓存视频",
        )

        def update_progress(progress: int, message: str) -> None:
            _set_job(
                job_id,
                status="running",
                progress=max(1, min(99, progress)),
                phase="download",
                message=message,
            )

        video_path: Path | None = None
        try:
            item = library.get(item_id)
            if not item:
                raise ValueError("Course item not found")
            video_path = ytdlp_runner.download_video(
                request,
                active_workspace_dir / "downloads",
                item_id,
                progress=update_progress,
            )
            with deleted_items_lock:
                if item_id in deleted_items:
                    _delete_download_path(active_workspace_dir, video_path)
                    _delete_download_files_for_item(active_workspace_dir, item_id)
                    raise ValueError("Course item was deleted")
            item = library.get(item_id)
            if not item:
                _delete_download_path(active_workspace_dir, video_path)
                raise ValueError("Course item not found")
            item.local_video_path = _workspace_relative_path(active_workspace_dir, video_path)
            library.save(item)
        except Exception as exc:
            if video_path is not None:
                _delete_download_path(active_workspace_dir, video_path)
            _set_job(
                job_id,
                status="failed",
                progress=100,
                phase="failed",
                message="视频缓存失败",
                error=str(exc),
            )
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
    ) -> None:
        _set_job(
            job_id,
            status="running",
            progress=1,
            phase="preparing",
            message="正在启动 ASR 校正",
        )

        def update_progress(phase: str, progress: int, message: str) -> None:
            _set_job(
                job_id,
                status="running",
                progress=max(1, min(99, progress)),
                phase=phase,
                message=message,
            )

        try:
            item = library.get(item_id)
            if not item:
                raise ValueError("Course item not found")
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
            )
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
            with asr_results_lock:
                asr_results[job_id] = result
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

    return app


def _prepare_workspace(workspace_dir: Path, legacy_data_dir: Path) -> None:
    workspace_existed = workspace_dir.exists()
    workspace_dir.mkdir(parents=True, exist_ok=True)
    if workspace_dir.resolve() == legacy_data_dir.resolve() or workspace_existed:
        return
    _copy_legacy_child_dir(legacy_data_dir / "items", workspace_dir / "items")
    _copy_legacy_child_dir(legacy_data_dir / "downloads", workspace_dir / "downloads")


def _copy_legacy_child_dir(source: Path, target: Path) -> None:
    if not source.exists() or not source.is_dir():
        return
    if target.exists() and any(target.iterdir()):
        return
    shutil.copytree(source, target, dirs_exist_ok=True)


def _normalize_library_video_paths(library: CourseLibrary, workspace_dir: Path) -> None:
    for item in library.list_items():
        normalized = _normalized_local_video_reference(workspace_dir, item)
        if normalized is not None and str(normalized) != str(item.local_video_path):
            item.local_video_path = normalized
            library.save(item)


def _backfill_local_video_items(library: CourseLibrary, workspace_dir: Path, runner: YtDlpRunner) -> None:
    next_unfiled_index = _next_course_index(library.list_items(), "", "")
    for item in library.list_items():
        if not _is_local_video_item(item):
            continue
        updates: dict[str, object] = {}
        video_path = _local_video_path_for_workspace_item(workspace_dir, item)
        if item.duration is None and video_path:
            duration = _probe_local_video_duration(runner, video_path)
            if duration is not None:
                updates["duration"] = duration
        if item.course_index is None:
            updates["course_index"] = next_unfiled_index
            if item.sort_order is None:
                updates["sort_order"] = next_unfiled_index
            next_unfiled_index += 1
        elif item.sort_order is None:
            updates["sort_order"] = item.course_index
        if updates:
            library.save(item.model_copy(update=updates))


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


def _is_local_video_item(item: CourseItem) -> bool:
    return _is_local_video_url(item.source_url)


def _local_video_item_id_from_url(value: str) -> str:
    return unquote(value.removeprefix("local-video://")).strip("/")


def _probe_local_video_duration(runner: YtDlpRunner, video_path: Path) -> float | None:
    probe = getattr(runner, "probe_local_video_duration", None)
    if callable(probe):
        duration = probe(video_path)
        return duration if isinstance(duration, (int, float)) and duration > 0 else None
    return None


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
) -> tuple[list[TranscriptSegment], str | None]:
    asr_request = _request_with_metadata_language(request, metadata)
    if request.subtitle_source == "asr":
        return _extract_asr_transcript(runner, asr_request, transcript_dir, item_id, progress), "asr"
    if request.subtitle_source == "online_asr":
        return _extract_online_asr_transcript(runner, asr_request, transcript_dir, item_id, settings, progress), "online_asr"

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

    try:
        transcript = _extract_asr_transcript(runner, asr_request, transcript_dir, item_id, progress)
    except YtDlpError:
        return [], None
    return transcript, "asr" if transcript else None


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


def _extract_asr_transcript(
    runner: YtDlpRunner,
    request: ExtractRequest,
    transcript_dir: Path,
    item_id: str,
    progress: Callable[[str, int, str], None] | None = None,
) -> list[TranscriptSegment]:
    extractor = getattr(runner, "extract_asr", None)
    if not callable(extractor):
        if request.subtitle_source == "asr":
            raise YtDlpError("当前提取器不支持本地 ASR")
        return []
    if progress:
        return extractor(
            request,
            transcript_dir,
            item_id,
            progress=lambda value, message: progress("asr", value, message),
        )
    return extractor(request, transcript_dir, item_id)


def _extract_online_asr_transcript(
    runner: YtDlpRunner,
    request: ExtractRequest,
    transcript_dir: Path,
    item_id: str,
    settings: Settings,
    progress: Callable[[str, int, str], None] | None = None,
) -> list[TranscriptSegment]:
    if progress:
        return extract_online_asr_transcript(
            request,
            transcript_dir,
            item_id,
            getattr(runner, "binary", "yt-dlp"),
            settings.online_asr,
            progress=lambda value, message: progress("online_asr", value, message),
        )
    return extract_online_asr_transcript(
        request,
        transcript_dir,
        item_id,
        getattr(runner, "binary", "yt-dlp"),
        settings.online_asr,
    )


def _extract_asr_transcript_from_file(
    video_path: Path,
    request: ExtractRequest,
    transcript_dir: Path,
    item_id: str,
    runner: YtDlpRunner,
    progress: Callable[[str, int, str], None] | None = None,
) -> list[TranscriptSegment]:
    extractor = getattr(runner, "extract_asr_from_file", None)
    if not callable(extractor):
        raise YtDlpError("当前提取器不支持本地视频 ASR")
    if progress:
        return extractor(
            video_path,
            transcript_dir,
            item_id,
            language=request.language,
            progress=lambda value, message: progress("asr", value, message),
        )
    return extractor(video_path, transcript_dir, item_id, language=request.language)


def _extract_online_asr_transcript_from_file(
    video_path: Path,
    request: ExtractRequest,
    transcript_dir: Path,
    item_id: str,
    settings: Settings,
    progress: Callable[[str, int, str], None] | None = None,
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
        )
    return extract_online_asr_transcript(
        request,
        transcript_dir,
        item_id,
        None,
        settings.online_asr,
        source_video_path=video_path,
    )


def _normalize_item_for_response(item: CourseItem) -> CourseItem:
    return _with_course_defaults(
        _with_complete_translation_for_response(_with_display_title_fallback(_with_duration_fallback(item)))
    )


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
    if _translated_transcript_complete(item.transcript, item.study.translated_transcript):
        return item
    study = item.study.model_copy(update={"translated_transcript": []})
    return item.model_copy(update={"study": study})


def _translated_transcript_complete(
    source: list[TranscriptSegment],
    translated: list[TranscriptSegment],
) -> bool:
    if not source or len(source) != len(translated):
        return False
    for source_segment, translated_segment in zip(source, translated):
        if abs(source_segment.start - translated_segment.start) > 0.4:
            return False
        if not translated_segment.text.strip():
            return False
        source_text = re.sub(r"\s+", " ", source_segment.text).strip().lower()
        translated_text = re.sub(r"\s+", " ", translated_segment.text).strip().lower()
        if source_text and source_text == translated_text and len(source_text) > 12:
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


def _title_from_supported_lesson_url(source_url: str) -> str | None:
    parsed = urlparse(source_url)
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
    parsed = urlparse(source_url)
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
        translated_title=translated_title or (existing.translated_title if existing else None),
        context_summary=context_summary or (existing.context_summary if existing else None),
        time_map=existing.time_map if existing else [],
        outline=existing.outline if existing else [],
        detailed_notes=existing.detailed_notes if existing else "",
        high_fidelity_text=existing.high_fidelity_text if existing else "",
        translated_transcript=segments,
        prerequisites=existing.prerequisites if existing else [],
        thought_prompts=existing.thought_prompts if existing else [],
        review_suggestions=existing.review_suggestions if existing else [],
    )


def _delete_course_artifacts(data_dir: Path, workspace_dir: Path, item: CourseItem) -> None:
    _delete_local_video(workspace_dir, item)
    _delete_download_files_for_item(workspace_dir, item.id)
    subtitle_dir = (data_dir / "subtitles" / item.id).resolve()
    subtitles_root = (data_dir / "subtitles").resolve()
    if subtitle_dir.exists() and subtitles_root in subtitle_dir.parents:
        shutil.rmtree(subtitle_dir)


def _delete_local_video(workspace_dir: Path, item: CourseItem) -> None:
    if not item.local_video_path:
        return
    _delete_download_path(workspace_dir, _resolve_workspace_path(workspace_dir, Path(item.local_video_path)))


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
            "tavily": _updated_asr_search_service(current.tavily, request.tavily),
            "firecrawl": _updated_asr_search_service(current.firecrawl, request.firecrawl),
        }
    )


def _updated_asr_search_service(
    current: AsrSearchServiceConfig,
    request: object | None,
) -> AsrSearchServiceConfig:
    if request is None:
        return current
    fields = getattr(request, "model_fields_set", set())
    base_url = current.base_url
    api_key = current.api_key
    if "base_url" in fields:
        raw_base_url = getattr(request, "base_url", None)
        base_url = raw_base_url.strip() if isinstance(raw_base_url, str) and raw_base_url.strip() else None
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
    if not keep_base and "model" in fields:
        raw_model = getattr(request, "model", None)
        model = raw_model.strip() if isinstance(raw_model, str) and raw_model.strip() else None
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
    path.write_text("\n".join(next_lines) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


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


def _normalize_model_base_url(value: str) -> str:
    base_url = value.strip().rstrip("/")
    for suffix in ("/chat/completions", "/responses", "/messages"):
        if base_url.endswith(suffix):
            base_url = base_url[: -len(suffix)].rstrip("/")
            break
    return base_url


def _role_id_or_first(role_id: str, profiles: list[ModelProfileConfig]) -> str:
    if any(profile.id == role_id for profile in profiles):
        return role_id
    return profiles[0].id if profiles else role_id


app = create_app()
