from __future__ import annotations

import json
import os
from pathlib import Path
from typing import get_args

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from .ai import LlmProvider, LlmProviderSet
from .models import AsrSearchProvider, ModelProviderType, StudyDetailLevel, TaskParameterKey, TaskParameterOverride


class ModelProfileConfig(BaseModel):
    id: str
    name: str
    provider_type: ModelProviderType = "openai"
    base_url: str
    model: str
    context_window: int | None = None
    max_tokens: int | None = None
    api_key: str | None = None


class AsrSearchServiceConfig(BaseModel):
    base_url: str | None = None
    api_key: str | None = None


class AsrSearchSettings(BaseModel):
    enabled: bool = False
    provider: AsrSearchProvider = "tavily"
    result_limit: int = Field(default=5, ge=1, le=10)
    tavily: AsrSearchServiceConfig = Field(
        default_factory=lambda: AsrSearchServiceConfig(base_url="https://api.tavily.com")
    )
    firecrawl: AsrSearchServiceConfig = Field(default_factory=AsrSearchServiceConfig)

    def service_for(self, provider: AsrSearchProvider) -> AsrSearchServiceConfig:
        return self.firecrawl if provider == "firecrawl" else self.tavily


class Settings(BaseModel):
    data_dir: Path = Path(".course-navigator")
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    model_profiles: list[ModelProfileConfig] = Field(default_factory=list)
    translation_model_id: str = "default"
    learning_model_id: str = "default"
    global_model_id: str = "default"
    asr_model_id: str = "default"
    asr_search: AsrSearchSettings = Field(default_factory=AsrSearchSettings)
    study_detail_level: StudyDetailLevel = "faithful"
    task_parameters: dict[TaskParameterKey, TaskParameterOverride] = Field(default_factory=dict)

    @property
    def provider(self) -> LlmProvider | None:
        provider_set = self.provider_set
        return provider_set.learning or provider_set.global_provider or provider_set.translation

    @property
    def provider_set(self) -> LlmProviderSet:
        return LlmProviderSet(
            translation=self.provider_for(self.translation_model_id),
            learning=self.provider_for(self.learning_model_id),
            global_provider=self.provider_for(self.global_model_id),
        )

    def provider_for(self, profile_id: str) -> LlmProvider | None:
        for profile in self.effective_model_profiles:
            if profile.id == profile_id and profile.base_url and profile.model and profile.api_key:
                return LlmProvider(
                    base_url=profile.base_url,
                    api_key=profile.api_key,
                    model=profile.model,
                    provider_type=profile.provider_type,
                    context_window=profile.context_window,
                    max_tokens=profile.max_tokens,
                    task_parameters=self.task_parameters,
                )
        return None

    @property
    def effective_model_profiles(self) -> list[ModelProfileConfig]:
        if self.model_profiles:
            return self.model_profiles
        if not (self.llm_base_url and self.llm_model):
            return []
        return [
            ModelProfileConfig(
                id="default",
                name=_profile_name_from_model(self.llm_model),
                base_url=self.llm_base_url,
                model=self.llm_model,
                api_key=self.llm_api_key,
            )
        ]


def load_settings() -> Settings:
    load_dotenv()
    profiles = _load_model_profiles(os.getenv("COURSE_NAVIGATOR_MODEL_PROFILES"))
    legacy_model = os.getenv("COURSE_NAVIGATOR_LLM_MODEL")
    if not profiles and legacy_model:
        profiles = [
            ModelProfileConfig(
                id="default",
                name=_profile_name_from_model(legacy_model),
                base_url=os.getenv("COURSE_NAVIGATOR_LLM_BASE_URL") or "",
                model=legacy_model,
                api_key=os.getenv("COURSE_NAVIGATOR_LLM_API_KEY"),
            )
        ]
    return Settings(
        data_dir=Path(os.getenv("COURSE_NAVIGATOR_DATA_DIR", ".course-navigator")),
        llm_base_url=os.getenv("COURSE_NAVIGATOR_LLM_BASE_URL"),
        llm_api_key=os.getenv("COURSE_NAVIGATOR_LLM_API_KEY"),
        llm_model=legacy_model,
        model_profiles=profiles,
        translation_model_id=os.getenv("COURSE_NAVIGATOR_TRANSLATION_MODEL_ID", "default"),
        learning_model_id=os.getenv("COURSE_NAVIGATOR_LEARNING_MODEL_ID", "default"),
        global_model_id=os.getenv("COURSE_NAVIGATOR_GLOBAL_MODEL_ID", "default"),
        asr_model_id=os.getenv("COURSE_NAVIGATOR_ASR_MODEL_ID", "default"),
        asr_search=_load_asr_search_settings(),
        study_detail_level=os.getenv("COURSE_NAVIGATOR_STUDY_DETAIL_LEVEL", "faithful"),  # type: ignore[arg-type]
        task_parameters=_load_task_parameters(os.getenv("COURSE_NAVIGATOR_TASK_PARAMETERS")),
    )


def _load_model_profiles(raw: str | None) -> list[ModelProfileConfig]:
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    profiles: list[ModelProfileConfig] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            profiles.append(ModelProfileConfig.model_validate(item))
        except ValueError:
            continue
    return profiles


def _load_task_parameters(raw: str | None) -> dict[TaskParameterKey, TaskParameterOverride]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    valid_keys = set(get_args(TaskParameterKey))
    parameters: dict[TaskParameterKey, TaskParameterOverride] = {}
    for key, value in payload.items():
        if key not in valid_keys or not isinstance(value, dict):
            continue
        try:
            parameters[key] = TaskParameterOverride.model_validate(value)  # type: ignore[literal-required]
        except ValueError:
            continue
    return parameters


def _load_asr_search_settings() -> AsrSearchSettings:
    provider = os.getenv("COURSE_NAVIGATOR_ASR_SEARCH_PROVIDER", "tavily")
    if provider not in get_args(AsrSearchProvider):
        provider = "tavily"
    return AsrSearchSettings(
        enabled=_env_bool("COURSE_NAVIGATOR_ASR_SEARCH_ENABLED", False),
        provider=provider,  # type: ignore[arg-type]
        result_limit=_env_int("COURSE_NAVIGATOR_ASR_SEARCH_RESULT_LIMIT", 5, minimum=1, maximum=10),
        tavily=AsrSearchServiceConfig(
            base_url=os.getenv("COURSE_NAVIGATOR_TAVILY_BASE_URL") or "https://api.tavily.com",
            api_key=os.getenv("COURSE_NAVIGATOR_TAVILY_API_KEY") or os.getenv("TAVILY_API_KEY"),
        ),
        firecrawl=AsrSearchServiceConfig(
            base_url=os.getenv("COURSE_NAVIGATOR_FIRECRAWL_BASE_URL") or os.getenv("FIRECRAWL_API_URL"),
            api_key=os.getenv("COURSE_NAVIGATOR_FIRECRAWL_API_KEY") or os.getenv("FIRECRAWL_API_KEY"),
        ),
    )


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return min(max(value, minimum), maximum)


def _profile_name_from_model(model: str) -> str:
    if model == "deepseek-ai/DeepSeek-V3.2":
        return "DeepSeek V3.2"
    name = model.rsplit("/", 1)[-1].replace("-", " ").replace("_", " ").strip()
    return name or "Default Model"
