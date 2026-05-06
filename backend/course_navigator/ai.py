from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Literal

import httpx

from .models import (
    ModelProviderType,
    OutlineNode,
    OutputLanguage,
    StudyDetailLevel,
    StudyMaterial,
    StudySection,
    TaskParameterKey,
    TaskParameterOverride,
    TimeRange,
    TranscriptSegment,
    VideoMetadata,
)


ProgressCallback = Callable[[str, int, str], None]
TranslationProgressCallback = Callable[[list[TranscriptSegment]], None]
PartialStudyCallback = Callable[[StudyMaterial], None]
PartialRangesCallback = Callable[[list[TimeRange]], None]
TitleTranslationCallback = Callable[[str | None], None]
ContextSummaryCallback = Callable[[str], None]

GUIDANCE_LIST_KEYS = (
    "prerequisites",
    "thought_prompts",
    "review_suggestions",
    "beginner_focus",
    "experienced_guidance",
)


@dataclass(frozen=True)
class LlmProvider:
    base_url: str
    api_key: str
    model: str
    provider_type: ModelProviderType = "openai"
    context_window: int | None = None
    max_tokens: int | None = None
    task_parameters: dict[TaskParameterKey, TaskParameterOverride] = field(default_factory=dict)


@dataclass(frozen=True)
class LlmProviderSet:
    translation: LlmProvider | None = None
    learning: LlmProvider | None = None
    global_provider: LlmProvider | None = None


@dataclass(frozen=True)
class StudyGenerationStrategy:
    detail_level: StudyDetailLevel
    target_block_seconds: int
    min_block_seconds: int
    max_block_seconds: int
    block_base_tokens: int
    block_tokens_per_minute: int
    block_max_tokens: int


DETAIL_STRATEGIES: dict[StudyDetailLevel, StudyGenerationStrategy] = {
    "fast": StudyGenerationStrategy(
        detail_level="fast",
        target_block_seconds=420,
        min_block_seconds=150,
        max_block_seconds=540,
        block_base_tokens=1200,
        block_tokens_per_minute=450,
        block_max_tokens=4200,
    ),
    "standard": StudyGenerationStrategy(
        detail_level="standard",
        target_block_seconds=300,
        min_block_seconds=120,
        max_block_seconds=480,
        block_base_tokens=1800,
        block_tokens_per_minute=850,
        block_max_tokens=7200,
    ),
    "detailed": StudyGenerationStrategy(
        detail_level="detailed",
        target_block_seconds=105,
        min_block_seconds=45,
        max_block_seconds=180,
        block_base_tokens=2600,
        block_tokens_per_minute=1300,
        block_max_tokens=12000,
    ),
    "faithful": StudyGenerationStrategy(
        detail_level="faithful",
        target_block_seconds=70,
        min_block_seconds=30,
        max_block_seconds=120,
        block_base_tokens=3600,
        block_tokens_per_minute=1800,
        block_max_tokens=18000,
    ),
}


def generate_study_material(
    title: str,
    transcript: list[TranscriptSegment],
    provider: LlmProvider | LlmProviderSet | None,
    output_language: OutputLanguage = "en",
    detail_level: StudyDetailLevel = "standard",
    progress: ProgressCallback | None = None,
    partial_translation: TranslationProgressCallback | None = None,
    partial_study: PartialStudyCallback | None = None,
    existing_translation: list[TranscriptSegment] | None = None,
    existing_context_summary: str | None = None,
    existing_translated_title: str | None = None,
    source_language: str | None = None,
    metadata: VideoMetadata | None = None,
) -> StudyMaterial:
    _report(progress, "preparing", 1, "正在准备字幕与课程信息")
    if not transcript:
        if output_language == "zh-CN":
            return StudyMaterial(
                one_line=f"{title} 暂时没有可用字幕。",
                translated_title=None,
                time_map=[],
                outline=[],
                detailed_notes="",
                high_fidelity_text="",
            )
        return StudyMaterial(
            one_line=f"No transcript is available for {title} yet.",
            translated_title=None,
            time_map=[],
            outline=[],
            detailed_notes="",
            high_fidelity_text="",
        )

    provider_set = _coerce_provider_set(provider)
    if _first_provider(provider_set.learning, provider_set.global_provider, provider_set.translation):
        try:
            return _generate_with_provider(
                title,
                transcript,
                provider_set,
                output_language,
                detail_level,
                progress,
                partial_translation,
                partial_study,
                existing_translation,
                existing_context_summary,
                existing_translated_title,
                source_language,
                metadata,
            )
        except Exception as exc:
            _report(progress, "fallback", 90, f"模型生成失败，使用本地回退：{type(exc).__name__}")
            return _generate_fallback(title, transcript, output_language)

    _report(progress, "fallback", 70, "未配置模型，使用本地字幕生成学习材料")
    return _generate_fallback(title, transcript, output_language)


def regenerate_study_section(
    title: str,
    transcript: list[TranscriptSegment],
    existing_study: StudyMaterial | None,
    provider: LlmProvider | LlmProviderSet | None,
    output_language: OutputLanguage,
    section: StudySection,
    detail_level: StudyDetailLevel = "standard",
    progress: ProgressCallback | None = None,
    source_language: str | None = None,
    metadata: VideoMetadata | None = None,
) -> StudyMaterial:
    if section == "all" or not existing_study:
        return generate_study_material(
            title=title,
            transcript=transcript,
            provider=provider,
            output_language=output_language,
            detail_level=detail_level,
            progress=progress,
            existing_translation=existing_study.translated_transcript if existing_study else None,
            existing_context_summary=existing_study.context_summary if existing_study else None,
            existing_translated_title=existing_study.translated_title if existing_study else None,
            source_language=source_language,
            metadata=metadata,
        )

    _report(progress, "preparing", 1, f"正在准备重新生成{_section_label(section)}")
    if not transcript:
        return existing_study

    provider_set = _coerce_provider_set(provider)
    global_provider = _first_provider(provider_set.global_provider, provider_set.learning, provider_set.translation)
    learning_provider = _first_provider(provider_set.learning, global_provider, provider_set.translation)
    if not (global_provider and learning_provider):
        generated = _generate_fallback(title, transcript, output_language)
        merged = _merge_study_section(existing_study, generated, section)
        _report(progress, "complete", 95, f"{_section_label(section)}已重新生成")
        return merged

    context_summary = existing_study.context_summary
    if context_summary:
        _report(progress, "summary", 8, "已复用课程上下文摘要")
    else:
        _report(progress, "summary", 8, "正在生成上下文摘要")
        context_summary = _generate_translation_context(title, transcript, global_provider, output_language, metadata)

    next_study = existing_study.model_copy(deep=True)
    next_study.context_summary = context_summary
    prompt_context_summary = _context_summary_with_metadata(context_summary, metadata)

    if section == "guide":
        _report(progress, "guide", 35, "正在重新生成导览")
        guidance = _generate_guidance_with_provider(
            title,
            transcript,
            prompt_context_summary,
            global_provider,
            output_language,
        )
        if guidance:
            next_study.one_line = str(guidance.get("one_line") or next_study.one_line).strip() or next_study.one_line
            next_study.prerequisites = guidance.get("prerequisites", next_study.prerequisites)
            next_study.thought_prompts = guidance.get("thought_prompts", next_study.thought_prompts)
            next_study.review_suggestions = guidance.get("review_suggestions", next_study.review_suggestions)
            next_study.beginner_focus = guidance.get("beginner_focus", next_study.beginner_focus)
            next_study.experienced_guidance = guidance.get("experienced_guidance", next_study.experienced_guidance)
        if next_study.time_map and not guidance.get("one_line"):
            next_study.one_line = _one_line_from_context(
                title,
                _blocks_from_time_map(next_study.time_map),
                output_language,
                prompt_context_summary,
            )
        _report(progress, "complete", 95, "导览已重新生成")
        return next_study

    blocks = _blocks_from_existing_study(next_study)

    if section == "outline":
        _report(progress, "outline", 45, "正在重新生成大纲")
        next_study.outline = _generate_outline_with_provider(
            title,
            blocks,
            prompt_context_summary,
            global_provider,
            output_language,
        )
        _report(progress, "complete", 95, "大纲已重新生成")
        return next_study

    _report(progress, section, 20, f"正在重新生成{_section_label(section)}")
    if section == "detailed" and next_study.time_map:
        learning_blocks = _generate_interpretation_blocks_for_existing_ranges_with_provider(
            title=title,
            source_transcript=transcript,
            translated_transcript=next_study.translated_transcript,
            ranges=next_study.time_map,
            existing_study=next_study,
            context_summary=prompt_context_summary,
            provider=learning_provider,
            output_language=output_language,
            detail_level=detail_level,
            progress=progress,
        )
        next_study.detailed_notes = _detailed_notes_from_blocks(learning_blocks)
        _report(progress, "complete", 95, "解读已重新生成")
        return next_study
    if section == "high" and next_study.time_map and next_study.detailed_notes.strip():
        learning_blocks = _generate_high_fidelity_blocks_for_existing_ranges_with_provider(
            title=title,
            source_transcript=transcript,
            translated_transcript=next_study.translated_transcript,
            ranges=next_study.time_map,
            existing_study=next_study,
            context_summary=prompt_context_summary,
            provider=learning_provider,
            output_language=output_language,
            detail_level=detail_level,
            progress=progress,
        )
        next_study.high_fidelity_text = _high_fidelity_text_from_blocks(learning_blocks)
        _report(progress, "complete", 95, "详解已重新生成")
        return next_study

    learning_blocks = _generate_learning_blocks_for_ranges_with_provider(
        title=title,
        source_transcript=transcript,
        translated_transcript=next_study.translated_transcript,
        ranges=next_study.time_map,
        context_summary=prompt_context_summary,
        provider=learning_provider,
        output_language=output_language,
        detail_level=detail_level,
        progress=progress,
    )
    if section == "detailed":
        next_study.detailed_notes = _detailed_notes_from_blocks(learning_blocks)
        _report(progress, "complete", 95, "解读已重新生成")
    elif section == "high":
        next_study.high_fidelity_text = _high_fidelity_text_from_blocks(learning_blocks)
        _report(progress, "complete", 95, "详解已重新生成")
    return next_study


def _coerce_provider_set(provider: LlmProvider | LlmProviderSet | None) -> LlmProviderSet:
    if isinstance(provider, LlmProviderSet):
        return provider
    if isinstance(provider, LlmProvider):
        return LlmProviderSet(
            translation=provider,
            learning=provider,
            global_provider=provider,
        )
    return LlmProviderSet()


def _first_provider(*providers: LlmProvider | None) -> LlmProvider | None:
    for provider in providers:
        if provider and provider.base_url and provider.model and provider.api_key:
            return provider
    return None


def _chat_json(
    provider: LlmProvider,
    messages: list[dict[str, str]],
    *,
    temperature: float,
    max_tokens: int,
    timeout: float,
    task_key: TaskParameterKey | None = None,
) -> object:
    content = _chat_text(
        provider,
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        task_key=task_key,
    )
    return _loads_json_content(content)


