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
            return '{"patches":[{"segment_index":0,"original_text":"open cloud","corrected_text":"OpenClaw","confidence":0.94,"reason":"附加参考信息和上下文都指向 OpenClaw。","evidence":"用户参考信息。"}]}'
        match = re.search(r"\[(\d+) \|", user_message)
        segment_index = int(match.group(1)) if match else 0
        return f'{{"c":[{{"i":{segment_index},"f":"open cloud","t":"OpenClaw","k":"product","r":"user ref","c":0.92,"q":[],"p":1}}]}}'

    monkeypatch.setattr("course_navigator.asr._chat_text", fake_chat_text)
    transcript = [
        TranscriptSegment(start=index, end=index + 0.5, text="open cloud" if index == 0 else f"line {index}")
        for index in range(4300)
    ]
    provider = LlmProvider(base_url="https://api.example.com/v1", api_key="sk-test", model="model")

    suggestions = suggest_asr_corrections(
        title="OpenClaw interview",
        transcript=transcript,
        provider=provider,
        search_config=AsrCorrectionSearchConfig(enabled=False),
        context={"user_context": "open cloud 应校正为 OpenClaw"},
        progress=lambda phase, progress, message: progress_messages.append(message),
    )

    candidate_calls = [message for message in chat_calls if "Return compact JSON only" in message]
    review_calls = [message for message in chat_calls if "Candidate errors:" in message]
    assert len(candidate_calls) == 12
    assert len(review_calls) == 1
    assert not any("/43" in message for message in progress_messages)
    assert all(timeout == 240 for timeout in timeouts)
    assert suggestions[0].original_text == "open cloud"
    assert suggestions[0].corrected_text == "OpenClaw"


def test_asr_correction_uses_one_or_two_scan_batches_for_short_transcripts(monkeypatch):
    chat_calls = []

    def fake_chat_text(provider, messages, **kwargs):
        user_message = messages[-1]["content"]
        chat_calls.append(user_message)
        if "Candidate errors:" in user_message:
            return '{"patches":[{"segment_index":0,"original_text":"open cloud","corrected_text":"OpenClaw","confidence":0.94,"reason":"附加参考信息。","evidence":"用户参考信息。"}]}'
        return '{"c":[{"i":0,"f":"open cloud","t":"OpenClaw","k":"product","r":"user ref","c":0.92,"q":[],"p":1}]}'

    monkeypatch.setattr("course_navigator.asr._chat_text", fake_chat_text)
    provider = LlmProvider(base_url="https://api.example.com/v1", api_key="sk-test", model="model")

    suggest_asr_corrections(
        title="OpenClaw interview",
        transcript=[
            TranscriptSegment(start=index, end=index + 0.5, text="open cloud" if index == 0 else f"line {index}")
            for index in range(90)
        ],
        provider=provider,
        search_config=AsrCorrectionSearchConfig(enabled=False),
        context={"user_context": "open cloud 应校正为 OpenClaw"},
    )

    candidate_calls = [message for message in chat_calls if "Return compact JSON only" in message]
    assert len(candidate_calls) == 1


def test_asr_correction_repairs_malformed_model_json(monkeypatch):
    calls = []

    def fake_chat_text(provider, messages, **kwargs):
        content = messages[-1]["content"]
        calls.append(content)
        if "repair malformed JSON" in messages[0]["content"] or "Malformed payload:" in content:
            return '{"c":[{"i":0,"f":"open cloud","t":"OpenClaw","k":"product","r":"reference","c":0.94,"q":[],"p":1}]}'
        if "Candidate errors:" in content:
            return '{"patches":[{"segment_index":0,"original_text":"open cloud","corrected_text":"OpenClaw","confidence":0.94,"reason":"reference","evidence":"user"}]}'
        return '{"c":[{"i":0,"f":"open cloud","t":"OpenClaw","k":"product","r":"unterminated}'

    monkeypatch.setattr("course_navigator.asr._chat_text", fake_chat_text)
    provider = LlmProvider(base_url="https://api.example.com/v1", api_key="sk-test", model="model")

    suggestions = suggest_asr_corrections(
        title="OpenClaw interview",
        transcript=[TranscriptSegment(start=0, end=1, text="open cloud")],
        provider=provider,
        search_config=AsrCorrectionSearchConfig(enabled=False),
        context={"user_context": "open cloud 应校正为 OpenClaw"},
    )

    assert any("Malformed payload:" in call for call in calls)
    assert suggestions[0].corrected_text == "OpenClaw"


def test_asr_correction_drops_mojibake_patch_text(monkeypatch):
    def fake_chat_text(provider, messages, **kwargs):
        content = messages[-1]["content"]
        if "Candidate errors:" in content:
            return (
                '{"patches":['
                '{"segment_index":0,"original_text":"open cloud","corrected_text":"è@ä¸£ä¸ª","confidence":0.95,"reason":"乱码","evidence":"乱码"},'
                '{"segment_index":0,"original_text":"open cloud","corrected_text":"OpenClaw","confidence":0.95,"reason":"附加参考信息","evidence":"标题"}'
                "]} "
            )
        return '{"c":[{"i":0,"f":"open cloud","t":"OpenClaw","k":"product","r":"reference","c":0.94,"q":[],"p":1}]}'

    monkeypatch.setattr("course_navigator.asr._chat_text", fake_chat_text)
    provider = LlmProvider(base_url="https://api.example.com/v1", api_key="sk-test", model="model")

    suggestions = suggest_asr_corrections(
        title="OpenClaw interview",
        transcript=[TranscriptSegment(start=0, end=1, text="open cloud")],
        provider=provider,
        search_config=AsrCorrectionSearchConfig(enabled=False),
        context={"user_context": "open cloud 应校正为 OpenClaw"},
    )

    assert [suggestion.corrected_text for suggestion in suggestions] == ["OpenClaw"]
