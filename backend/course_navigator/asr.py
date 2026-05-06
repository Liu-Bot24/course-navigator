from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Callable
from threading import Event, Thread
from time import monotonic
from typing import Any

import httpx

from .ai import LlmProvider, _chat_text, _loads_json_content
from .models import (
    AsrCorrectionSearchConfig,
    AsrCorrectionSuggestion,
    OutputLanguage,
    TaskParameterKey,
    TranscriptSegment,
)

ProgressCallback = Callable[[str, int, str], None]
MAX_CANDIDATES_PER_FILE = 240
DEFAULT_SCAN_CHUNKS = 5
MAX_SCAN_CHUNKS = 12
MAX_REVIEW_CANDIDATES_PER_CALL = 40
ASR_MODEL_RESPONSE_TIMEOUT_SECONDS = 240
SEARCH_QUERY_BUDGET_MIN = 6
SEARCH_QUERY_BUDGET_MAX = 48
SEARCH_RESULTS_PER_BACKGROUND_ITEM = 3
SEARCH_BACKGROUND_MAX_CARDS = 24


def suggest_asr_corrections(
    *,
    title: str,
    transcript: list[TranscriptSegment],
    provider: LlmProvider,
    search_config: AsrCorrectionSearchConfig,
    context: dict[str, object] | None = None,
    output_language: OutputLanguage = "zh-CN",
    progress: ProgressCallback | None = None,
) -> list[AsrCorrectionSuggestion]:
    if not transcript:
        return []

    _report(progress, "candidate", 6, "正在建立资料上下文并检查 ASR 候选项")
    candidates = _extract_candidate_items(
        title,
        transcript,
        provider,
        context,
        progress,
        search_enabled=search_config.enabled,
    )
    if not candidates:
        return []

    if search_config.enabled:
        _report(progress, "search", 32, "正在搜索校验证据")
        evidence = _collect_search_evidence(candidates, search_config, progress)
        _report(progress, "background", 64, "正在归纳搜索背景信息")
        background_cards = _synthesize_search_background_cards(
            title,
            candidates,
            evidence,
            provider,
            context,
            output_language,
            progress,
        )
        _report(progress, "review", 68, "正在统一审核候选错误和搜索背景")
        raw_patches = _review_candidate_patches(
            title,
            transcript,
            provider,
            candidates,
            background_cards,
            context,
            output_language,
            progress,
            source="search",
        )
        return _normalize_patch_payload(raw_patches, transcript, source="search")

    _report(progress, "review", 48, "正在统一审核候选错误并生成补丁")
    raw_patches = _review_candidate_patches(
        title,
        transcript,
        provider,
        candidates,
        [],
        context,
        output_language,
        progress,
        source="model",
    )
    return _normalize_patch_payload(raw_patches, transcript, source="model")


