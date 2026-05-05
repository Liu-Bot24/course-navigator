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
    "asr_correction",
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


class TranscriptUpdateRequest(BaseModel):
    transcript: list[TranscriptSegment]


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
    started_at: str | None = None
    updated_at: str | None = None


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
    asr_model_id: str = "default"
    study_detail_level: StudyDetailLevel = "faithful"
    task_parameters: dict[TaskParameterKey, TaskParameterOverride] = Field(default_factory=dict)


class ModelSettingsUpdate(BaseModel):
    profiles: list[ModelProfileUpdate]
    translation_model_id: str
    learning_model_id: str
    global_model_id: str
    asr_model_id: str = "default"
    study_detail_level: StudyDetailLevel = "faithful"
    task_parameters: dict[TaskParameterKey, TaskParameterOverride] = Field(default_factory=dict)


AsrCorrectionSource = Literal["model", "search"]
AsrSearchProvider = Literal["tavily", "firecrawl"]


class AsrCorrectionSearchConfig(BaseModel):
    enabled: bool = False
    provider: AsrSearchProvider = "tavily"
    api_key: str | None = None
    base_url: str | None = None
    result_limit: int = Field(default=5, ge=1, le=10)


class AsrSearchServiceSettingsResponse(BaseModel):
    base_url: str | None = None
    has_api_key: bool = False
    api_key_preview: str | None = None


class AsrSearchSettingsResponse(BaseModel):
    enabled: bool = False
    provider: AsrSearchProvider = "tavily"
    result_limit: int = Field(default=5, ge=1, le=10)
    tavily: AsrSearchServiceSettingsResponse = Field(default_factory=AsrSearchServiceSettingsResponse)
    firecrawl: AsrSearchServiceSettingsResponse = Field(default_factory=AsrSearchServiceSettingsResponse)


class AsrSearchServiceSettingsUpdate(BaseModel):
    base_url: str | None = None
    api_key: str | None = None


class AsrSearchSettingsUpdate(BaseModel):
    enabled: bool | None = None
    provider: AsrSearchProvider | None = None
    result_limit: int | None = Field(default=None, ge=1, le=10)
    tavily: AsrSearchServiceSettingsUpdate | None = None
    firecrawl: AsrSearchServiceSettingsUpdate | None = None


class AsrCorrectionRequest(BaseModel):
    output_language: OutputLanguage = "zh-CN"
    transcript: list[TranscriptSegment] | None = None
    model_id: str | None = None
    user_context: str | None = Field(default=None, max_length=8000)
    search: AsrCorrectionSearchConfig = Field(default_factory=AsrCorrectionSearchConfig)


class AsrCorrectionSuggestion(BaseModel):
    id: str
    segment_index: int = Field(ge=0)
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    original_text: str
    corrected_text: str
    confidence: float = Field(ge=0, le=1)
    reason: str
    evidence: str | None = None
    status: Literal["pending", "accepted", "rejected"] = "pending"
    source: AsrCorrectionSource = "model"


class AsrCorrectionResult(BaseModel):
    job_id: str
    item_id: str
    generated_at: str
    search_enabled: bool = False
    search_provider: AsrSearchProvider | None = None
    suggestions: list[AsrCorrectionSuggestion] = Field(default_factory=list)


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
    uploader: str | None = None
    channel: str | None = None
    creator: str | None = None
    description: str | None = None
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
