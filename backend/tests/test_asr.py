import re

from course_navigator.ai import LlmProvider
from course_navigator.asr import suggest_asr_corrections
from course_navigator.models import AsrCorrectionSearchConfig, TranscriptSegment


def test_direct_asr_correction_uses_few_scan_batches_and_final_patch_review(monkeypatch):
    chat_calls = []
    timeouts = []
    progress_messages = []

    def fake_chat_text(provider, messages, **kwargs):
        timeouts.append(kwargs.get("timeout"))
        user_message = messages[-1]["content"]
        chat_calls.append(user_message)
        if "Candidate errors:" in user_message:
            assert '"candidates"' not in user_message
            assert '"asr_text"' not in user_message
            assert "Write reason and evidence in Simplified Chinese" in user_message
            assert "Do not write reason or evidence in English" in user_message
            assert "Preserve valid acronyms, abbreviations, shorthand names, and spoken aliases" in user_message
            return '{"patches":[{"segment_index":0,"original_text":"noba dek","corrected_text":"NovaDeck","confidence":0.94,"reason":"附加参考信息和上下文都指向 NovaDeck。","evidence":"用户参考信息。"}]}'
        match = re.search(r"\[(\d+) \|", user_message)
        segment_index = int(match.group(1)) if match else 0
        return f'{{"c":[{{"i":{segment_index},"f":"noba dek","t":"NovaDeck","k":"product","r":"user ref","c":0.92,"q":[],"p":1}}]}}'

    monkeypatch.setattr("course_navigator.asr._chat_text", fake_chat_text)
    transcript = [
        TranscriptSegment(start=index, end=index + 0.5, text="noba dek" if index == 0 else f"line {index}")
        for index in range(4300)
    ]
    provider = LlmProvider(base_url="https://api.example.com/v1", api_key="sk-test", model="model")

    suggestions = suggest_asr_corrections(
        title="NovaDeck interview",
        transcript=transcript,
        provider=provider,
        search_config=AsrCorrectionSearchConfig(enabled=False),
        context={"user_context": "noba dek 应校正为 NovaDeck"},
        progress=lambda phase, progress, message: progress_messages.append(message),
    )

    candidate_calls = [message for message in chat_calls if "Return compact JSON only" in message]
    review_calls = [message for message in chat_calls if "Candidate errors:" in message]
    assert len(candidate_calls) == 12
    assert len(review_calls) == 1
    assert not any("/43" in message for message in progress_messages)
    assert all(timeout == 240 for timeout in timeouts)
    assert suggestions[0].original_text == "noba dek"
    assert suggestions[0].corrected_text == "NovaDeck"


def test_asr_correction_prompt_preserves_valid_spoken_abbreviations(monkeypatch):
    chat_calls = []

    def fake_chat_text(provider, messages, **kwargs):
        user_message = messages[-1]["content"]
        chat_calls.append(user_message)
        if "Candidate errors:" in user_message:
            assert "Do not expand a recognized shorthand to its full form" in user_message
            return '{"patches":[]}'
        assert "Do not flag a valid acronym, abbreviation, shorthand, or spoken alias" in user_message
        return '{"c":[{"i":0,"f":"ND","t":"NovaDeck","k":"acronym","r":"possible shorthand","c":0.95,"q":[],"p":1}]}'

    monkeypatch.setattr("course_navigator.asr._chat_text", fake_chat_text)
    provider = LlmProvider(base_url="https://api.example.com/v1", api_key="sk-test", model="model")

    suggestions = suggest_asr_corrections(
        title="Product walkthrough",
        transcript=[
            TranscriptSegment(start=0, end=1, text="后面我简称它为 ND"),
            TranscriptSegment(start=1, end=2, text="ND 的接口比较清楚"),
        ],
        provider=provider,
        search_config=AsrCorrectionSearchConfig(enabled=False),
        context={"user_context": "ND 是产品简称时不需要展开"},
    )

    assert suggestions == []


def test_asr_correction_uses_one_or_two_scan_batches_for_short_transcripts(monkeypatch):
    chat_calls = []

    def fake_chat_text(provider, messages, **kwargs):
        user_message = messages[-1]["content"]
        chat_calls.append(user_message)
        if "Candidate errors:" in user_message:
            return '{"patches":[{"segment_index":0,"original_text":"noba dek","corrected_text":"NovaDeck","confidence":0.94,"reason":"附加参考信息。","evidence":"用户参考信息。"}]}'
        return '{"c":[{"i":0,"f":"noba dek","t":"NovaDeck","k":"product","r":"user ref","c":0.92,"q":[],"p":1}]}'

    monkeypatch.setattr("course_navigator.asr._chat_text", fake_chat_text)
    provider = LlmProvider(base_url="https://api.example.com/v1", api_key="sk-test", model="model")

    suggest_asr_corrections(
        title="NovaDeck interview",
        transcript=[
            TranscriptSegment(start=index, end=index + 0.5, text="noba dek" if index == 0 else f"line {index}")
            for index in range(90)
        ],
        provider=provider,
        search_config=AsrCorrectionSearchConfig(enabled=False),
        context={"user_context": "noba dek 应校正为 NovaDeck"},
    )

    candidate_calls = [message for message in chat_calls if "Return compact JSON only" in message]
    assert len(candidate_calls) == 1