def _extract_candidate_items(
    title: str,
    transcript: list[TranscriptSegment],
    provider: LlmProvider,
    context: dict[str, object] | None,
    progress: ProgressCallback | None,
    *,
    search_enabled: bool,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    chunks = _scan_chunks(transcript)
    total = len(chunks)
    for chunk_number, (chunk_start, chunk) in enumerate(chunks, start=1):
        base_progress = _scaled_progress(8, 32 if search_enabled else 45, chunk_number - 1, total)
        done_progress = _scaled_progress(8, 32 if search_enabled else 45, chunk_number, total)
        _report(progress, "candidate", base_progress, f"正在扫描第 {chunk_number}/{total} 批字幕候选错误")
        payload = _chat_json_with_progress(
            provider,
            _candidate_messages(
                title,
                chunk,
                start_index=chunk_start,
                context=context,
                search_enabled=search_enabled,
            ),
            temperature=0.12,
            max_tokens=_candidate_max_tokens(chunk, search_enabled=search_enabled),
            timeout=ASR_MODEL_RESPONSE_TIMEOUT_SECONDS,
            task_key="asr_correction",
            progress=progress,
            phase="model_wait",
            base_progress=base_progress,
            max_progress=done_progress,
            message=f"正在等待大模型返回第 {chunk_number}/{total} 批候选错误",
        )
        _report(progress, "model_parse", done_progress, f"正在整理第 {chunk_number}/{total} 批候选错误")
        for item in _payload_list(payload, "candidates"):
            if isinstance(item, dict):
                candidates.append(item)
    return _dedupe_candidates(candidates, transcript)[:MAX_CANDIDATES_PER_FILE]


def _collect_search_evidence(
    candidates: list[dict[str, Any]],
    config: AsrCorrectionSearchConfig,
    progress: ProgressCallback | None,
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    query_plans = _search_query_plans(candidates)
    if not query_plans:
        return []
    raw_query_count = sum(
        len(_candidate_queries(candidate)) or (1 if _candidate_fallback_query(candidate) else 0)
        for candidate in candidates
    )
    budget = _search_query_budget(len(candidates), len(query_plans))
    selected_plans = query_plans[:budget]
    _report(
        progress,
        "search",
        32,
        f"已将 {raw_query_count} 个候选查询归一化为 {len(query_plans)} 个唯一术语，准备搜索 {len(selected_plans)} 个",
    )
    total_queries = max(1, len(selected_plans))
    for query_index, plan in enumerate(selected_plans, start=1):
        _report(progress, "search", _scaled_progress(32, 64, query_index - 1, total_queries), f"正在搜索第 {query_index}/{total_queries} 个唯一术语背景")
        results = _search(str(plan["query"]), config)
        _report(progress, "search", _scaled_progress(32, 64, query_index, total_queries), f"已获取第 {query_index}/{total_queries} 个唯一术语背景")
        evidence.append(
            {
                "query": plan["query"],
                "normalized_query": plan["normalized_query"],
                "candidate_count": plan["candidate_count"],
                "candidate_examples": plan["candidate_examples"],
                "results": results,
            }
        )
    return evidence


def _search_query_plans(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        queries = _candidate_queries(candidate)
        if not queries:
            fallback = _candidate_fallback_query(candidate)
            queries = [fallback] if fallback else []
        for query in queries:
            normalized = _normalize_search_query(query)
            if not normalized:
                continue
            plan = grouped.setdefault(
                normalized,
                {
                    "query": query,
                    "normalized_query": normalized,
                    "score": 0.0,
                    "candidates": [],
                    "queries": set(),
                },
            )
            plan["score"] += _search_query_score(candidate)
            plan["candidates"].append(candidate)
            plan["queries"].add(query)
            if len(query) < len(str(plan["query"])):
                plan["query"] = query
    plans: list[dict[str, Any]] = []
    for plan in grouped.values():
        related = plan["candidates"]
        plans.append(
            {
                "query": plan["query"],
                "normalized_query": plan["normalized_query"],
                "score": plan["score"],
                "candidate_count": len(related),
                "candidate_examples": _compact_candidates(related[:3]),
            }
        )
    return sorted(
        plans,
        key=lambda plan: (
            -float(plan["score"]),
            -int(plan["candidate_count"]),
            len(str(plan["query"])),
            str(plan["query"]).casefold(),
        ),
    )


def _candidate_fallback_query(candidate: dict[str, Any]) -> str:
    suggested = str(candidate.get("suggested_correction") or candidate.get("corrected_text") or candidate.get("t") or "").strip()
    asr_text = str(candidate.get("asr_text") or candidate.get("original_text") or candidate.get("f") or "").strip()
    if suggested and suggested.casefold() != asr_text.casefold():
        return suggested[:80]
    return asr_text[:80]


def _normalize_search_query(query: str) -> str:
    value = unicodedata.normalize("NFKC", query).casefold()
    value = re.sub(r"[\"'“”‘’`]+", "", value)
    value = re.sub(r"[\s/_\\\-–—:：]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _search_query_score(candidate: dict[str, Any]) -> float:
    priority = _coerce_int(candidate.get("priority", candidate.get("p"))) or 5
    confidence = _coerce_confidence(candidate.get("confidence", candidate.get("c")))
    category = str(candidate.get("category") or candidate.get("k") or "").casefold()
    category_boost = 1.5 if any(token in category for token in ("model", "product", "term", "name", "person", "acronym")) else 0.0
    return max(0.2, 7 - priority) + confidence * 2 + category_boost


def _search_query_budget(candidate_count: int, unique_query_count: int) -> int:
    if unique_query_count <= SEARCH_QUERY_BUDGET_MIN:
        return unique_query_count
    dynamic_budget = math.ceil(math.sqrt(max(1, candidate_count)) * 3)
    return min(unique_query_count, SEARCH_QUERY_BUDGET_MAX, max(SEARCH_QUERY_BUDGET_MIN, dynamic_budget))


def _review_candidate_patches(
    title: str,
    transcript: list[TranscriptSegment],
    provider: LlmProvider,
    candidates: list[dict[str, Any]],
    search_background: list[dict[str, Any]],
    context: dict[str, object] | None,
    output_language: OutputLanguage,
    progress: ProgressCallback | None,
    *,
    source: str,
) -> object:
    patches: list[Any] = []
    groups = _candidate_groups(candidates)
    total = len(groups)
    start_progress = 70 if source == "search" else 50
    end_progress = 94
    for group_number, group in enumerate(groups, start=1):
        base_progress = _scaled_progress(start_progress, end_progress, group_number - 1, total)
        done_progress = _scaled_progress(start_progress, end_progress, group_number, total)
        _report(progress, "model_request", base_progress, f"正在发送第 {group_number}/{total} 组候选错误给审核模型")
        payload = _chat_json_with_progress(
            provider,
            _review_messages(
                title,
                candidates=group,
                transcript_windows=_candidate_transcript_windows(group, transcript),
                search_background=search_background,
                context=context,
                output_language=output_language,
                source=source,
            ),
            temperature=0.08,
            max_tokens=9000,
            timeout=ASR_MODEL_RESPONSE_TIMEOUT_SECONDS,
            task_key="asr_correction",
            progress=progress,
            phase="model_wait",
            base_progress=base_progress,
            max_progress=done_progress,
            message=f"正在等待审核模型返回第 {group_number}/{total} 组补丁",
        )
        _report(progress, "model_parse", done_progress, f"正在解析第 {group_number}/{total} 组补丁")
        patches.extend(_payload_list(payload, "patches"))
    return {"patches": patches}


def _synthesize_search_background_cards(
    title: str,
    candidates: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    provider: LlmProvider,
    context: dict[str, object] | None,
    output_language: OutputLanguage,
    progress: ProgressCallback | None,
) -> list[dict[str, Any]]:
    if not evidence:
        return []
    payload = _chat_json_with_progress(
        provider,
        _search_background_messages(
            title,
            candidates=candidates,
            evidence=evidence,
            context=context,
            output_language=output_language,
        ),
        temperature=0.04,
        max_tokens=7000,
        timeout=ASR_MODEL_RESPONSE_TIMEOUT_SECONDS,
        task_key="asr_correction",
        progress=progress,
        phase="model_wait",
        base_progress=64,
        max_progress=68,
        message="正在等待大模型归纳搜索背景信息",
    )
    cards = [card for card in _payload_list(payload, "background") if isinstance(card, dict)]
    return _normalize_search_background_cards(cards)[:SEARCH_BACKGROUND_MAX_CARDS]


def _candidate_messages(
    title: str,
    transcript: list[TranscriptSegment],
    *,
    start_index: int,
    context: dict[str, object] | None,
    search_enabled: bool,
) -> list[dict[str, str]]:
    search_instruction = (
        "For candidates that need search, q should contain 1-2 normalized, reusable queries that verify exact spelling, named entities, product names, or model versions."
        if search_enabled
        else "q may be empty; include t only when local context or trusted reference strongly supports a likely correction."
    )
    return [
        {
            "role": "system",
            "content": (
                "You are an ASR candidate extractor. Find short spans that may be ASR errors. "
                "Do not patch, rewrite, summarize, polish, or translate the transcript. Return JSON only."
            ),
        },
        {
            "role": "user",
            "content": (
                "Return compact JSON only: {\"c\":[{\"i\":0,\"f\":\"asr span\",\"t\":\"likely correction\",\"k\":\"term\",\"r\":\"short reason\",\"c\":0.91,\"q\":[\"query\"],\"p\":1}]}.\n"
                "Field meanings: i=segment_index, f=exact ASR short span, t=likely correction or empty, "
                "k=category, r=short risk reason, c=confidence, q=search queries, p=priority.\n"
                "Rules: only short spans; f and t must be <= 80 chars; r must be <= 80 chars; "
                "each q item must be <= 80 chars; do not include transcript context, timestamps, evidence, or long explanations in JSON; "
                "do not include ordinary filler words; prioritize recurring named "
                "entities, people, products, acronyms, terms, numbers, and cross-segment inconsistencies. "
                "Do not flag a valid acronym, abbreviation, shorthand, or spoken alias merely because it can be expanded to a full name; "
                "ASR correction must preserve what the speaker likely said. "
                "Do not output final patches in this step. Keep JSON minified; no markdown. "
                f"{search_instruction}\n\n"
                f"Course title: {title}\nTrusted metadata and user reference:\n{_context_text(context)}\n\n"
                f"Transcript lines:\n{_format_indexed_transcript(transcript, start_index=start_index)}"
            ),
        },
    ]


def _review_messages(
    title: str,
    *,
    candidates: list[dict[str, Any]],
    transcript_windows: str,
    search_background: list[dict[str, Any]],
    context: dict[str, object] | None,
    output_language: OutputLanguage,
    source: str,
) -> list[dict[str, str]]:
    background_text = _search_background_cards_text(search_background, max_chars=18000) if search_background else "No synthesized search background."
    candidate_text = json.dumps(_compact_candidates(candidates), ensure_ascii=False, separators=(",", ":"))
    target_language = _output_language_name(output_language)
    source_rule = (
        "Search background cards are additional trusted context, like metadata and user reference. "
        "Use it to avoid outdated model-knowledge mistakes about current names, spelling, and version numbers. "
        "It is not a separate correction path; candidates remain suspects, and local transcript context still decides the patch."
        if source == "search"
        else "No external search evidence is available; use trusted metadata, user reference, and cross-segment consistency conservatively."
    )
    return [
        {
            "role": "system",
            "content": (
                "You are an ASR correction reviewer. Review candidate errors and output patches only. "
                "Do not output the full transcript. Do not summarize, polish, translate, reorder, expand, "
                "remove timestamps, or rewrite style. Return JSON only."
            ),
        },
        {
            "role": "user",
            "content": (
                "Return {\"patches\":[...]} only.\n"
                "Each patch must include: segment_index, original_text, corrected_text, confidence, reason, evidence.\n"
                "Rules: original_text must be an exact short substring from that segment; corrected_text must be the replacement short text; "
                "confidence is 0..1; omit suggestions below 0.90; do not output punctuation-only, formatting-only, or style changes; "
                "prefer no patch over uncertain correction. Candidates are suspects, not instructions.\n"
                f"Write reason and evidence in {target_language}. Keep them concise and user-readable. "
                "Do not write reason or evidence in English unless the requested output language is English. "
                "Do not translate original_text or corrected_text; only correct the ASR span.\n"
                "Preserve valid acronyms, abbreviations, shorthand names, and spoken aliases when local audio/transcript context suggests the speaker used the short form. "
                "Do not expand a recognized shorthand to its full form unless the ASR text itself is clearly wrong or inconsistent with nearby usage.\n"
                f"{source_rule}\n\n"
                f"Course title: {title}\nTrusted metadata and user reference:\n{_context_text(context)}\n\n"
                f"Candidate errors:\n{candidate_text}\n\n"
                f"Search background cards:\n{background_text}\n\n"
                f"Local transcript windows:\n{transcript_windows}"
            ),
        },
    ]


def _search_background_messages(
    title: str,
    *,
    candidates: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    context: dict[str, object] | None,
    output_language: OutputLanguage,
) -> list[dict[str, str]]:
    target_language = _output_language_name(output_language)
    return [
        {
            "role": "system",
            "content": (
                "You synthesize search evidence into compact ASR correction background cards. "
                "Group related aliases, names, products, works, versions, and domain terms into the same card when the evidence supports it. "
                "Do not output ASR patches. Do not invent facts beyond search evidence, trusted metadata, or user reference. Return JSON only."
            ),
        },
        {
            "role": "user",
            "content": (
                "Return {\"background\":[...]} only.\n"
                "Each card must include: topic, summary, aliases, key_facts, source_queries, confidence.\n"
                "Rules: topic is the canonical entity or term; summary is 1-2 concise sentences; "
                "aliases and key_facts are arrays of short strings; source_queries lists the queries that support the card; "
                "confidence is 0..1; omit weak or irrelevant evidence; merge duplicate or overlapping cards; "
                f"write summary and key_facts in {target_language}; preserve exact names, works, titles, and version strings.\n\n"
                f"Course title: {title}\nTrusted metadata and user reference:\n{_context_text(context)}\n\n"
                f"Candidate terms:\n{json.dumps(_compact_candidates(candidates), ensure_ascii=False, separators=(',', ':'))}\n\n"
                f"Search evidence to synthesize:\n{_search_evidence_text(evidence, max_chars=22000)}"
            ),
        },
    ]


def _search_evidence_text(evidence: list[dict[str, Any]], *, max_chars: int) -> str:
    background: list[dict[str, Any]] = []
    for item in evidence:
        results: list[dict[str, str]] = []
        raw_results = item.get("results")
        if isinstance(raw_results, list):
            for result in raw_results[:SEARCH_RESULTS_PER_BACKGROUND_ITEM]:
                if not isinstance(result, dict):
                    continue
                results.append(
                    {
                        "title": str(result.get("title") or "").strip(),
                        "snippet": str(result.get("snippet") or "").strip()[:360],
                        "url": str(result.get("url") or "").strip(),
                    }
                )
        if not results:
            continue
        background.append(
            {
                "query": item.get("query"),
                "candidate_count": item.get("candidate_count"),
                "candidate_examples": item.get("candidate_examples"),
                "facts": results,
            }
        )
    if not background:
        return "No useful external search background."
    text = json.dumps(background, ensure_ascii=False, separators=(",", ":"))
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}\n...truncated..."


def _normalize_search_background_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for card in cards:
        topic = str(card.get("topic") or "").strip()
        summary = str(card.get("summary") or "").strip()
        if not topic or not summary:
            continue
        key = _normalize_search_query(topic)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "topic": topic[:120],
                "summary": summary[:700],
                "aliases": _short_string_list(card.get("aliases"), limit=12, item_limit=80),
                "key_facts": _short_string_list(card.get("key_facts"), limit=12, item_limit=180),
                "source_queries": _short_string_list(card.get("source_queries"), limit=12, item_limit=80),
                "confidence": _coerce_confidence(card.get("confidence")),
            }
        )
    return sorted(normalized, key=lambda item: (-float(item.get("confidence") or 0), str(item.get("topic") or "").casefold()))


def _search_background_cards_text(cards: list[dict[str, Any]], *, max_chars: int) -> str:
    text = json.dumps(cards, ensure_ascii=False, separators=(",", ":"))
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}\n...truncated..."


