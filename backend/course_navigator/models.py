from __future__ import annotations

from pathlib import Path
from typing import Literal


OutputLanguage = Literal["zh-CN", "en", "ja"]
JobStatusValue = Literal["queued", "running", "succeeded", "failed"]
StudySection = Literal["all", "guide", "outline", "detailed", "high"]
ModelProviderType = Literal["openai", "anthropic"]
StudyDetailLevel = Literal["fast", "standard", "detailed", "faithful"]
TranscriptSource = Literal["subtitles", "asr"]
TaskParameterKey = Literal[
    "title_translation",
    "subtitle_translation",
    "semantic_segmentation",
    "guide",
    "outline",
    "interpretation",
    "high_fidelity",
]

from pydantic import BaseModel, Field, HttpUrl


class TranscriptSegment(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str


class ExtractRequest(BaseModel):
    url: HttpUrl
    mode: Literal["normal", "browser", "cookies"] = "normal"
    browser: str = "chrome"
    cookies_path: str | None = None
    language: str = "auto"
    subtitle_source: TranscriptSource = "subtitles"


class DownloadRequest(BaseModel):
    url: HttpUrl
    mode: Literal["normal", "browser", "cookies"] = "normal"
    browser: str = "chrome"
    cookies_path: str | None = None


class StudyRequest(BaseModel):
    output_language: OutputLanguage = "zh-CN"
    section: StudySection = "all"


class CourseItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    translated_title: str | None = Field(default=None, max_length=200)
    collection_title: str | None = Field(default=None, max_length=200)
    course_index: float | None = None
    sort_order: float | None = None


class StudyJobStatus(BaseModel):
    job_id: str
    item_id: str
    status: JobStatusValue
    progress: int = Field(ge=0, le=100)
    phase: str
    message: str
    error: str | None = None


class ModelProfileResponse(BaseModel):
    id: str
    name: str
    provider_type: ModelProviderType = "openai"
    base_url: str
    model: str
    context_window: int | None = Field(default=None, ge=1)
    max_tokens: int | None = Field(default=None, ge=1)
    has_api_key: bool
    api_key_preview: str | None = None


class ModelProfileUpdate(BaseModel):
    id: str
    name: str
    provider_type: ModelProviderType = "openai"
    base_url: str
    model: str
    context_window: int | None = Field(default=None, ge=1)
    max_tokens: int | None = Field(default=None, ge=1)
    api_key: str | None = None


class TaskParameterOverride(BaseModel):
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1)


class ModelSettingsResponse(BaseModel):
    profiles: list[ModelProfileResponse]
    translation_model_id: str
    learning_model_id: str
    global_model_id: str
    study_detail_level: StudyDetailLevel = "faithful"
    task_parameters: dict[TaskParameterKey, TaskParameterOverride] = Field(default_factory=dict)


class ModelSettingsUpdate(BaseModel):
    profiles: list[ModelProfileUpdate]
    translation_model_id: str
    learning_model_id: str
    global_model_id: str
    study_detail_level: StudyDetailLevel = "faithful"
    task_parameters: dict[TaskParameterKey, TaskParameterOverride] = Field(default_factory=dict)


class ModelListRequest(BaseModel):
    provider_type: ModelProviderType = "openai"
    base_url: str
    api_key: str | None = None
    profile_id: str | None = None


class ModelListResponse(BaseModel):
    models: list[str]


class DownloadResponse(BaseModel):
    path: str


class VideoMetadata(BaseModel):
    id: str
    title: str
    duration: float | None = None
    playlist_title: str | None = None
    playlist_index: int | None = None
    webpage_url: str
    extractor: str
    stream_url: str | None = None
    hls_manifest_url: str | None = None
    language: str | None = None
    subtitles: list[str] = Field(default_factory=list)
    automatic_captions: list[str] = Field(default_factory=list)


class CourseItem(BaseModel):
    id: str
    source_url: str
    title: str
    custom_title: bool = False
    collection_title: str | None = None
    course_index: float | None = None
    sort_order: float | None = None
    duration: float | None = None
    created_at: str
    transcript: list[TranscriptSegment] = Field(default_factory=list)
    transcript_source: TranscriptSource | None = None
    metadata: VideoMetadata | None = None
    study: "StudyMaterial | None" = None
    local_video_path: Path | None = None


class TimeRange(BaseModel):
    start: float
    end: float
    title: str
    summary: str
    priority: Literal["focus", "skim", "skip", "review"] = "skim"


class OutlineNode(BaseModel):
    id: str
    start: float
    end: float
    title: str
    summary: str
    children: list["OutlineNode"] = Field(default_factory=list)


class StudyMaterial(BaseModel):
    one_line: str
    translated_title: str | None = None
    context_summary: str | None = None
    time_map: list[TimeRange]
    outline: list[OutlineNode]
    detailed_notes: str
    high_fidelity_text: str
    translated_transcript: list[TranscriptSegment] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    thought_prompts: list[str] = Field(default_factory=list)
    review_suggestions: list[str] = Field(default_factory=list)


CourseItem.model_rebuild()
OutlineNode.model_rebuild()