def test_search_correction_deduplicates_queries_and_uses_search_as_background(monkeypatch):
    chat_calls = []
    search_calls = []
    progress_messages = []

    def fake_chat_text(provider, messages, **kwargs):
        user_message = messages[-1]["content"]
        chat_calls.append(user_message)
        if "Search evidence to synthesize:" in user_message:
            assert "AtlasLM 9.8 is a current model family" in user_message
            return (
                '{"background":['
                '{"topic":"AtlasLM 9.8","summary":"AtlasLM 9.8 is a current model family.",'
                '"aliases":["AtlisLM 9.8"],"key_facts":["Search confirms AtlasLM 9.8 is valid."],'
                '"source_queries":["AtlasLM 9.8 model"],"confidence":0.98}'
                "]}"
            )
        if "Candidate errors:" in user_message:
            assert "Search background cards:" in user_message
            assert "additional trusted context" in user_message
            assert "AtlasLM 9.8 is a current model family" in user_message
            assert "AtlasLM 9.8 release notes" not in user_message
            return '{"patches":[{"segment_index":0,"original_text":"AtlisLM 9.8","corrected_text":"AtlasLM 9.8","confidence":0.98,"reason":"搜索背景确认 AtlasLM 9.8 是有效模型名。","evidence":"搜索结果确认 AtlasLM 9.8。"}]}'
        return (
            '{"c":['
            '{"i":0,"f":"AtlisLM 9.8","t":"AtlasLM 8","k":"model","r":"疑似模型名","c":0.95,"q":["AtlasLM 9.8 model","AtlasLM-9.8 model"],"p":1},'
            '{"i":1,"f":"AtlisLM 9.8","t":"AtlasLM 8","k":"model","r":"重复模型名","c":0.94,"q":["AtlasLM 9.8 model"],"p":1}'
            "]}"
        )

    def fake_search(query, config):
        search_calls.append(query)
        return [
            {
                "title": "AtlasLM 9.8 release notes",
                "url": "https://example.com/atlaslm-9-8",
                "snippet": "AtlasLM 9.8 is a current model family.",
                "source": "firecrawl",
                "rank": 1,
            }
        ]

    monkeypatch.setattr("course_navigator.asr._chat_text", fake_chat_text)
    monkeypatch.setattr("course_navigator.asr._search", fake_search)
    provider = LlmProvider(base_url="https://api.example.com/v1", api_key="sk-test", model="model")

    suggestions = suggest_asr_corrections(
        title="Model roadmap interview",
        transcript=[
            TranscriptSegment(start=0, end=1, text="这里提到 AtlisLM 9.8"),
            TranscriptSegment(start=1, end=2, text="再次说到 AtlisLM 9.8"),
        ],
        provider=provider,
        search_config=AsrCorrectionSearchConfig(enabled=True, provider="firecrawl", base_url="http://127.0.0.1:3002"),
        context={"user_context": "模型名称需要谨慎校正"},
        progress=lambda phase, progress, message: progress_messages.append(message),
    )

    assert search_calls == ["AtlasLM 9.8 model"]
    assert any("归一化" in message and "唯一术语" in message for message in progress_messages)
    assert suggestions[0].original_text == "AtlisLM 9.8"
    assert suggestions[0].corrected_text == "AtlasLM 9.8"
    assert suggestions[0].source == "search"