def _short_string_list(value: object, *, limit: int, item_limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    seen: set[str] = set()
    for raw in value:
        item = str(raw).strip()
        if not item:
            continue
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        items.append(item[:item_limit])
        if len(items) >= limit:
            break
    return items


def _search(query: str, config: AsrCorrectionSearchConfig) -> list[dict[str, Any]]:
    if config.provider == "tavily":
        if not config.api_key:
            raise ValueError("Tavily API key is required when search calibration is enabled")
        response = httpx.post(
            "https://api.tavily.com/search",
            headers={"Authorization": f"Bearer {config.api_key}"},
            json={"query": query, "max_results": config.result_limit},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        return _normalize_search_results(payload.get("results"), "tavily")

    base_url = (config.base_url or "").strip().rstrip("/")
    if not base_url:
        raise ValueError("Firecrawl base URL is required when search calibration is enabled")
    endpoint = base_url
    if not endpoint.endswith("/search"):
        if not endpoint.endswith("/v1"):
            endpoint = f"{endpoint}/v1"
        endpoint = f"{endpoint}/search"
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    response = httpx.post(
        endpoint,
        headers=headers,
        json={"query": query, "limit": config.result_limit},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    return _normalize_search_results(payload.get("data") or payload.get("results"), "firecrawl")


def _normalize_search_results(raw_results: object, source: str) -> list[dict[str, Any]]:
    if not isinstance(raw_results, list):
        return []
    normalized: list[dict[str, Any]] = []
    for rank, item in enumerate(raw_results[:10], start=1):
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "title": str(item.get("title") or "").strip(),
                "url": str(item.get("url") or item.get("link") or "").strip(),
                "snippet": str(item.get("content") or item.get("snippet") or item.get("description") or "").strip(),
                "source": source,
                "rank": rank,
            }
        )
    return normalized


def _normalize_patch_payload(
    payload: object,
    transcript: list[TranscriptSegment],
    *,
    source: str,
) -> list[AsrCorrectionSuggestion]:
    suggestions: list[AsrCorrectionSuggestion] = []
    seen: set[tuple[int, str, str]] = set()
    for raw in _payload_list(payload, "patches"):
        if not isinstance(raw, dict):
            continue
        segment_index = _coerce_int(raw.get("segment_index"))
        if segment_index is None or segment_index < 0 or segment_index >= len(transcript):
            continue
        segment = transcript[segment_index]
        original = str(raw.get("original_text") or raw.get("from") or "").strip()
        corrected = str(raw.get("corrected_text") or raw.get("to") or "").strip()
        if not original or not corrected or original == corrected:
            continue
        if _looks_like_mojibake(corrected):
            continue
        if original not in segment.text:
            continue
        if _format_only_change(original, corrected):
            continue
        confidence = _coerce_confidence(raw.get("confidence"))
        if confidence < 0.9:
            continue
        key = (segment_index, original, corrected)
        if key in seen:
            continue
        seen.add(key)
        suggestion_id = _patch_id(segment_index, original, corrected)
        suggestions.append(
            AsrCorrectionSuggestion(
                id=suggestion_id,
                segment_index=segment_index,
                start=segment.start,
                end=segment.end,
                original_text=original,
                corrected_text=corrected,
                confidence=confidence,
                reason=str(raw.get("reason") or "模型建议校正此 ASR 片段。").strip(),
                evidence=str(raw.get("evidence") or "").strip() or None,
                source="search" if source == "search" else "model",
            )
        )
    return suggestions


def _payload_list(payload: object, key: str) -> list[object]:
    if isinstance(payload, dict):
        value = payload.get(key)
        if value is None and key == "candidates":
            value = payload.get("c")
        return value if isinstance(value, list) else []
    return []


def _dedupe_candidates(candidates: list[dict[str, Any]], transcript: list[TranscriptSegment]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[int, str, str]] = set()
    for candidate in candidates:
        segment_index = _coerce_int(candidate.get("segment_index", candidate.get("i")))
        if segment_index is None or segment_index < 0 or segment_index >= len(transcript):
            continue
        asr_text = str(candidate.get("asr_text") or candidate.get("original_text") or candidate.get("f") or "").strip()
        suggested = str(
            candidate.get("suggested_correction") or candidate.get("corrected_text") or candidate.get("t") or ""
        ).strip()
        if not asr_text:
            continue
        key = (segment_index, asr_text.casefold(), suggested.casefold())
        if key in seen:
            continue
        seen.add(key)
        normalized = dict(candidate)
        normalized["segment_index"] = segment_index
        normalized["asr_text"] = asr_text
        normalized["category"] = str(candidate.get("category") or candidate.get("k") or "").strip()
        normalized["risk_reason"] = str(candidate.get("risk_reason") or candidate.get("r") or "").strip()
        normalized["confidence"] = _coerce_confidence(candidate.get("confidence", candidate.get("c")))
        normalized["priority"] = _coerce_int(candidate.get("priority", candidate.get("p"))) or 5
        normalized["search_queries"] = _candidate_queries(candidate)
        if suggested:
            normalized["suggested_correction"] = suggested
        deduped.append(normalized)
    return sorted(deduped, key=_candidate_sort_key)


def _candidate_sort_key(candidate: dict[str, Any]) -> tuple[int, float, int]:
    priority = _coerce_int(candidate.get("priority", candidate.get("p"))) or 5
    confidence = _coerce_confidence(candidate.get("confidence", candidate.get("c")))
    segment_index = _coerce_int(candidate.get("segment_index")) or 0
    return (priority, -confidence, segment_index)


def _candidate_queries(candidate: dict[str, Any]) -> list[str]:
    raw_queries = candidate.get("search_queries")
    if not isinstance(raw_queries, list):
        raw_queries = candidate.get("q")
    if not isinstance(raw_queries, list):
        return []
    return [str(item).strip()[:80] for item in raw_queries if str(item).strip()][:4]


def _compact_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for candidate in candidates:
        item: dict[str, Any] = {
            "i": candidate.get("segment_index"),
            "f": candidate.get("asr_text"),
            "t": candidate.get("suggested_correction") or "",
            "k": candidate.get("category") or "",
            "r": candidate.get("risk_reason") or "",
            "c": candidate.get("confidence") or 0,
            "q": _candidate_queries(candidate),
            "p": candidate.get("priority") or 5,
        }
        compact.append(item)
    return compact


def _candidate_groups(candidates: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    return [
        candidates[index : index + MAX_REVIEW_CANDIDATES_PER_CALL]
        for index in range(0, len(candidates), MAX_REVIEW_CANDIDATES_PER_CALL)
    ]


def _candidate_transcript_windows(candidates: list[dict[str, Any]], transcript: list[TranscriptSegment]) -> str:
    selected: set[int] = set()
    for candidate in candidates:
        segment_index = _coerce_int(candidate.get("segment_index"))
        if segment_index is None:
            continue
        for index in range(max(0, segment_index - 2), min(len(transcript), segment_index + 3)):
            selected.add(index)
    return "\n".join(
        f"[{index} | {_format_time(transcript[index].start)}-{_format_time(transcript[index].end)}] {transcript[index].text}"
        for index in sorted(selected)
    )


def _chat_json_with_progress(
    provider: LlmProvider,
    messages: list[dict[str, str]],
    *,
    temperature: float,
    max_tokens: int,
    timeout: float,
    task_key: TaskParameterKey,
    progress: ProgressCallback | None,
    phase: str,
    base_progress: int,
    max_progress: int,
    message: str,
) -> object:
    stop = Event()

    def heartbeat() -> None:
        started = monotonic()
        while not stop.wait(6):
            elapsed = int(monotonic() - started)
            step = min(max_progress - 1, base_progress + max(1, elapsed // 8))
            _report(progress, phase, step, f"{message}，已等待 {elapsed}s")

    _report(progress, phase, base_progress, f"{message}，等待响应")
    thread = Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        content = _chat_text(
            provider,
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            task_key=task_key,
        )
        try:
            return _loads_json_content(content)
        except json.JSONDecodeError as exc:
            _report(progress, "model_parse", max_progress - 1, "模型返回 JSON 不完整，正在尝试修复返回包")
            return _repair_json_content(
                provider,
                content,
                error=exc,
                expected_key=_expected_payload_key(messages),
                timeout=timeout,
                task_key=task_key,
            )
    finally:
        stop.set()


def _repair_json_content(
    provider: LlmProvider,
    content: str,
    *,
    error: json.JSONDecodeError,
    expected_key: str,
    timeout: float,
    task_key: TaskParameterKey,
) -> object:
    repaired = _chat_text(
        provider,
        [
            {
                "role": "system",
                "content": (
                    "You repair malformed JSON. Return valid JSON only. Do not add new facts. "
                    "If an item is incomplete, discard that item."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"The JSON parser failed with: {error.msg} at line {error.lineno}, column {error.colno}.\n"
                    f"Return a valid JSON object with top-level key \"{expected_key}\". "
                    "Keep only complete recoverable items from the malformed payload.\n\n"
                    f"Malformed payload:\n{_trim_for_repair(content)}"
                ),
            },
        ],
        temperature=0,
        max_tokens=5000,
        timeout=timeout,
        task_key=task_key,
    )
    try:
        return _loads_json_content(repaired)
    except json.JSONDecodeError as repair_exc:
        raise ValueError(
            "模型返回了无法解析的 JSON，自动修复也失败；"
            f"原始错误在 line {error.lineno}, column {error.colno}: {error.msg}; "
            f"修复后错误在 line {repair_exc.lineno}, column {repair_exc.colno}: {repair_exc.msg}"
        ) from repair_exc


def _expected_payload_key(messages: list[dict[str, str]]) -> str:
    content = "\n".join(message["content"] for message in messages)
    if "\"background\"" in content:
        return "background"
    return "patches" if "\"patches\"" in content else "candidates"


def _trim_for_repair(content: str, limit: int = 24000) -> str:
    if len(content) <= limit:
        return content
    return f"{content[: limit // 2]}\n...truncated middle...\n{content[-limit // 2 :]}"


def _scaled_progress(start: int, end: int, index: int, total: int) -> int:
    if total <= 0:
        return start
    return max(start, min(end, round(start + (end - start) * index / total)))


def _candidate_max_tokens(chunk: list[TranscriptSegment], *, search_enabled: bool) -> int:
    base = 2600 if search_enabled else 2200
    per_line = 18 if search_enabled else 14
    return min(8000, base + len(chunk) * per_line)


def _chunk_transcript(
    transcript: list[TranscriptSegment],
    *,
    size: int = 120,
) -> list[tuple[int, list[TranscriptSegment]]]:
    return [(index, transcript[index : index + size]) for index in range(0, len(transcript), size)]


def _scan_chunks(transcript: list[TranscriptSegment]) -> list[tuple[int, list[TranscriptSegment]]]:
    if not transcript:
        return []
    chunk_size = max(1, math.ceil(len(transcript) / _target_scan_chunk_count(len(transcript))))
    return _chunk_transcript(transcript, size=chunk_size)


def _target_scan_chunk_count(segment_count: int) -> int:
    if segment_count <= 120:
        return 1
    if segment_count <= 240:
        return 2
    if segment_count <= 1000:
        return DEFAULT_SCAN_CHUNKS
    return min(MAX_SCAN_CHUNKS, max(DEFAULT_SCAN_CHUNKS, math.ceil(segment_count / 360)))


def _format_indexed_transcript(transcript: list[TranscriptSegment], *, start_index: int = 0) -> str:
    return "\n".join(
        f"[{start_index + index} | {_format_time(segment.start)}-{_format_time(segment.end)}] {segment.text}"
        for index, segment in enumerate(transcript)
    )


def _format_time(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    total_seconds, milliseconds = divmod(total_ms, 1000)
    minutes, second = divmod(total_seconds, 60)
    hours, minute = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minute:02d}:{second:02d}.{milliseconds:03d}"
    return f"{minute:02d}:{second:02d}.{milliseconds:03d}"


def _coerce_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _coerce_confidence(value: object) -> float:
    try:
        confidence = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if confidence > 1 and confidence <= 100:
        confidence = confidence / 100
    return max(0.0, min(1.0, confidence))


def _format_only_change(left: str, right: str) -> bool:
    return _normalize_for_format_check(left) == _normalize_for_format_check(right)


def _looks_like_mojibake(value: str) -> bool:
    if "\ufffd" in value:
        return True
    if re.search(r"[ÃÂ][\x80-\xffA-Za-z]", value):
        return True
    indicators = sum(value.count(character) for character in "äåæçèêëìíîïðñòóôõöøùúûüýþÿœ€")
    return indicators >= 2 and any(character in value for character in "äåæçè")


def _normalize_for_format_check(value: str) -> str:
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE).casefold()


def _patch_id(segment_index: int, original: str, corrected: str) -> str:
    digest = hashlib.sha1(f"{segment_index}\n{original}\n{corrected}".encode("utf-8")).hexdigest()[:10]
    return f"asr-{segment_index}-{digest}"


def _context_text(context: dict[str, object] | None) -> str:
    if not context:
        return "None"
    lines = []
    for key in (
        "title",
        "metadata_title",
        "collection_title",
        "uploader",
        "channel",
        "creator",
        "description",
        "user_context",
        "source_url",
        "webpage_url",
        "extractor",
        "language",
        "playlist_title",
        "playlist_index",
        "duration",
        "subtitles",
        "automatic_captions",
    ):
        value = context.get(key)
        if value not in (None, "", [], {}):
            lines.append(f"- {key}: {value}")
    return "\n".join(lines) if lines else "None"


def _output_language_name(output_language: OutputLanguage) -> str:
    if output_language == "zh-CN":
        return "Simplified Chinese"
    if output_language == "ja":
        return "Japanese"
    return "English"


def _report(progress: ProgressCallback | None, phase: str, value: int, message: str) -> None:
    if progress:
        progress(phase, value, message)