def _chat_text(
    provider: LlmProvider,
    messages: list[dict[str, str]],
    *,
    temperature: float,
    max_tokens: int,
    timeout: float,
    task_key: TaskParameterKey | None = None,
) -> str:
    base_url = provider.base_url.rstrip("/")
    effective_temperature, effective_max_tokens = _effective_task_parameters(
        provider,
        task_key=task_key,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if provider.provider_type == "anthropic":
        system = "\n\n".join(message["content"] for message in messages if message["role"] == "system")
        anthropic_messages = [
            {
                "role": "assistant" if message["role"] == "assistant" else "user",
                "content": message["content"],
            }
            for message in messages
            if message["role"] != "system"
        ]
        response = httpx.post(
            _anthropic_endpoint_url(base_url, "messages"),
            headers={
                "x-api-key": provider.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": provider.model,
                "system": system or None,
                "messages": anthropic_messages,
                "temperature": effective_temperature,
                "max_tokens": effective_max_tokens,
            },
            timeout=timeout,
        )
        response.raise_for_status()
        parts = response.json().get("content") or []
        if isinstance(parts, list):
            return "".join(
                part.get("text", "")
                for part in parts
                if isinstance(part, dict) and part.get("type") in {None, "text"}
            )
        return ""

    response = httpx.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {provider.api_key}"},
        json={
            "model": provider.model,
            "messages": messages,
            "temperature": effective_temperature,
            "max_tokens": effective_max_tokens,
            "response_format": {"type": "json_object"},
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return str(response.json()["choices"][0]["message"]["content"])


def _effective_task_parameters(
    provider: LlmProvider,
    *,
    task_key: TaskParameterKey | None,
    temperature: float,
    max_tokens: int,
) -> tuple[float, int]:
    task_parameters = provider.task_parameters.get(task_key) if task_key else None
    effective_temperature = (
        task_parameters.temperature
        if task_parameters and task_parameters.temperature is not None
        else temperature
    )
    effective_max_tokens = (
        task_parameters.max_tokens
        if task_parameters and task_parameters.max_tokens is not None
        else max_tokens
    )
    if provider.max_tokens:
        effective_max_tokens = min(effective_max_tokens, provider.max_tokens)
    return effective_temperature, effective_max_tokens


def _anthropic_endpoint_url(base_url: str, endpoint: str) -> str:
    base = base_url.strip().rstrip("/")
    if base.endswith(f"/{endpoint}"):
        return base
    if base.endswith("/v1"):
        return f"{base}/{endpoint}"
    if re.search(r"api\.anthropic\.com$", base) or re.search(r"api\.minimaxi\.com/anthropic$", base):
        return f"{base}/v1/{endpoint}"
    return f"{base}/{endpoint}"


def _ordered_translated_chunks(
    source_chunks: list[list[TranscriptSegment]],
    translated_by_index: dict[int, list[TranscriptSegment]],
) -> list[TranscriptSegment]:
    translated: list[TranscriptSegment] = []
    for index, source_chunk in enumerate(source_chunks):
        chunk = translated_by_index.get(index)
        if not chunk:
            continue
        translated.extend(_align_translated_chunk(source_chunk, chunk))
    return translated


def _align_translated_chunk(
    source_chunk: list[TranscriptSegment],
    translated_chunk: list[TranscriptSegment],
) -> list[TranscriptSegment]:
    if len(translated_chunk) == len(source_chunk):
        return [
            TranscriptSegment(
                start=source.start,
                end=source.end,
                text=(translated.text or source.text).strip(),
            )
            for source, translated in zip(source_chunk, translated_chunk)
        ]

    by_start = {round(segment.start, 2): segment for segment in translated_chunk}
    aligned: list[TranscriptSegment] = []
    for source in source_chunk:
        translated = by_start.get(round(source.start, 2))
        aligned.append(
            TranscriptSegment(
                start=source.start,
                end=source.end,
                text=(translated.text if translated else source.text).strip(),
            )
        )
    return aligned


def _generate_fallback(
    title: str,
    transcript: list[TranscriptSegment],
    output_language: OutputLanguage,
) -> StudyMaterial:
    chunks = _chunk_segments(transcript, target_size=8)
    chinese = output_language == "zh-CN"
    japanese = output_language == "ja"
    time_map = [
        TimeRange(
            start=chunk[0].start,
            end=chunk[-1].end,
            title=(
                f"第 {index + 1} 段：{_first_words(chunk[0].text, 7)}"
                if chinese
                else f"セクション {index + 1}: {_first_words(chunk[0].text, 7)}"
                if japanese
                else f"Block {index + 1}: {_first_words(chunk[0].text, 7)}"
            ),
            summary=" ".join(segment.text for segment in chunk[:2]),
            priority="focus" if index == 0 else "skim",
        )
        for index, chunk in enumerate(chunks)
    ]
    outline = [
        OutlineNode(
            id=f"block-{index + 1}",
            start=chunk[0].start,
            end=chunk[-1].end,
            title=time_map[index].title,
            summary=time_map[index].summary,
            children=[
                OutlineNode(
                    id=f"block-{index + 1}-seg-{child_index + 1}",
                    start=segment.start,
                    end=segment.end,
                    title=_first_words(segment.text, 10),
                    summary=segment.text,
                    children=[],
                )
                for child_index, segment in enumerate(chunk)
            ],
        )
        for index, chunk in enumerate(chunks)
    ]
    detailed_notes = "\n\n".join(
        f"{_format_time(block.start)}-{_format_time(block.end)} {block.title}\n{block.summary}"
        for block in time_map
    )
    high_fidelity_lines = "\n".join(
        f"[{_format_time(segment.start)}-{_format_time(segment.end)}] {segment.text}"
        for segment in transcript
    )
    high_fidelity_text = (
        (
            "未配置模型，以下保留原始字幕逐句稿；配置模型后会生成中文详解学习稿。\n"
            + high_fidelity_lines
        )
        if chinese
        else (
            "モデルが未設定です。以下は元字幕を保持した逐語稿です。\n" + high_fidelity_lines
        )
        if japanese
        else high_fidelity_lines
    )

    return StudyMaterial(
        one_line=(
            f"{title} 包含 {len(transcript)} 条字幕片段，分成 {len(chunks)} 个学习块。"
            if chinese
            else f"{title} は {len(transcript)} 件の字幕セグメントを {len(chunks)} 個の学習ブロックに分けています。"
            if japanese
            else f"{title} covers {len(transcript)} transcript segments across {len(chunks)} blocks."
        ),
        time_map=time_map,
        outline=outline,
        detailed_notes=detailed_notes,
        high_fidelity_text=high_fidelity_text,
        prerequisites=[],
        thought_prompts=(
            [
                "快速思考：哪些部分对你来说足够新，值得重点观看？",
                "哪些想法可以直接迁移到你当前的工作场景？",
                "深入观看前，哪些术语最好先查清楚？",
            ]
            if chinese
            else [
                "どの部分が自分にとって新しく、重点的に見る価値がありますか？",
                "現在の仕事に直接応用できる考え方はどれですか？",
                "深く見る前に確認しておくべき用語はありますか？",
            ]
            if japanese
            else [
                "Which parts are new enough to deserve focused watching?",
                "Which ideas can be transferred directly into current work?",
                "Which terms should be checked before watching deeply?",
            ]
        ),
        review_suggestions=(
            [
                "先扫 Time Map，再只展开你判断需要重点看的片段。",
                "看完后，回到最难的一段附近阅读详解文本。",
            ]
            if chinese
            else [
                "まず Time Map をざっと見て、重点的に見るべきブロックだけ開いてください。",
                "視聴後、最も難しかった箇所の周辺で細粒度テキストを読み直してください。",
            ]
            if japanese
            else [
                "Skim the time map first, then expand only the blocks marked focus.",
                "After watching, revisit the high-fidelity text around the hardest segment.",
            ]
        ),
    )


def _generate_with_provider(
    title: str,
    transcript: list[TranscriptSegment],
    provider_set: LlmProviderSet,
    output_language: OutputLanguage,
    detail_level: StudyDetailLevel,
    progress: ProgressCallback | None = None,
    partial_translation: TranslationProgressCallback | None = None,
    partial_study: PartialStudyCallback | None = None,
    existing_translation: list[TranscriptSegment] | None = None,
    existing_context_summary: str | None = None,
    existing_translated_title: str | None = None,
    source_language: str | None = None,
    metadata: VideoMetadata | None = None,
) -> StudyMaterial:
    return _generate_long_translated_with_provider(
        title,
        transcript,
        provider_set,
        output_language,
        detail_level,
        progress,
        partial_translation,
        partial_study,
        existing_translation,
        existing_context_summary,
        existing_translated_title,
        source_language,
        metadata,
    )


def _generate_long_translated_with_provider(
    title: str,
    transcript: list[TranscriptSegment],
    provider_set: LlmProviderSet,
    output_language: OutputLanguage,
    detail_level: StudyDetailLevel,
    progress: ProgressCallback | None = None,
    partial_translation: TranslationProgressCallback | None = None,
    partial_study: PartialStudyCallback | None = None,
    existing_translation: list[TranscriptSegment] | None = None,
    existing_context_summary: str | None = None,
    existing_translated_title: str | None = None,
    source_language: str | None = None,
    metadata: VideoMetadata | None = None,
) -> StudyMaterial:
    context_provider = _first_provider(provider_set.global_provider, provider_set.translation, provider_set.learning)
    translation_provider = _first_provider(provider_set.translation, context_provider)
    learning_provider = _first_provider(provider_set.learning, context_provider, translation_provider)
    global_provider = _first_provider(provider_set.global_provider, learning_provider, translation_provider)
    if not (context_provider and translation_provider and learning_provider and global_provider):
        return _generate_fallback(title, transcript, output_language)

    if existing_context_summary:
        _report(progress, "summary", 8, "已复用课程上下文摘要")
        context_summary = existing_context_summary
    else:
        _report(progress, "summary", 8, "正在生成课程上下文摘要")
        context_summary = _generate_translation_context(title, transcript, context_provider, output_language, metadata)
    prompt_context_summary = _context_summary_with_metadata(context_summary, metadata)
    should_translate = _should_translate_transcript(source_language, output_language) and not _transcript_matches_output_language(
        transcript,
        output_language,
    )
    translated_title = existing_translated_title or (
        _translate_title_with_provider(title, context_summary, translation_provider, output_language)
        if should_translate
        else None
    )
    _report(progress, "guide", 12, "正在生成学习导览")
    try:
        guidance = _generate_guidance_with_provider(
            title,
            transcript,
            prompt_context_summary,
            global_provider,
            output_language,
        )
    except Exception:
        guidance = {}
    if partial_study:
        guide_study = StudyMaterial(
            one_line=str(guidance.get("one_line") or _partial_one_line_from_context(title, output_language, context_summary)).strip(),
            translated_title=translated_title,
            context_summary=context_summary,
            time_map=[],
            outline=[],
            detailed_notes="",
            high_fidelity_text="",
            translated_transcript=[],
            prerequisites=guidance.get("prerequisites", []) if guidance else [],
            thought_prompts=guidance.get("thought_prompts", []) if guidance else [],
            review_suggestions=guidance.get("review_suggestions", []) if guidance else [],
            beginner_focus=guidance.get("beginner_focus", []) if guidance else [],
            experienced_guidance=guidance.get("experienced_guidance", []) if guidance else [],
        )
        _send_partial_study(partial_study, guide_study)
    if not should_translate:
        translated = [
            TranscriptSegment(start=segment.start, end=segment.end, text=segment.text)
            for segment in transcript
        ]
        if partial_translation:
            partial_translation(translated)
        _report(progress, "translation", 73, "源语言与输出语言一致，已复用原始字幕")
    elif existing_translation and len(existing_translation) == len(transcript):
        _report(progress, "translation", 70, "正在校验现有字幕译文")
        translated = _repair_untranslated_segments(
            title=title,
            source_transcript=transcript,
            translated_transcript=existing_translation,
            provider=translation_provider,
            context_summary=context_summary,
            output_language=output_language,
            progress=progress,
            partial_translation=partial_translation,
        )
        if _translation_repair_indices(transcript, translated, output_language):
            _report(progress, "translation", 73, "现有字幕译文不完整，正在重新翻译")
            translated = _translate_transcript_with_provider(
                title=title,
                transcript=transcript,
                provider=translation_provider,
                context_summary=context_summary,
                output_language=output_language,
                progress=progress,
                partial_translation=partial_translation,
            )
        else:
            _report(progress, "translation", 73, "已复用现有字幕译文")
    else:
        _report(progress, "translation", 15, "正在按字幕片段翻译")
        translated = _translate_transcript_with_provider(
            title=title,
            transcript=transcript,
            provider=translation_provider,
            context_summary=context_summary,
            output_language=output_language,
            progress=progress,
            partial_translation=partial_translation,
        )
    _report(progress, "segmentation", 74, "正在进行语义分块")
    def save_partial_ranges(ranges: list[TimeRange]) -> None:
        if not partial_study:
            return
        range_blocks = [_block_from_time_range(index, time_range) for index, time_range in enumerate(ranges)]
        range_study = StudyMaterial(
            one_line=str(guidance.get("one_line") or _one_line_from_context(title, range_blocks, output_language, context_summary)).strip(),
            translated_title=translated_title,
            context_summary=context_summary,
            time_map=[time_range.model_copy(deep=True) for time_range in ranges],
            outline=_outline_from_blocks(range_blocks),
            detailed_notes="",
            high_fidelity_text="",
            translated_transcript=translated,
            prerequisites=guidance.get("prerequisites", []) if guidance else [],
            thought_prompts=guidance.get("thought_prompts", []) if guidance else [],
            review_suggestions=guidance.get("review_suggestions", []) if guidance else [],
            beginner_focus=guidance.get("beginner_focus", []) if guidance else [],
            experienced_guidance=guidance.get("experienced_guidance", []) if guidance else [],
        )
        _send_partial_study(partial_study, range_study)

    blocks = _generate_learning_blocks_with_provider(
        title=title,
        source_transcript=transcript,
        translated_transcript=translated,
        context_summary=prompt_context_summary,
        provider=learning_provider,
        segmentation_provider=global_provider,
        output_language=output_language,
        detail_level=detail_level,
        progress=progress,
        partial_ranges=save_partial_ranges,
    )
    _report(progress, "outline", 90, "正在生成课程大纲")
    study = _assemble_study_from_blocks(
        title=title,
        blocks=blocks,
        output_language=output_language,
        context_summary=context_summary,
    )
    study.translated_transcript = translated
    study.translated_title = translated_title
    study.context_summary = context_summary
    if guidance:
        study.one_line = str(guidance.get("one_line") or study.one_line).strip() or study.one_line
        study.prerequisites = guidance.get("prerequisites", study.prerequisites)
        study.thought_prompts = guidance.get("thought_prompts", study.thought_prompts)
        study.review_suggestions = guidance.get("review_suggestions", study.review_suggestions)
        study.beginner_focus = guidance.get("beginner_focus", study.beginner_focus)
        study.experienced_guidance = guidance.get("experienced_guidance", study.experienced_guidance)
    _send_partial_study(partial_study, study)
    try:
        study.outline = _generate_outline_with_provider(title, blocks, prompt_context_summary, global_provider, output_language)
    except Exception:
        study.outline = _outline_from_blocks(blocks)
    _send_partial_study(partial_study, study)
    _report(progress, "assembly", 96, "正在组装时间地图、解读和详解文本")
    return study


def translate_transcript_material(
    title: str,
    transcript: list[TranscriptSegment],
    provider: LlmProvider | LlmProviderSet | None,
    output_language: OutputLanguage,
    progress: ProgressCallback | None = None,
    partial_translation: TranslationProgressCallback | None = None,
    title_translation: TitleTranslationCallback | None = None,
    context_summary_created: ContextSummaryCallback | None = None,
    source_language: str | None = None,
    metadata: VideoMetadata | None = None,
) -> list[TranscriptSegment]:
    if not transcript:
        return []
    if not _should_translate_transcript(source_language, output_language) or _transcript_matches_output_language(
        transcript,
        output_language,
    ):
        title_translation and title_translation(None)
        translated = [
            TranscriptSegment(start=segment.start, end=segment.end, text=segment.text)
            for segment in transcript
        ]
        partial_translation and partial_translation(translated)
        return translated
    provider_set = _coerce_provider_set(provider)
    context_provider = _first_provider(provider_set.global_provider, provider_set.translation, provider_set.learning)
    translation_provider = _first_provider(provider_set.translation, context_provider)
    if not (context_provider and translation_provider):
        raise ValueError("未配置可用的翻译模型")
    _report(progress, "summary", 8, "正在生成课程上下文摘要")
    context_summary = _generate_translation_context(title, transcript, context_provider, output_language, metadata)
    context_summary_created and context_summary_created(context_summary)
    translated_title = _translate_title_with_provider(title, context_summary, translation_provider, output_language)
    if translated_title:
        title_translation and title_translation(translated_title)
    _report(progress, "translation", 15, "正在按字幕片段翻译")
    return _translate_transcript_with_provider(
        title=title,
        transcript=transcript,
        provider=translation_provider,
        context_summary=context_summary,
        output_language=output_language,
        progress=progress,
        partial_translation=partial_translation,
    )


def _translate_title_with_provider(
    title: str,
    context_summary: str,
    provider: LlmProvider,
    output_language: OutputLanguage,
) -> str | None:
    target_language = _target_language_name(output_language)
    try:
        payload = _chat_json(
            provider,
            [
                {
                    "role": "system",
                    "content": (
                        f"Translate the course/video title into natural {target_language}. "
                        "Preserve brand names, product names, and version markers. "
                        "Return strict JSON only: {\"translated_title\": string}. "
                        "Do not add explanations."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Title: {title}\nCourse context: {context_summary}",
                },
            ],
            temperature=0.1,
            max_tokens=300,
            timeout=60,
            task_key="title_translation",
        )
        if isinstance(payload, dict) and isinstance(payload.get("translated_title"), str):
            translated = payload["translated_title"].strip()
            return translated if translated and translated != title else None
    except Exception:
        return None
    return None


def _translate_transcript_with_provider(
    title: str,
    transcript: list[TranscriptSegment],
    provider: LlmProvider,
    context_summary: str,
    output_language: OutputLanguage,
    progress: ProgressCallback | None = None,
    partial_translation: TranslationProgressCallback | None = None,
) -> list[TranscriptSegment]:
    chunks = _chunk_segments(transcript, target_size=_translation_chunk_size(provider))
    translated_by_index: dict[int, list[TranscriptSegment]] = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(
                _translate_chunk_with_provider,
                title,
                chunk,
                provider,
                context_summary,
                output_language,
            ): index
            for index, chunk in enumerate(chunks)
        }
        completed = 0
        for future in as_completed(futures):
            index = futures[future]
            source_chunk = chunks[index]
            try:
                translated_by_index[index] = future.result()
            except Exception:
                translated_by_index[index] = [
                    TranscriptSegment(start=source.start, end=source.end, text=source.text)
                    for source in source_chunk
                ]
            completed += 1
            progress_value = 15 + round((completed / max(len(chunks), 1)) * 58)
            _report(
                progress,
                "translation",
                progress_value,
                f"正在翻译字幕片段 {completed}/{len(chunks)}",
            )
            if partial_translation:
                partial_translation(_ordered_translated_chunks(chunks, translated_by_index))
    translated = _ordered_translated_chunks(chunks, translated_by_index)
    translated = _repair_untranslated_segments(
        title=title,
        source_transcript=transcript,
        translated_transcript=translated,
        provider=provider,
        context_summary=context_summary,
        output_language=output_language,
        progress=progress,
        partial_translation=partial_translation,
    )
    _ensure_translation_complete(transcript, translated, output_language)
    if partial_translation:
        partial_translation(translated)
    return translated


def _repair_untranslated_segments(
    title: str,
    source_transcript: list[TranscriptSegment],
    translated_transcript: list[TranscriptSegment],
    provider: LlmProvider,
    context_summary: str,
    output_language: OutputLanguage,
    progress: ProgressCallback | None = None,
    partial_translation: TranslationProgressCallback | None = None,
) -> list[TranscriptSegment]:
    if output_language == "en":
        return translated_transcript
    repaired = _align_translated_chunk(source_transcript, translated_transcript)
    for attempt in range(2):
        missing_indices = [
            index
            for index, (source, translated) in enumerate(zip(source_transcript, repaired))
            if _needs_translation_repair(source, translated, output_language=output_language)
        ]
        if not missing_indices:
            return repaired
        _report(
            progress,
            "translation_repair",
            min(88, 74 + attempt * 7),
            f"正在补译漏翻字幕 {len(missing_indices)} 条",
        )
        for indexed_chunk in _chunk_indices(missing_indices, target_size=8):
            source_chunk = [source_transcript[index] for index in indexed_chunk]
            try:
                translated_chunk = _translate_chunk_with_provider(
                    title,
                    source_chunk,
                    provider,
                    context_summary,
                    output_language,
                )
            except Exception:
                continue
            aligned = _align_translated_chunk(source_chunk, translated_chunk)
            for index, translated_segment in zip(indexed_chunk, aligned):
                if not _needs_translation_repair(source_transcript[index], translated_segment, output_language=output_language):
                    repaired[index] = translated_segment
            if partial_translation:
                partial_translation(repaired)
    return repaired


def _translation_repair_indices(
    source_transcript: list[TranscriptSegment],
    translated_transcript: list[TranscriptSegment],
    output_language: OutputLanguage,
) -> list[int]:
    aligned = _align_translated_chunk(source_transcript, translated_transcript)
    return [
        index
        for index, (source, translated) in enumerate(zip(source_transcript, aligned))
        if _needs_translation_repair(source, translated, output_language=output_language)
    ]


def _ensure_translation_complete(
    source_transcript: list[TranscriptSegment],
    translated_transcript: list[TranscriptSegment],
    output_language: OutputLanguage,
) -> None:
    missing_indices = _translation_repair_indices(source_transcript, translated_transcript, output_language)
    if missing_indices:
        raise RuntimeError(f"字幕翻译不完整，仍有 {len(missing_indices)} 条漏翻，请重试或更换翻译模型。")


def _needs_translation_repair(
    source: TranscriptSegment,
    translated: TranscriptSegment | None,
    output_language: OutputLanguage,
) -> bool:
    if not translated or not translated.text.strip():
        return True
    source_text = _normalize_translation_compare(source.text)
    translated_text = _normalize_translation_compare(translated.text)
    if not source_text or source_text != translated_text:
        return False
    if len(source_text) > 12:
        return True
    if output_language == "en":
        return False
    return _looks_like_short_latin_text(source.text)


def _normalize_translation_compare(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _should_translate_transcript(source_language: str | None, output_language: OutputLanguage) -> bool:
    if _source_language_matches_output(source_language, output_language):
        return False
    return True


def _source_language_matches_output(source_language: str | None, output_language: OutputLanguage) -> bool:
    source = _normalize_language_code(source_language)
    if not source:
        return False
    target = _normalize_language_code(output_language)
    return source == target


def _transcript_matches_output_language(
    transcript: list[TranscriptSegment],
    output_language: OutputLanguage,
) -> bool:
    target = _normalize_language_code(output_language)
    if not transcript or target not in {"zh", "ja", "en"}:
        return False
    sample = " ".join(segment.text for segment in transcript[:120])
    if target == "zh":
        cjk_count = len(re.findall(r"[\u4e00-\u9fff]", sample))
        latin_count = len(re.findall(r"[A-Za-z]", sample))
        return cjk_count >= 12 and cjk_count >= latin_count
    if target == "ja":
        kana_count = len(re.findall(r"[\u3040-\u30ff]", sample))
        cjk_count = len(re.findall(r"[\u4e00-\u9fff]", sample))
        return kana_count >= 8 or kana_count + cjk_count >= 16
    latin_words = len(re.findall(r"[A-Za-z][A-Za-z']+", sample))
    cjk_count = len(re.findall(r"[\u3040-\u30ff\u4e00-\u9fff]", sample))
    return latin_words >= 20 and cjk_count < 8


def _normalize_language_code(language: str | None) -> str:
    if not language:
        return ""
    normalized = language.strip().lower().replace("_", "-")
    if not normalized or normalized == "auto":
        return ""
    if normalized.startswith("zh"):
        return "zh"
    if normalized.startswith("ja") or normalized.startswith("jp"):
        return "ja"
    if normalized.startswith("en"):
        return "en"
    return normalized.split("-", 1)[0]


def _looks_like_short_latin_text(value: str) -> bool:
    tokens = re.findall(r"[A-Za-z][A-Za-z']*", value)
    if not tokens:
        return False
    ignored = {
        "ai",
        "api",
        "asr",
        "gpt",
        "llm",
        "rag",
        "url",
        "chatgpt",
        "gemini",
        "claude",
        "youtube",
        "deeplearning",
        "deeplearningai",
    }
    for token in tokens:
        normalized = token.lower().replace("'", "")
        if normalized in ignored:
            continue
        if token.isupper() and len(token) <= 6:
            continue
        return True
    return False


def _chunk_indices(indices: list[int], target_size: int) -> list[list[int]]:
    chunks: list[list[int]] = []
    current: list[int] = []
    previous: int | None = None
    for index in indices:
        if current and (len(current) >= target_size or previous is not None and index != previous + 1):
            chunks.append(current)
            current = []
        current.append(index)
        previous = index
    if current:
        chunks.append(current)
    return chunks


def _translation_chunk_size(provider: LlmProvider) -> int:
    window = provider.context_window or 0
    if window and window < 16000:
        return 12
    if window and window < 64000:
        return 20
    if window >= 256000:
        return 48
    return 30


def _translate_chunk_with_provider(
    title: str,
    chunk: list[TranscriptSegment],
    provider: LlmProvider,
    context_summary: str,
    output_language: OutputLanguage,
) -> list[TranscriptSegment]:
    target_language = _target_language_name(output_language)
    payload = _chat_json(
        provider,
        [
            {
                "role": "system",
                "content": (
                    f"Translate video transcript segments into natural {target_language}. "
                    "Use the course title, course summary, and context reference as background "
                    "context for term consistency. "
                    "Return strict JSON only: {\"translated_transcript\":[{\"start\":number,\"end\":number,\"text\":string}]}. "
                    "Preserve the segment count, order, start, and end values exactly. Do not summarize."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Title: {title}\n"
                    f"Course summary: {context_summary}\n\n"
                    "Context reference: These lines are one continuous subtitle slice from the same "
                    "course. Keep terminology and pronoun references consistent across this slice; "
                    "do not add facts not supported by the lines.\n\n"
                    "Segments:\n"
                    + "\n".join(
                        f"[{segment.start:.2f}-{segment.end:.2f}] {segment.text}"
                        for segment in chunk
                    )
                ),
            },
        ],
        temperature=0.1,
        max_tokens=6000,
        timeout=180,
        task_key="subtitle_translation",
    )
    if not isinstance(payload, dict):
        raise TypeError("Translation payload must be a JSON object")
    segments = [
        TranscriptSegment.model_validate(segment)
        for segment in _ensure_list(payload.get("translated_transcript"))
        if isinstance(segment, dict)
    ]
    return segments


def _generate_translation_context(
    title: str,
    transcript: list[TranscriptSegment],
    provider: LlmProvider,
    output_language: OutputLanguage,
    metadata: VideoMetadata | None = None,
) -> str:
    transcript_text = _full_transcript_for_prompt(transcript)
    metadata_reference = _metadata_prompt_reference(metadata)
    payload = _chat_json(
        provider,
        [
            {
                "role": "system",
                "content": (
                    "Create a concise context summary for a course transcript. "
                    "Return strict JSON only: {\"summary\": string}. Include the topic, speaker/course type, "
                    "source identity, uploader/channel when provided, author-provided course description when useful, "
                    "and important terms. Use trusted video metadata only for source identity and course background; "
                    "use transcript lines for course claims. Do not invent facts outside the provided inputs."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Title: {title}\n"
                    f"{metadata_reference}"
                    f"Full transcript:\n{transcript_text}"
                ),
            },
        ],
        temperature=0.1,
        max_tokens=1000,
        timeout=90,
    )
    if isinstance(payload, dict) and isinstance(payload.get("summary"), str):
        return payload["summary"]
    return title


def _generate_guidance_with_provider(
    title: str,
    transcript: list[TranscriptSegment],
    context_summary: str,
    provider: LlmProvider,
    output_language: OutputLanguage,
) -> dict[str, object]:
    transcript_text = _full_transcript_for_prompt(transcript)
    target_language = _target_language_name(output_language)
    payload = _chat_json(
        provider,
        [
            {
                "role": "system",
                "content": (
                    f"Output concise {target_language} study guidance for a busy working professional. "
                    "Use transcript-derived content for course claims, and use your domain judgment to judge "
                    "what different learner levels should focus on or skip. Do not turn the guidance into a "
                    "timestamped navigation map. Return strict JSON only with one string field and five arrays: "
                    "one_line, prerequisites, thought_prompts, review_suggestions, beginner_focus, and "
                    "experienced_guidance. one_line must be a meaningful one-sentence course overview in the "
                    "target language; do not make it a block-count status line. Keep each item short. In beginner_focus, advise new learners which "
                    "concepts, explanations, or examples deserve focused listening. In experienced_guidance, "
                    "advise learners with foundations or practice which basic parts can likely be skimmed or "
                    "skipped, and which ideas are still worth reviewing; if the whole course is too basic, say so "
                    "plainly while naming any rare points still worth knowing."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Title: {title}\n"
                    f"Summary: {context_summary}\n"
                    f"Full transcript:\n{transcript_text}"
                ),
            },
        ],
        temperature=0.25,
        max_tokens=1600,
        timeout=120,
        task_key="guide",
    )
    if not isinstance(payload, dict):
        return {}
    result: dict[str, object] = {}
    one_line = str(payload.get("one_line") or "").strip()
    if one_line:
        result["one_line"] = one_line
    for key in GUIDANCE_LIST_KEYS:
        result[key] = [str(item) for item in _ensure_list(payload.get(key)) if str(item).strip()]
    return result


def _study_strategy(detail_level: StudyDetailLevel) -> StudyGenerationStrategy:
    return DETAIL_STRATEGIES.get(detail_level, DETAIL_STRATEGIES["standard"])


def _learning_temperature(detail_level: StudyDetailLevel) -> float:
    return {
        "fast": 0.25,
        "standard": 0.3,
        "detailed": 0.35,
        "faithful": 0.35,
    }.get(detail_level, 0.3)


def _semantic_soft_block_limit(duration_seconds: float, strategy: StudyGenerationStrategy) -> int | None:
    if strategy.detail_level == "faithful":
        return None
    target_blocks = max(1, round(duration_seconds / max(strategy.target_block_seconds, 1)))
    duration_minutes = duration_seconds / 60
    if duration_minutes >= 120:
        return max(target_blocks + 8, round(target_blocks * 1.45))
    if duration_minutes >= 60:
        return max(target_blocks + 5, round(target_blocks * 1.35))
    return max(target_blocks + 3, round(target_blocks * 1.25))


def _generate_semantic_ranges_with_provider(
    title: str,
    transcript: list[TranscriptSegment],
    context_summary: str,
    provider: LlmProvider,
    output_language: OutputLanguage,
    strategy: StudyGenerationStrategy,
) -> list[TimeRange]:
    transcript_text = _full_transcript_for_prompt(transcript)
    estimated_input_tokens = _estimate_text_tokens(transcript_text) + _estimate_text_tokens(context_summary) + 800
    if provider.context_window and estimated_input_tokens > int(provider.context_window * 0.72):
        raise ValueError("Transcript exceeds the configured semantic segmentation budget")

    target_language = _target_language_name(output_language)
    duration_seconds = _transcript_duration(transcript)
    target_blocks = max(1, round(duration_seconds / max(strategy.target_block_seconds, 1)))
    soft_block_limit = _semantic_soft_block_limit(duration_seconds, strategy)
    block_count_instruction = (
        "High-fidelity mode may use as many semantic blocks as the transcript genuinely needs."
        if soft_block_limit is None
        else (
            f"Soft maximum block count is {soft_block_limit}; exceed it only for long or structurally dense courses "
            "where merging would hide important teaching shifts."
        )
    )
    max_tokens = min(
        14000,
        max(1800, 900 + target_blocks * 260),
    )
    attempts: list[str] = [
        "",
        "The previous segmentation was invalid. Be stricter: cover the full timeline once, avoid overlap, "
        "and make every boundary correspond to a real topic shift.",
    ]
    last_error: Exception | None = None
    for extra_instruction in attempts:
        try:
            payload = _chat_json(
                provider,
                [
                    {
                        "role": "system",
                        "content": (
                            f"Segment a course transcript into semantic learning blocks in {target_language}. "
                            "This call only discovers structure; do not summarize every block in detail. "
                            "Use real teaching-topic boundaries, not fixed line counts. Prefer boundaries at "
                            "concept shifts, new examples, transitions, exercises, or conclusion markers. "
                            "Return strict JSON only: {\"blocks\":[{\"start\":number,\"end\":number,"
                            "\"title\":string,\"summary\":string,\"priority\":\"focus|skim|skip|review\","
                            "\"boundary_reason\":string,\"confidence\":number}]}. "
                            f"Target block duration is about {_duration_label(strategy.target_block_seconds)}; "
                            f"acceptable range is {_duration_label(strategy.min_block_seconds)} to "
                            f"{_duration_label(strategy.max_block_seconds)} unless the course structure strongly "
                            f"requires a different size. {block_count_instruction} "
                            "Cover the whole transcript timeline exactly once. "
                            "Do not invent course facts outside the transcript. "
                            f"{extra_instruction}"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Course title: {title}\n"
                            f"Course context: {context_summary}\n"
                            f"Transcript duration: {_duration_label(duration_seconds)}\n"
                            f"Approximate target block count: {target_blocks}\n\n"
                            "Timestamped source transcript:\n"
                            f"{transcript_text}"
                        ),
                    },
                ],
                temperature=0.2,
                max_tokens=max_tokens,
                timeout=240,
                task_key="semantic_segmentation",
            )
            return _validate_semantic_ranges(payload, transcript, output_language, strategy)
        except Exception as exc:
            last_error = exc
    raise last_error or ValueError("Semantic segmentation failed")


def _validate_semantic_ranges(
    payload: object,
    transcript: list[TranscriptSegment],
    output_language: OutputLanguage,
    strategy: StudyGenerationStrategy,
) -> list[TimeRange]:
    if not isinstance(payload, dict):
        raise TypeError("Semantic segmentation payload must be an object")
    raw_blocks = _ensure_list(payload.get("blocks") or payload.get("time_map"))
    ranges: list[TimeRange] = []
    for index, raw in enumerate(raw_blocks):
        if not isinstance(raw, dict):
            continue
        try:
            start = float(raw.get("start"))
            end = float(raw.get("end"))
        except (TypeError, ValueError):
            continue
        title = str(raw.get("title") or "").strip()
        summary = str(raw.get("summary") or raw.get("boundary_reason") or "").strip()
        if not title:
            title = _fallback_range_title(index, output_language)
        if not summary:
            summary = title
        priority = _normalize_time_range({"priority": raw.get("priority", "skim")})["priority"]
        ranges.append(
            TimeRange(
                start=start,
                end=end,
                title=title,
                summary=summary,
                priority=priority,
            )
        )
    if not ranges:
        raise ValueError("Semantic segmentation returned no blocks")
    repaired = _repair_time_ranges(ranges, transcript, output_language, strategy)
    if not repaired:
        raise ValueError("Semantic segmentation could not be repaired")
    return repaired


def _repair_time_ranges(
    ranges: list[TimeRange],
    transcript: list[TranscriptSegment],
    output_language: OutputLanguage,
    strategy: StudyGenerationStrategy,
) -> list[TimeRange]:
    if not transcript:
        return []
    transcript_start = transcript[0].start
    transcript_end = transcript[-1].end
    sorted_ranges = sorted(ranges, key=lambda item: (item.start, item.end))
    repaired: list[TimeRange] = []
    cursor = transcript_start
    for index, time_range in enumerate(sorted_ranges):
        start = _snap_to_segment_start(max(transcript_start, min(time_range.start, transcript_end)), transcript)
        end = _snap_to_segment_end(max(transcript_start, min(time_range.end, transcript_end)), transcript)
        if not repaired and start > transcript_start:
            start = transcript_start
        if repaired and start > cursor + 1:
            repaired[-1] = repaired[-1].model_copy(update={"end": start})
        start = max(start, cursor)
        if end <= start:
            continue
        repaired.append(
            time_range.model_copy(
                update={
                    "start": start,
                    "end": end,
                    "title": time_range.title or _fallback_range_title(index, output_language),
                    "summary": time_range.summary or time_range.title,
                }
            )
        )
        cursor = end
    if not repaired:
        return []
    if repaired[0].start > transcript_start:
        repaired[0] = repaired[0].model_copy(update={"start": transcript_start})
    if repaired[-1].end < transcript_end:
        repaired[-1] = repaired[-1].model_copy(update={"end": transcript_end})
    repaired = _merge_short_ranges(repaired, strategy.min_block_seconds)
    return _split_long_ranges(repaired, transcript, output_language, strategy)


def _merge_short_ranges(ranges: list[TimeRange], min_seconds: int) -> list[TimeRange]:
    merged: list[TimeRange] = []
    for time_range in ranges:
        if merged and time_range.end - time_range.start < min_seconds:
            previous = merged[-1]
            merged[-1] = previous.model_copy(
                update={
                    "end": time_range.end,
                    "summary": _join_summaries(previous.summary, time_range.summary),
                }
            )
        else:
            merged.append(time_range)
    if len(merged) > 1 and merged[0].end - merged[0].start < min_seconds:
        first, second = merged[0], merged[1]
        merged[1] = second.model_copy(
            update={
                "start": first.start,
                "summary": _join_summaries(first.summary, second.summary),
            }
        )
        merged = merged[1:]
    return merged


def _split_long_ranges(
    ranges: list[TimeRange],
    transcript: list[TranscriptSegment],
    output_language: OutputLanguage,
    strategy: StudyGenerationStrategy,
) -> list[TimeRange]:
    split_ranges: list[TimeRange] = []
    for time_range in ranges:
        if time_range.end - time_range.start <= strategy.max_block_seconds * 1.6:
            split_ranges.append(time_range)
            continue
        segments = [
            segment
            for segment in transcript
            if _segment_overlaps_range(segment, time_range.start, time_range.end)
        ]
        local_ranges = _fallback_time_ranges_from_transcript(
            segments,
            output_language,
            strategy,
            title_seed=time_range.title,
            summary_seed=time_range.summary,
        )
        split_ranges.extend(local_ranges or [time_range])
    return [
        time_range.model_copy(update={"title": time_range.title or _fallback_range_title(index, output_language)})
        for index, time_range in enumerate(split_ranges)
    ]


def _fallback_time_ranges_from_transcript(
    transcript: list[TranscriptSegment],
    output_language: OutputLanguage,
    strategy: StudyGenerationStrategy,
    title_seed: str | None = None,
    summary_seed: str | None = None,
) -> list[TimeRange]:
    if not transcript:
        return []
    ranges: list[TimeRange] = []
    current: list[TranscriptSegment] = []
    current_start = transcript[0].start
    for segment in transcript:
        if current and segment.end - current_start >= strategy.target_block_seconds:
            ranges.append(
                _time_range_from_segments(
                    len(ranges),
                    current,
                    output_language,
                    title_seed,
                    summary_seed,
                )
            )
            current = []
            current_start = segment.start
        current.append(segment)
    if current:
        ranges.append(
            _time_range_from_segments(
                len(ranges),
                current,
                output_language,
                title_seed,
                summary_seed,
            )
        )
    return ranges


def _time_range_from_segments(
    index: int,
    segments: list[TranscriptSegment],
    output_language: OutputLanguage,
    title_seed: str | None = None,
    summary_seed: str | None = None,
) -> TimeRange:
    fallback_title = _fallback_range_title(index, output_language)
    first_text = _first_words(segments[0].text, 9)
    title = title_seed if title_seed and index == 0 else f"{fallback_title}: {first_text}"
    summary = summary_seed if summary_seed and index == 0 else " ".join(segment.text for segment in segments[:3])
    return TimeRange(
        start=segments[0].start,
        end=segments[-1].end,
        title=title,
        summary=summary,
        priority="focus" if index == 0 else "skim",
    )


def _fallback_range_title(index: int, output_language: OutputLanguage) -> str:
    if output_language == "zh-CN":
        return f"学习块 {index + 1}"
    if output_language == "ja":
        return f"学習ブロック {index + 1}"
    return f"Learning block {index + 1}"


def _neighbor_context(ranges: list[TimeRange], index: int) -> str:
    lines: list[str] = []
    if index > 0:
        previous = ranges[index - 1]
        lines.append(f"Previous: [{_format_time(previous.start)}-{_format_time(previous.end)}] {previous.title}: {previous.summary}")
    if index + 1 < len(ranges):
        following = ranges[index + 1]
        lines.append(f"Next: [{_format_time(following.start)}-{_format_time(following.end)}] {following.title}: {following.summary}")
    return "\n".join(lines)


def _full_transcript_for_prompt(transcript: list[TranscriptSegment]) -> str:
    return "\n".join(
        f"{index + 1}. [{_format_time(segment.start)}-{_format_time(segment.end)}] {segment.text}"
        for index, segment in enumerate(transcript)
    )


def _estimate_text_tokens(text: str) -> int:
    cjk_chars = len(re.findall(r"[\u4e00-\u9fff\u3040-\u30ff]", text))
    ascii_words = len(re.findall(r"[A-Za-z0-9_]+", text))
    other_chars = max(len(text) - cjk_chars, 0)
    return max(1, cjk_chars + ascii_words + other_chars // 4)


def _transcript_duration(transcript: list[TranscriptSegment]) -> float:
    if not transcript:
        return 0
    return max(0, transcript[-1].end - transcript[0].start)


def _duration_label(seconds: float | int) -> str:
    seconds = float(seconds)
    if seconds < 90:
        return f"{round(seconds)} seconds"
    return f"{seconds / 60:.1f} minutes"


def _snap_to_segment_start(value: float, transcript: list[TranscriptSegment]) -> float:
    return min(transcript, key=lambda segment: abs(segment.start - value)).start


def _snap_to_segment_end(value: float, transcript: list[TranscriptSegment]) -> float:
    return min(transcript, key=lambda segment: abs(segment.end - value)).end


def _join_summaries(first: str, second: str) -> str:
    first = first.strip()
    second = second.strip()
    if not first:
        return second
    if not second or second in first:
        return first
    return f"{first} {second}"


def _generate_learning_blocks_with_provider(
    title: str,
    source_transcript: list[TranscriptSegment],
    translated_transcript: list[TranscriptSegment],
    context_summary: str,
    provider: LlmProvider,
    output_language: OutputLanguage,
    segmentation_provider: LlmProvider | None = None,
    detail_level: StudyDetailLevel = "standard",
    progress: ProgressCallback | None = None,
    partial_ranges: PartialRangesCallback | None = None,
) -> list[dict]:
    strategy = _study_strategy(detail_level)
    segment_provider = segmentation_provider or provider
    try:
        ranges = _generate_semantic_ranges_with_provider(
            title=title,
            transcript=source_transcript,
            context_summary=context_summary,
            provider=segment_provider,
            output_language=output_language,
            strategy=strategy,
        )
        _report(progress, "segmentation", 78, f"已完成语义分块，共 {len(ranges)} 个学习块")
    except Exception:
        ranges = _fallback_time_ranges_from_transcript(source_transcript, output_language, strategy)
        _report(progress, "segmentation", 78, f"语义分块失败，已使用本地分块，共 {len(ranges)} 个学习块")

    if partial_ranges:
        partial_ranges(ranges)

    return _generate_learning_blocks_for_ranges_with_provider(
        title=title,
        source_transcript=source_transcript,
        translated_transcript=translated_transcript,
        ranges=ranges,
        context_summary=context_summary,
        provider=provider,
        output_language=output_language,
        detail_level=detail_level,
        progress=progress,
        progress_start=78,
        progress_span=10,
        progress_message="正在生成学习块",
    )


def _generate_learning_blocks_for_ranges_with_provider(
    title: str,
    source_transcript: list[TranscriptSegment],
    translated_transcript: list[TranscriptSegment],
    ranges: list[TimeRange],
    context_summary: str,
    provider: LlmProvider,
    output_language: OutputLanguage,
    detail_level: StudyDetailLevel = "standard",
    progress: ProgressCallback | None = None,
    progress_start: int = 20,
    progress_span: int = 65,
    progress_message: str = "正在重新生成学习块",
) -> list[dict]:
    if not ranges:
        return _generate_learning_blocks_with_provider(
            title=title,
            source_transcript=source_transcript,
            translated_transcript=translated_transcript,
            context_summary=context_summary,
            provider=provider,
            output_language=output_language,
            detail_level=detail_level,
            progress=progress,
        )

    translated_by_start = {round(segment.start, 2): segment for segment in translated_transcript}
    blocks_by_index: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {}
        for index, time_range in enumerate(ranges):
            source_chunk = [
                segment
                for segment in source_transcript
                if _segment_overlaps_range(segment, time_range.start, time_range.end)
            ]
            if not source_chunk:
                source_chunk = [
                    segment
                    for segment in source_transcript
                    if time_range.start <= segment.start <= time_range.end
                ][:1]
            if not source_chunk:
                blocks_by_index[index] = _block_from_time_range(index, time_range)
                continue
            translated_chunk = [
                translated_by_start.get(round(segment.start, 2))
                or TranscriptSegment(start=segment.start, end=segment.end, text=segment.text)
                for segment in source_chunk
            ]
            futures[
                executor.submit(
                    _generate_learning_block_with_provider,
                    title,
                    index,
                    source_chunk,
                    translated_chunk,
                    context_summary,
                    provider,
                    output_language,
                    detail_level,
                    _neighbor_context(ranges, index),
                )
            ] = (index, time_range, source_chunk, translated_chunk)

        completed = 0
        total = max(len(futures), 1)
        for future in as_completed(futures):
            index, time_range, source_chunk, translated_chunk = futures[future]
            try:
                block = future.result()
                block["id"] = f"block-{index + 1}"
                block["start"] = time_range.start
                block["end"] = time_range.end
                blocks_by_index[index] = block
            except Exception:
                fallback = _fallback_learning_block(index, source_chunk, translated_chunk, output_language)
                fallback["start"] = time_range.start
                fallback["end"] = time_range.end
                blocks_by_index[index] = fallback
            completed += 1
            _report(
                progress,
                "learning_blocks",
                progress_start + round((completed / total) * progress_span),
                f"{progress_message} {completed}/{total}",
            )

    return [
        blocks_by_index.get(index) or _block_from_time_range(index, time_range)
        for index, time_range in enumerate(ranges)
    ]


def _generate_interpretation_blocks_for_existing_ranges_with_provider(
    title: str,
    source_transcript: list[TranscriptSegment],
    translated_transcript: list[TranscriptSegment],
    ranges: list[TimeRange],
    existing_study: StudyMaterial,
    context_summary: str,
    provider: LlmProvider,
    output_language: OutputLanguage,
    detail_level: StudyDetailLevel = "standard",
    progress: ProgressCallback | None = None,
) -> list[dict]:
    return _generate_existing_range_blocks_with_provider(
        title=title,
        source_transcript=source_transcript,
        translated_transcript=translated_transcript,
        ranges=ranges,
        existing_study=existing_study,
        context_summary=context_summary,
        provider=provider,
        output_language=output_language,
        detail_level=detail_level,
        progress=progress,
        section="detailed",
    )


def _generate_high_fidelity_blocks_for_existing_ranges_with_provider(
    title: str,
    source_transcript: list[TranscriptSegment],
    translated_transcript: list[TranscriptSegment],
    ranges: list[TimeRange],
    existing_study: StudyMaterial,
    context_summary: str,
    provider: LlmProvider,
    output_language: OutputLanguage,
    detail_level: StudyDetailLevel = "standard",
    progress: ProgressCallback | None = None,
) -> list[dict]:
    return _generate_existing_range_blocks_with_provider(
        title=title,
        source_transcript=source_transcript,
        translated_transcript=translated_transcript,
        ranges=ranges,
        existing_study=existing_study,
        context_summary=context_summary,
        provider=provider,
        output_language=output_language,
        detail_level=detail_level,
        progress=progress,
        section="high",
    )


def _generate_existing_range_blocks_with_provider(
    title: str,
    source_transcript: list[TranscriptSegment],
    translated_transcript: list[TranscriptSegment],
    ranges: list[TimeRange],
    existing_study: StudyMaterial,
    context_summary: str,
    provider: LlmProvider,
    output_language: OutputLanguage,
    detail_level: StudyDetailLevel,
    progress: ProgressCallback | None,
    section: Literal["detailed", "high"],
) -> list[dict]:
    translated_by_start = {round(segment.start, 2): segment for segment in translated_transcript}
    blocks_by_index: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {}
        for index, time_range in enumerate(ranges):
            source_chunk, translated_chunk = _chunks_for_time_range(
                source_transcript,
                translated_by_start,
                time_range,
            )
            if not source_chunk:
                block = _existing_structure_for_range(existing_study, index, time_range)
                if section == "high":
                    block["detailed_notes"] = _existing_detailed_notes_for_range(existing_study, index, time_range)
                blocks_by_index[index] = block
                continue
            futures[
                executor.submit(
                    _generate_existing_range_block_with_provider,
                    title=title,
                    index=index,
                    time_range=time_range,
                    source_chunk=source_chunk,
                    translated_chunk=translated_chunk,
                    existing_study=existing_study,
                    context_summary=context_summary,
                    provider=provider,
                    output_language=output_language,
                    detail_level=detail_level,
                    section=section,
                )
            ] = (index, time_range)

        completed = 0
        total = max(len(futures), 1)
        for future in as_completed(futures):
            index, time_range = futures[future]
            try:
                block = future.result()
                block["id"] = f"block-{index + 1}"
                block["start"] = time_range.start
                block["end"] = time_range.end
                blocks_by_index[index] = block
            except Exception:
                blocks_by_index[index] = _block_from_time_range(index, time_range)
            completed += 1
            _report(
                progress,
                "learning_blocks",
                20 + round((completed / total) * 65),
                f"正在重新生成{_section_label(section)} {completed}/{total}",
            )

    return [
        blocks_by_index.get(index) or _block_from_time_range(index, time_range)
        for index, time_range in enumerate(ranges)
    ]


def _generate_existing_range_block_with_provider(
    title: str,
    index: int,
    time_range: TimeRange,
    source_chunk: list[TranscriptSegment],
    translated_chunk: list[TranscriptSegment],
    existing_study: StudyMaterial,
    context_summary: str,
    provider: LlmProvider,
    output_language: OutputLanguage,
    detail_level: StudyDetailLevel,
    section: Literal["detailed", "high"],
) -> dict:
    fallback = _fallback_learning_block(index, source_chunk, translated_chunk, output_language)
    structure = _existing_structure_for_range(existing_study, index, time_range)
    if section == "detailed":
        try:
            detailed_notes = _generate_learning_block_interpretation_with_provider(
                title=title,
                index=index,
                source_chunk=source_chunk,
                translated_chunk=translated_chunk,
                context_summary=context_summary,
                structure=structure,
                provider=provider,
                output_language=output_language,
                detail_level=detail_level,
            )
        except Exception:
            detailed_notes = fallback["detailed_notes"]
        high_fidelity_text = fallback["high_fidelity_text"]
    else:
        detailed_notes = _existing_detailed_notes_for_range(existing_study, index, time_range)
        try:
            high_fidelity_text = _generate_learning_block_high_fidelity_with_provider(
                title=title,
                index=index,
                source_chunk=source_chunk,
                translated_chunk=translated_chunk,
                context_summary=context_summary,
                structure=structure,
                detailed_notes=detailed_notes,
                provider=provider,
                output_language=output_language,
                detail_level=detail_level,
            )
        except Exception:
            high_fidelity_text = fallback["high_fidelity_text"]
    return {
        "id": f"block-{index + 1}",
        "start": time_range.start,
        "end": time_range.end,
        "title": str(structure.get("title") or fallback["title"]).strip(),
        "summary": str(structure.get("summary") or fallback["summary"]).strip(),
        "priority": structure.get("priority") if structure.get("priority") in {"focus", "skim", "skip", "review"} else fallback["priority"],
        "key_points": _normalize_key_points(structure.get("key_points")) or fallback["key_points"],
        "detailed_notes": str(detailed_notes or fallback["detailed_notes"]).strip(),
        "high_fidelity_text": str(high_fidelity_text or fallback["high_fidelity_text"]).strip(),
    }


def _generate_learning_block_with_provider(
    title: str,
    index: int,
    source_chunk: list[TranscriptSegment],
    translated_chunk: list[TranscriptSegment],
    context_summary: str,
    provider: LlmProvider,
    output_language: OutputLanguage,
    detail_level: StudyDetailLevel = "standard",
    neighbor_context: str = "",
) -> dict:
    fallback = _fallback_learning_block(index, source_chunk, translated_chunk, output_language)
    try:
        structure = _generate_learning_block_structure_with_provider(
            title=title,
            index=index,
            source_chunk=source_chunk,
            translated_chunk=translated_chunk,
            context_summary=context_summary,
            provider=provider,
            output_language=output_language,
            detail_level=detail_level,
            neighbor_context=neighbor_context,
        )
    except Exception:
        structure = {
            "title": fallback["title"],
            "summary": fallback["summary"],
            "priority": fallback["priority"],
            "key_points": fallback["key_points"],
            "terms": [],
            "open_questions": [],
        }

    try:
        detailed_notes = _generate_learning_block_interpretation_with_provider(
            title=title,
            index=index,
            source_chunk=source_chunk,
            translated_chunk=translated_chunk,
            context_summary=context_summary,
            structure=structure,
            provider=provider,
            output_language=output_language,
            detail_level=detail_level,
        )
    except Exception:
        detailed_notes = fallback["detailed_notes"]

    try:
        high_fidelity_text = _generate_learning_block_high_fidelity_with_provider(
            title=title,
            index=index,
            source_chunk=source_chunk,
            translated_chunk=translated_chunk,
            context_summary=context_summary,
            structure=structure,
            detailed_notes=detailed_notes,
            provider=provider,
            output_language=output_language,
            detail_level=detail_level,
        )
    except Exception:
        high_fidelity_text = fallback["high_fidelity_text"]

    priority = str(structure.get("priority") or fallback["priority"]).lower()
    if priority not in {"focus", "skim", "skip", "review"}:
        priority = fallback["priority"]
    key_points = _normalize_key_points(structure.get("key_points"))
    return {
        "id": f"block-{index + 1}",
        "start": source_chunk[0].start,
        "end": source_chunk[-1].end,
        "title": str(structure.get("title") or fallback["title"]).strip(),
        "summary": str(structure.get("summary") or fallback["summary"]).strip(),
        "priority": priority,
        "key_points": key_points or fallback["key_points"],
        "detailed_notes": str(detailed_notes or fallback["detailed_notes"]).strip(),
        "high_fidelity_text": str(high_fidelity_text or fallback["high_fidelity_text"]).strip(),
    }


def _generate_learning_block_structure_with_provider(
    title: str,
    index: int,
    source_chunk: list[TranscriptSegment],
    translated_chunk: list[TranscriptSegment],
    context_summary: str,
    provider: LlmProvider,
    output_language: OutputLanguage,
    detail_level: StudyDetailLevel,
    neighbor_context: str,
) -> dict:
    target_language = _target_language_name(output_language)
    payload = _chat_json(
        provider,
        [
            {
                "role": "system",
                "content": (
                    f"Extract the learning-block structure from one course transcript segment in {target_language}. "
                    "Use only the provided transcript lines and adjacent block context. Do not add facts outside "
                    "the transcript. Do not write long interpretation, detailed notes, or high-fidelity prose. "
                    "Return strict JSON only: {\"title\":string,\"summary\":string,"
                    "\"priority\":\"focus|skim|skip|review\",\"key_points\":[{\"type\":string,"
                    "\"text\":string,\"evidence\":string}],\"terms\":[string],\"open_questions\":[string]}. "
                    "The title should be short. The summary should explain the block in one or two sentences. "
                    "key_points must extract concrete concepts, claims, methods, examples, steps, warnings, "
                    "definitions, comparisons, transitions, or uncertainties rather than generic topic names. "
                    "Use evidence to briefly identify what transcript content supports each point. "
                    "terms should list important terms, names, product names, or method names in this block. "
                    "open_questions should include only uncertainty or unresolved points actually present in the transcript."
                ),
            },
            {
                "role": "user",
                "content": _learning_block_user_context(
                    title,
                    index,
                    source_chunk,
                    translated_chunk,
                    context_summary,
                    neighbor_context=neighbor_context,
                ),
            },
        ],
        temperature=_learning_temperature(detail_level),
        max_tokens=_learning_block_structure_tokens(detail_level, source_chunk),
        timeout=150,
        task_key="interpretation",
    )
    if not isinstance(payload, dict):
        raise TypeError("Learning block structure payload must be an object")
    return payload


def _generate_learning_block_interpretation_with_provider(
    title: str,
    index: int,
    source_chunk: list[TranscriptSegment],
    translated_chunk: list[TranscriptSegment],
    context_summary: str,
    structure: dict,
    provider: LlmProvider,
    output_language: OutputLanguage,
    detail_level: StudyDetailLevel,
) -> str:
    target_language = _target_language_name(output_language)
    payload = _chat_json(
        provider,
        [
            {
                "role": "system",
                "content": (
                    f"Write the interpretation layer for one course learning block in {target_language}. "
                    "Use only the provided transcript, course context, and extracted learning-block structure. "
                    "Do not invent facts outside the transcript. Do not produce a raw subtitle retelling. "
                    "Do not write the high-fidelity detailed version in this call. "
                    "Return strict JSON only: {\"detailed_notes\": string}. "
                    "detailed_notes should explain what this block is about, why it matters, and how it connects "
                    "to the course thread. It should help the learner decide whether to focus, skim, skip, or review. "
                    "Integrate key points naturally instead of mechanically listing every item."
                ),
            },
            {
                "role": "user",
                "content": (
                    _learning_block_user_context(
                        title,
                        index,
                        source_chunk,
                        translated_chunk,
                        context_summary,
                    )
                    + "\n\nLearning block structure:\n"
                    + json.dumps(_serializable_learning_block_structure(structure), ensure_ascii=False)
                ),
            },
        ],
        temperature=_learning_temperature(detail_level),
        max_tokens=_learning_block_interpretation_tokens(detail_level, source_chunk),
        timeout=180,
        task_key="interpretation",
    )
    if not isinstance(payload, dict):
        raise TypeError("Learning block interpretation payload must be an object")
    return str(payload.get("detailed_notes") or "").strip()


def _generate_learning_block_high_fidelity_with_provider(
    title: str,
    index: int,
    source_chunk: list[TranscriptSegment],
    translated_chunk: list[TranscriptSegment],
    context_summary: str,
    structure: dict,
    detailed_notes: str,
    provider: LlmProvider,
    output_language: OutputLanguage,
    detail_level: StudyDetailLevel,
) -> str:
    strategy = _study_strategy(detail_level)
    target_language = _target_language_name(output_language)
    payload = _chat_json(
        provider,
        [
            {
                "role": "system",
                "content": (
                    f"Write the high-fidelity detailed layer for one course learning block in {target_language}. "
                    "Use only the provided transcript, course context, learning-block structure, and interpretation. "
                    "Do not add facts outside the transcript. Do not flatten several distinct claims into one "
                    "generic sentence. Do not output a raw subtitle dump. "
                    "Return strict JSON only: {\"high_fidelity_text\": string}. "
                    "high_fidelity_text should preserve the original teaching path: setup, claims, reasoning chain, "
                    "examples, numbers, definitions, steps, caveats, transitions, comparisons, limitations, and "
                    "unresolved or uncertain points when present. Prefer finer decomposition over premature compression. "
                    "Keep enough detail that a learner who cannot watch the video can still recover most of the "
                    "information value from this block. Avoid verbatim subtitle copying except for terms, short "
                    "phrases, or necessary definitions. "
                    "Use cautious wording for transcript uncertainty instead of inventing corrections. "
                    "The result should substitute for close watching while still being skimmable."
                ),
            },
            {
                "role": "user",
                "content": (
                    _learning_block_user_context(title, index, source_chunk, translated_chunk, context_summary)
                    + "\n\nLearning block structure:\n"
                    + json.dumps(_serializable_learning_block_structure(structure), ensure_ascii=False)
                    + "\n\nInterpretation detailed_notes:\n"
                    + detailed_notes
                ),
            },
        ],
        temperature=_learning_temperature(detail_level),
        max_tokens=_learning_block_high_fidelity_tokens(strategy, source_chunk),
        timeout=180,
        task_key="high_fidelity",
    )
    if not isinstance(payload, dict):
        raise TypeError("Learning block high-fidelity payload must be an object")
    return str(payload.get("high_fidelity_text") or "").strip()


def _learning_block_user_context(
    title: str,
    index: int,
    source_chunk: list[TranscriptSegment],
    translated_chunk: list[TranscriptSegment],
    context_summary: str,
    neighbor_context: str = "",
) -> str:
    return (
        f"Course title: {title}\n"
        f"Course context: {context_summary}\n"
        f"Block index: {index + 1}\n"
        f"Time range: {_format_time(source_chunk[0].start)}-{_format_time(source_chunk[-1].end)}\n\n"
        f"Adjacent block context:\n{neighbor_context or 'No adjacent context.'}\n\n"
        "Transcript lines:\n"
        + _paired_transcript_lines(source_chunk, translated_chunk)
    )


def _learning_block_structure_tokens(
    detail_level: StudyDetailLevel,
    source_chunk: list[TranscriptSegment],
) -> int:
    strategy = _study_strategy(detail_level)
    block_minutes = max((source_chunk[-1].end - source_chunk[0].start) / 60, 0.25)
    return min(4000, max(1600, round(strategy.block_base_tokens * 0.45 + block_minutes * 360)))


def _learning_block_interpretation_tokens(
    detail_level: StudyDetailLevel,
    source_chunk: list[TranscriptSegment],
) -> int:
    strategy = _study_strategy(detail_level)
    block_minutes = max((source_chunk[-1].end - source_chunk[0].start) / 60, 0.25)
    return min(strategy.block_max_tokens, max(1800, round(strategy.block_base_tokens * 0.75 + block_minutes * 700)))


def _learning_block_high_fidelity_tokens(
    strategy: StudyGenerationStrategy,
    source_chunk: list[TranscriptSegment],
) -> int:
    block_minutes = max((source_chunk[-1].end - source_chunk[0].start) / 60, 0.25)
    return min(
        strategy.block_max_tokens,
        max(2200, round(strategy.block_base_tokens + block_minutes * strategy.block_tokens_per_minute)),
    )


def _serializable_learning_block_structure(structure: dict) -> dict:
    return {
        "title": str(structure.get("title") or "").strip(),
        "summary": str(structure.get("summary") or "").strip(),
        "priority": str(structure.get("priority") or "").strip(),
        "key_points": _ensure_list(structure.get("key_points")),
        "terms": [str(item).strip() for item in _ensure_list(structure.get("terms")) if str(item).strip()],
        "open_questions": [
            str(item).strip()
            for item in _ensure_list(structure.get("open_questions"))
            if str(item).strip()
        ],
    }


def _normalize_key_points(value: object) -> list[str]:
    points: list[str] = []
    for item in _ensure_list(value):
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("claim") or item.get("summary") or "").strip()
        else:
            text = str(item).strip()
        if text:
            points.append(text)
    return points


def _generate_outline_with_provider(
    title: str,
    blocks: list[dict],
    context_summary: str,
    provider: LlmProvider,
    output_language: OutputLanguage,
) -> list[OutlineNode]:
    target_language = _target_language_name(output_language)
    block_index = "\n".join(
        f"- {block['id']} [{_format_time(float(block['start']))}-{_format_time(float(block['end']))}] "
        f"{block['title']}: {block['summary']}"
        for block in blocks
    )
    payload = _chat_json(
        provider,
        [
            {
                "role": "system",
                "content": (
                    f"Build a hierarchical course outline in {target_language}. "
                    "Use only the block index. Merge adjacent blocks when they form one topic. "
                    "Create up to three visible levels whenever the material supports it: "
                    "level 1 for major topics, level 2 for subtopics, and level 3 for concrete "
                    "concepts, examples, claims, caveats, or steps. If the course is short, still "
                    "prefer topic -> subtopic -> concrete point instead of stopping at two levels. "
                    "Return strict JSON only: {\"outline\":[{\"id\":string,\"start\":number,\"end\":number,"
                    "\"title\":string,\"summary\":string,\"children\":array}]}. "
                    "Include source block ids such as block-2 or block-2_block-3 inside every id so "
                    "timestamps can be calibrated."
                ),
            },
            {
                "role": "user",
                "content": f"Course title: {title}\nCourse context: {context_summary}\nBlocks:\n{block_index}",
            },
        ],
        temperature=0.25,
        max_tokens=5000,
        timeout=180,
        task_key="outline",
    )
    if not isinstance(payload, dict):
        raise TypeError("Outline payload must be an object")
    outline_payload = [
        _normalize_outline_node(node)
        for node in _ensure_list(payload.get("outline"))
        if isinstance(node, dict)
    ]
    outline = [OutlineNode.model_validate(node) for node in outline_payload]
    if not outline:
        return _outline_from_blocks(blocks)
    return _calibrate_outline_times(outline, blocks)


def _assemble_study_from_blocks(
    title: str,
    blocks: list[dict],
    output_language: OutputLanguage,
    context_summary: str,
) -> StudyMaterial:
    time_map = [
        TimeRange(
            start=float(block["start"]),
            end=float(block["end"]),
            title=str(block["title"]),
            summary=str(block["summary"]),
            priority=str(block["priority"]) if block["priority"] in {"focus", "skim", "skip", "review"} else "skim",
        )
        for block in blocks
    ]
    detailed_notes = _detailed_notes_from_blocks(blocks)
    high_fidelity_text = _high_fidelity_text_from_blocks(blocks)
    return StudyMaterial(
        one_line=_one_line_from_context(title, blocks, output_language, context_summary),
        translated_title=None,
        context_summary=context_summary,
        time_map=time_map,
        outline=_outline_from_blocks(blocks),
        detailed_notes=detailed_notes,
        high_fidelity_text=high_fidelity_text,
        translated_transcript=[],
        prerequisites=[],
        thought_prompts=[],
        review_suggestions=[],
    )


def _detailed_notes_from_blocks(blocks: list[dict]) -> str:
    return "\n\n".join(
        f"{_format_time(float(block['start']))}-{_format_time(float(block['end']))} {block['title']}\n{block['detailed_notes']}"
        for block in blocks
    )


def _high_fidelity_text_from_blocks(blocks: list[dict]) -> str:
    return "\n\n".join(
        f"[{_format_time(float(block['start']))}-{_format_time(float(block['end']))}] {block['title']}\n{block['high_fidelity_text']}"
        for block in blocks
    )


def _blocks_from_existing_study(study: StudyMaterial) -> list[dict]:
    if study.time_map:
        return _blocks_from_time_map(study.time_map)
    return [
        {
            "id": f"outline-{index + 1}",
            "start": node.start,
            "end": node.end,
            "title": node.title,
            "summary": node.summary,
            "priority": "skim",
            "key_points": [child.title for child in node.children] or [node.summary],
            "detailed_notes": node.summary,
            "high_fidelity_text": node.summary,
        }
        for index, node in enumerate(study.outline)
    ]


def _blocks_from_time_map(ranges: list[TimeRange]) -> list[dict]:
    return [
        {
            "id": f"block-{index + 1}",
            "start": time_range.start,
            "end": time_range.end,
            "title": time_range.title,
            "summary": time_range.summary,
            "priority": time_range.priority,
            "key_points": [time_range.summary] if time_range.summary else [time_range.title],
            "detailed_notes": time_range.summary,
            "high_fidelity_text": time_range.summary,
        }
        for index, time_range in enumerate(ranges)
    ]


def _chunks_for_time_range(
    source_transcript: list[TranscriptSegment],
    translated_by_start: dict[float, TranscriptSegment],
    time_range: TimeRange,
) -> tuple[list[TranscriptSegment], list[TranscriptSegment]]:
    source_chunk = [
        segment
        for segment in source_transcript
        if _segment_overlaps_range(segment, time_range.start, time_range.end)
    ]
    if not source_chunk:
        source_chunk = [
            segment
            for segment in source_transcript
            if time_range.start <= segment.start <= time_range.end
        ][:1]
    translated_chunk = [
        translated_by_start.get(round(segment.start, 2))
        or TranscriptSegment(start=segment.start, end=segment.end, text=segment.text)
        for segment in source_chunk
    ]
    return source_chunk, translated_chunk


def _existing_structure_for_range(study: StudyMaterial, index: int, time_range: TimeRange) -> dict:
    block = _block_from_time_range(index, time_range)
    outline_points = _outline_key_points_for_range(study, index, time_range)
    if outline_points:
        block["key_points"] = outline_points
    return block


def _outline_key_points_for_range(study: StudyMaterial, index: int, time_range: TimeRange) -> list[str]:
    block_id = f"block-{index + 1}"
    for node in study.outline:
        if block_id in node.id or _outline_node_matches_range(node, time_range):
            points = [child.title for child in node.children if child.title.strip()]
            if not points:
                points = [node.summary] if node.summary.strip() else []
            return points
    return []


def _outline_node_matches_range(node: OutlineNode, time_range: TimeRange) -> bool:
    return abs(node.start - time_range.start) < 1 and abs(node.end - time_range.end) < 1


def _existing_detailed_notes_for_range(study: StudyMaterial, index: int, time_range: TimeRange) -> str:
    text = study.detailed_notes.strip()
    if not text:
        return time_range.summary
    expected_prefix = f"{_format_time(time_range.start)}-{_format_time(time_range.end)}"
    for section in re.split(r"\n{2,}", text):
        first_line, _, body = section.partition("\n")
        if first_line.startswith(expected_prefix):
            return body.strip() or first_line.strip()
    if len(study.time_map) == 1:
        _, separator, body = text.partition("\n")
        return body.strip() if separator else text
    return time_range.summary


def _block_from_time_range(index: int, time_range: TimeRange) -> dict:
    return {
        "id": f"block-{index + 1}",
        "start": time_range.start,
        "end": time_range.end,
        "title": time_range.title,
        "summary": time_range.summary,
        "priority": time_range.priority,
        "key_points": [time_range.summary] if time_range.summary else [time_range.title],
        "detailed_notes": time_range.summary,
        "high_fidelity_text": time_range.summary,
    }


def _merge_study_section(
    existing: StudyMaterial,
    generated: StudyMaterial,
    section: StudySection,
) -> StudyMaterial:
    next_study = existing.model_copy(deep=True)
    if generated.context_summary:
        next_study.context_summary = generated.context_summary
    if generated.translated_title:
        next_study.translated_title = generated.translated_title
    if generated.translated_transcript:
        next_study.translated_transcript = generated.translated_transcript
    if section == "guide":
        next_study.one_line = generated.one_line
        next_study.prerequisites = generated.prerequisites
        next_study.thought_prompts = generated.thought_prompts
        next_study.review_suggestions = generated.review_suggestions
        next_study.beginner_focus = generated.beginner_focus
        next_study.experienced_guidance = generated.experienced_guidance
    elif section == "outline":
        next_study.outline = generated.outline
    elif section == "detailed":
        next_study.detailed_notes = generated.detailed_notes
    elif section == "high":
        next_study.high_fidelity_text = generated.high_fidelity_text
    return next_study


def _segment_overlaps_range(segment: TranscriptSegment, start: float, end: float) -> bool:
    return segment.start < end and segment.end > start


def _section_label(section: StudySection) -> str:
    return {
        "all": "学习地图",
        "guide": "导览",
        "outline": "大纲",
        "detailed": "解读",
        "high": "详解",
    }[section]


def _outline_from_blocks(blocks: list[dict]) -> list[OutlineNode]:
    outline: list[OutlineNode] = []
    for block in blocks:
        block_id = str(block["id"])
        block_start = float(block["start"])
        block_end = float(block["end"])
        summary = str(block["summary"])
        details = str(block.get("detailed_notes") or summary)
        key_points = [str(point) for point in block.get("key_points") or [] if str(point).strip()]
        if not key_points:
            key_points = [summary]
        children = [
            OutlineNode(
                id=f"{block_id}-point-{index + 1}",
                start=block_start,
                end=block_end,
                title=point,
                summary=point,
                children=[
                    OutlineNode(
                        id=f"{block_id}-point-{index + 1}-detail-1",
                        start=block_start,
                        end=block_end,
                        title=_first_words(details, 12),
                        summary=details,
                        children=[],
                    )
                ],
            )
            for index, point in enumerate(key_points)
        ]
        outline.append(
            OutlineNode(
                id=block_id,
                start=block_start,
                end=block_end,
                title=str(block["title"]),
                summary=summary,
                children=children,
            )
        )
    return outline


def _calibrate_outline_times(outline: list[OutlineNode], blocks: list[dict]) -> list[OutlineNode]:
    block_ranges = {
        str(block["id"]): (float(block["start"]), float(block["end"]))
        for block in blocks
    }

    def calibrate(node: OutlineNode) -> OutlineNode:
        children = [calibrate(child) for child in node.children]
        block_ids = [block_id for block_id in re.findall(r"block-\d+", node.id) if block_id in block_ranges]
        if block_ids:
            starts = [block_ranges[block_id][0] for block_id in block_ids]
            ends = [block_ranges[block_id][1] for block_id in block_ids]
            return node.model_copy(
                update={
                    "start": min(starts),
                    "end": max(ends),
                    "children": children,
                }
            )
        if children:
            return node.model_copy(
                update={
                    "start": min(child.start for child in children),
                    "end": max(child.end for child in children),
                    "children": children,
                }
            )
        return node.model_copy(update={"children": children})

    return [calibrate(node) for node in outline]


def _fallback_learning_block(
    index: int,
    source_chunk: list[TranscriptSegment],
    translated_chunk: list[TranscriptSegment],
    output_language: OutputLanguage,
) -> dict:
    display_chunk = translated_chunk or source_chunk
    title = (
        f"第 {index + 1} 段：{_first_words(display_chunk[0].text, 8)}"
        if output_language == "zh-CN"
        else f"セクション {index + 1}: {_first_words(display_chunk[0].text, 8)}"
        if output_language == "ja"
        else f"Block {index + 1}: {_first_words(display_chunk[0].text, 8)}"
    )
    lines = "\n".join(
        f"[{_format_time(segment.start)}-{_format_time(segment.end)}] {segment.text}"
        for segment in display_chunk
    )
    return {
        "id": f"block-{index + 1}",
        "start": source_chunk[0].start,
        "end": source_chunk[-1].end,
        "title": title,
        "summary": " ".join(segment.text for segment in display_chunk[:2]),
        "priority": "focus" if index == 0 else "skim",
        "key_points": [segment.text for segment in display_chunk[:3]],
        "detailed_notes": lines,
        "high_fidelity_text": lines,
    }


def _paired_transcript_lines(
    source_chunk: list[TranscriptSegment],
    translated_chunk: list[TranscriptSegment],
) -> str:
    lines: list[str] = []
    for index, source in enumerate(source_chunk):
        translated = translated_chunk[index] if index < len(translated_chunk) else None
        target_text = translated.text if translated else source.text
        lines.append(
            f"[{_format_time(source.start)}-{_format_time(source.end)}] "
            f"source: {source.text}\ntranslation: {target_text}"
        )
    return "\n".join(lines)


def _one_line_from_context(
    title: str,
    blocks: list[dict],
    output_language: OutputLanguage,
    context_summary: str,
) -> str:
    clean_summary = " ".join(context_summary.split())
    if output_language == "zh-CN":
        return f"这门课程围绕「{title}」展开。"
    if output_language == "ja":
        return f"このコースは「{title}」を中心に展開されています。"
    if len(clean_summary) > 64:
        clean_summary = clean_summary[:61].rstrip() + "..."
    return f"{len(blocks)} learning blocks: {clean_summary}"


def _partial_one_line_from_context(
    title: str,
    output_language: OutputLanguage,
    context_summary: str,
) -> str:
    if output_language == "zh-CN":
        return "正在生成学习地图。"
    if output_language == "ja":
        return "学習マップを生成中です。"
    clean_summary = " ".join((context_summary or title).split()) or title
    if len(clean_summary) > 64:
        clean_summary = clean_summary[:61].rstrip() + "..."
    return f"Generating study map: {clean_summary}"


def _context_summary_with_metadata(
    context_summary: str,
    metadata: VideoMetadata | None,
) -> str:
    metadata_reference = _metadata_prompt_reference(metadata).strip()
    if not metadata_reference:
        return context_summary
    return f"{context_summary.strip()}\n\n{metadata_reference}".strip()


def _metadata_prompt_reference(metadata: VideoMetadata | None) -> str:
    if not metadata:
        return ""
    fields = [
        ("id", metadata.id),
        ("metadata_title", metadata.title),
        ("duration_seconds", _format_metadata_duration(metadata.duration)),
        ("uploader", metadata.uploader),
        ("channel", metadata.channel),
        ("creator", metadata.creator),
        ("description", _truncate_prompt_text(metadata.description, 1200)),
        ("playlist_title", metadata.playlist_title),
        ("playlist_index", metadata.playlist_index),
        ("webpage_url", metadata.webpage_url),
        ("extractor", metadata.extractor),
        ("language", metadata.language),
        ("subtitles", ", ".join(metadata.subtitles) if metadata.subtitles else None),
        ("automatic_captions", ", ".join(metadata.automatic_captions) if metadata.automatic_captions else None),
    ]
    lines = [f"- {key}: {value}" for key, value in fields if value]
    if not lines:
        return ""
    return "Trusted video metadata:\n" + "\n".join(lines) + "\n\n"


def _format_metadata_duration(duration: float | None) -> str | None:
    if duration is None:
        return None
    return f"{duration:g}"


def _truncate_prompt_text(value: str | None, limit: int) -> str | None:
    if not value:
        return None
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _send_partial_study(
    partial_study: PartialStudyCallback | None,
    study: StudyMaterial,
) -> None:
    if partial_study:
        partial_study(study.model_copy(deep=True))


def _target_language_name(output_language: OutputLanguage) -> str:
    if output_language == "zh-CN":
        return "Simplified Chinese"
    if output_language == "ja":
        return "Japanese"
    return "English"


def _chunk_segments(
    transcript: list[TranscriptSegment],
    target_size: int,
) -> list[list[TranscriptSegment]]:
    return [
        transcript[index : index + target_size]
        for index in range(0, len(transcript), target_size)
    ]


def _report(
    progress: ProgressCallback | None,
    phase: str,
    value: int,
    message: str,
) -> None:
    if progress:
        progress(phase, max(0, min(100, value)), message)


def _format_time(seconds: float) -> str:
    total = int(seconds)
    minutes, sec = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def _first_words(text: str, count: int) -> str:
    words = text.split()
    if len(words) <= 1 and len(text) > count * 4:
        return text[: count * 4].rstrip() + "..."
    if len(words) <= count:
        return text
    return " ".join(words[:count]) + "..."


def _loads_json_content(content: str) -> object:
    stripped = content.strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL)
    if fence_match:
        stripped = fence_match.group(1).strip()
    return json.loads(stripped)


def _normalize_time_range(payload: dict) -> dict:
    normalized = dict(payload)
    priority = str(normalized.get("priority", "skim")).lower()
    normalized["priority"] = {
        "high": "focus",
        "important": "focus",
        "must": "focus",
        "medium": "skim",
        "low": "skip",
        "hard": "review",
    }.get(priority, priority if priority in {"focus", "skim", "skip", "review"} else "skim")
    return normalized


def _normalize_outline_node(payload: dict) -> dict:
    normalized = dict(payload)
    normalized["children"] = [
        _normalize_outline_node(child)
        for child in _ensure_list(normalized.get("children"))
        if isinstance(child, dict)
    ]
    return normalized


def _ensure_list(value: object) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