def test_search_results_are_summarized_into_background_cards_before_patch_review(monkeypatch):
    chat_calls = []
    search_calls = []

    def fake_chat_text(provider, messages, **kwargs):
        user_message = messages[-1]["content"]
        chat_calls.append(user_message)
        if "Search evidence to synthesize:" in user_message:
            assert "Raw lookup snippet A" in user_message
            assert "Raw lookup snippet B" in user_message
            return (
                '{"background":['
                '{"topic":"NovaDeck","summary":"NovaDeck is a documented product name used by the course speaker.",'
                '"aliases":["noba dek"],"key_facts":["The searched sources connect noba dek to NovaDeck."],'
                '"source_queries":["NovaDeck","noba dek"],"confidence":0.96}'
                "]}"
            )
        if "Candidate errors:" in user_message:
            assert "Search background cards:" in user_message
            assert "NovaDeck is a documented product name" in user_message
            assert "Raw lookup snippet" not in user_message
            return '{"patches":[{"segment_index":0,"original_text":"noba dek","corrected_text":"NovaDeck","confidence":0.96,"reason":"搜索背景确认产品名。","evidence":"背景卡确认 noba dek 对应 NovaDeck。"}]}'
        return (
            '{"c":['
            '{"i":0,"f":"noba dek","t":"NovaDeck","k":"product","r":"疑似产品名","c":0.95,"q":["NovaDeck","noba dek"],"p":1},'
            '{"i":1,"f":"product family","t":"","k":"term","r":"相关术语","c":0.91,"q":["NovaDeck product family"],"p":2}'
            "]}"
        )

    def fake_search(query, config):
        search_calls.append(query)
        return [
            {
                "title": f"{query} reference",
                "url": f"https://example.com/{query.replace(' ', '-')}",
                "snippet": f"Raw lookup snippet {'A' if len(search_calls) == 1 else 'B'} for {query}.",
                "source": "firecrawl",
                "rank": 1,
            }
        ]

    monkeypatch.setattr("course_navigator.asr._chat_text", fake_chat_text)
    monkeypatch.setattr("course_navigator.asr._search", fake_search)
    provider = LlmProvider(base_url="https://api.example.com/v1", api_key="sk-test", model="model")

    suggestions = suggest_asr_corrections(
        title="Product course",
        transcript=[
            TranscriptSegment(start=0, end=1, text="这里提到 noba dek"),
            TranscriptSegment(start=1, end=2, text="也谈到了 product family"),
        ],
        provider=provider,
        search_config=AsrCorrectionSearchConfig(enabled=True, provider="firecrawl", base_url="http://127.0.0.1:3002"),
        context={"user_context": "产品名需要保留大小写"},
    )

    assert set(search_calls) == {"NovaDeck", "noba dek", "NovaDeck product family"}
    assert len(search_calls) == 3
    assert any("Search evidence to synthesize:" in message for message in chat_calls)
    assert suggestions[0].corrected_text == "NovaDeck"


def test_asr_correction_repairs_malformed_model_json(monkeypatch):
    calls = []

    def fake_chat_text(provider, messages, **kwargs):
        content = messages[-1]["content"]
        calls.append(content)
        if "repair malformed JSON" in messages[0]["content"] or "Malformed payload:" in content:
            return '{"c":[{"i":0,"f":"noba dek","t":"NovaDeck","k":"product","r":"reference","c":0.94,"q":[],"p":1}]}'
        if "Candidate errors:" in content:
            return '{"patches":[{"segment_index":0,"original_text":"noba dek","corrected_text":"NovaDeck","confidence":0.94,"reason":"reference","evidence":"user"}]}'
        return '{"c":[{"i":0,"f":"noba dek","t":"NovaDeck","k":"product","r":"unterminated}'

    monkeypatch.setattr("course_navigator.asr._chat_text", fake_chat_text)
    provider = LlmProvider(base_url="https://api.example.com/v1", api_key="sk-test", model="model")

    suggestions = suggest_asr_corrections(
        title="NovaDeck interview",
        transcript=[TranscriptSegment(start=0, end=1, text="noba dek")],
        provider=provider,
        search_config=AsrCorrectionSearchConfig(enabled=False),
        context={"user_context": "noba dek 应校正为 NovaDeck"},
    )

    assert any("Malformed payload:" in call for call in calls)
    assert suggestions[0].corrected_text == "NovaDeck"


def test_asr_correction_drops_mojibake_patch_text(monkeypatch):
    def fake_chat_text(provider, messages, **kwargs):
        content = messages[-1]["content"]
        if "Candidate errors:" in content:
            return (
                '{"patches":['
                '{"segment_index":0,"original_text":"noba dek","corrected_text":"è@ä¸£ä¸ª","confidence":0.95,"reason":"乱码","evidence":"乱码"},'
                '{"segment_index":0,"original_text":"noba dek","corrected_text":"NovaDeck","confidence":0.95,"reason":"附加参考信息","evidence":"标题"}'
                "]} "
            )
        return '{"c":[{"i":0,"f":"noba dek","t":"NovaDeck","k":"product","r":"reference","c":0.94,"q":[],"p":1}]}'

    monkeypatch.setattr("course_navigator.asr._chat_text", fake_chat_text)
    provider = LlmProvider(base_url="https://api.example.com/v1", api_key="sk-test", model="model")

    suggestions = suggest_asr_corrections(
        title="NovaDeck interview",
        transcript=[TranscriptSegment(start=0, end=1, text="noba dek")],
        provider=provider,
        search_config=AsrCorrectionSearchConfig(enabled=False),
        context={"user_context": "noba dek 应校正为 NovaDeck"},
    )

    assert [suggestion.corrected_text for suggestion in suggestions] == ["NovaDeck"]
