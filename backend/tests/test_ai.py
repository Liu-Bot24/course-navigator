import pytest

import course_navigator.ai as ai
from course_navigator.ai import LlmProvider, _chat_text, generate_study_material
from course_navigator.models import OutlineNode, StudyMaterial, TimeRange, TranscriptSegment, VideoMetadata


def test_generate_study_material_fallback_preserves_transcript_detail():
    transcript = [
        TranscriptSegment(start=0, end=10, text="This lesson starts with novices."),
        TranscriptSegment(start=10, end=20, text="Power users iterate on prompts."),
        TranscriptSegment(start=20, end=30, text="The key is to refine context."),
    ]

    study = generate_study_material(
        title="Prompting Lesson",
        transcript=transcript,
        provider=None,
    )

    assert "Prompting Lesson" in study.one_line
    assert len(study.time_map) >= 1
    assert study.time_map[0].start == 0
    assert study.outline[0].children
    assert "Power users iterate on prompts." in study.high_fidelity_text
    assert "00:10" in study.high_fidelity_text


def test_generate_study_material_fallback_can_use_chinese_output():
    transcript = [
        TranscriptSegment(start=0, end=8, text="This lesson explains prompt iteration."),
        TranscriptSegment(start=8, end=16, text="Examples help users compare outputs."),
    ]

    study = generate_study_material(
        title="Prompting Lesson",
        transcript=transcript,
        provider=None,
        output_language="zh-CN",
    )

    assert "包含" in study.one_line
    assert study.time_map[0].title.startswith("第 1 段")
    assert "思考" in study.thought_prompts[0]
    assert "未配置模型" in study.high_fidelity_text
    assert study.translated_transcript == []


def test_chinese_one_line_does_not_reuse_english_context_summary():
    summary = "This is a weekly AI large model news report for May 2026."

    one_line = ai._one_line_from_context("Weekly AI News", [{"title": "OpenAI news"}], "zh-CN", summary)

    assert one_line == "这门课程围绕「Weekly AI News」展开。"


def test_generate_study_material_handles_empty_transcript():
    study = generate_study_material(title="Empty", transcript=[], provider=None)

    assert study.one_line == "No transcript is available for Empty yet."
    assert study.time_map == []
    assert study.outline == []


def test_long_transcript_provider_path_builds_layered_study_material(monkeypatch):
    transcript = [
        TranscriptSegment(start=index * 2, end=index * 2 + 2, text=f"source line {index}")
        for index in range(81)
    ]
    translated = [
        TranscriptSegment(start=segment.start, end=segment.end, text=f"译文 {index}")
        for index, segment in enumerate(transcript)
    ]
    blocks = [
        {
            "id": "block-1",
            "start": 0,
            "end": 80,
            "title": "第一部分：AI 入门",
            "summary": "解释 AI 的基本直觉。",
            "priority": "focus",
            "key_points": ["AI 会改变工作方式", "非技术学习者也可以使用 AI"],
            "detailed_notes": "这里是经过解释的解读，不是字幕拼接。",
            "high_fidelity_text": "这里是可以替代观看的详解学习稿。",
        },
        {
            "id": "block-2",
            "start": 80,
            "end": 162,
            "title": "第二部分：应用判断",
            "summary": "判断哪些场景适合使用 AI。",
            "priority": "skim",
            "key_points": ["识别任务边界"],
            "detailed_notes": "继续解释课程里的例子和转折。",
            "high_fidelity_text": "保留顺序和细节的学习文本。",
        },
    ]

    monkeypatch.setattr(ai, "_generate_translation_context", lambda *args, **kwargs: "课程讲 AI 基础。")
    monkeypatch.setattr(ai, "_translate_transcript_with_provider", lambda *args, **kwargs: translated)
    def fake_blocks(**kwargs):
        kwargs["partial_ranges"](
            [
                TimeRange(
                    start=0,
                    end=162,
                    title="先出的大纲骨架",
                    summary="先保存可浏览的课程结构。",
                    priority="focus",
                )
            ]
        )
        return blocks

    monkeypatch.setattr(ai, "_generate_learning_blocks_with_provider", fake_blocks)
    monkeypatch.setattr(
        ai,
        "_generate_outline_with_provider",
        lambda *args, **kwargs: [
            OutlineNode(
                id="outline-1",
                start=0,
                end=162,
                title="课程主线",
                summary="从直觉到应用判断。",
                children=[],
            )
        ],
    )
    monkeypatch.setattr(
        ai,
        "_generate_guidance_with_provider",
        lambda *args, **kwargs: {
            "prerequisites": ["了解什么是任务自动化"],
            "thought_prompts": ["哪些工作流适合迁移？"],
            "review_suggestions": ["回看应用判断片段"],
            "beginner_focus": ["小白先听基本概念。"],
            "experienced_guidance": ["有经验者可略过定义，重点复习迁移判断。"],
            "one_line": "这门课用 AI 应用示例帮助学习者理解任务自动化的判断方法。",
        },
    )
    progress_events: list[tuple[str, int, str]] = []

    study = generate_study_material(
        title="AI for Everyone",
        transcript=transcript,
        provider=LlmProvider(base_url="https://example.test/v1", api_key="sk-test", model="test-model"),
        output_language="zh-CN",
        progress=lambda phase, value, message: progress_events.append((phase, value, message)),
    )

    assert study.translated_transcript == translated
    assert study.time_map[0].title == "第一部分：AI 入门"
    assert study.outline[0].title == "课程主线"
    assert "经过解释的解读" in study.detailed_notes
    assert "详解学习稿" in study.high_fidelity_text
    assert study.one_line == "这门课用 AI 应用示例帮助学习者理解任务自动化的判断方法。"
    assert study.prerequisites == ["了解什么是任务自动化"]
    assert study.beginner_focus == ["小白先听基本概念。"]
    assert study.experienced_guidance == ["有经验者可略过定义，重点复习迁移判断。"]
    assert not any("翻译上下文摘要" in event[2] for event in progress_events)
    assert [event[0] for event in progress_events] == [
        "preparing",
        "summary",
        "guide",
        "translation",
        "segmentation",
        "outline",
        "assembly",
    ]


def test_full_study_generation_reports_partial_study_sections(monkeypatch):
    transcript = [
        TranscriptSegment(start=index * 2, end=index * 2 + 2, text=f"source line {index}")
        for index in range(81)
    ]
    translated = [
        TranscriptSegment(start=segment.start, end=segment.end, text=f"译文 {index}")
        for index, segment in enumerate(transcript)
    ]
    blocks = [
        {
            "id": "block-1",
            "start": 0,
            "end": 162,
            "title": "课程主线",
            "summary": "解释课程。",
            "priority": "focus",
            "key_points": ["重点"],
            "detailed_notes": "新解读",
            "high_fidelity_text": "新详解",
        }
    ]

    monkeypatch.setattr(ai, "_generate_translation_context", lambda *args, **kwargs: "课程上下文。")
    monkeypatch.setattr(ai, "_translate_transcript_with_provider", lambda *args, **kwargs: translated)
    def fake_blocks(**kwargs):
        kwargs["partial_ranges"](
            [
                TimeRange(
                    start=0,
                    end=162,
                    title="先出的大纲骨架",
                    summary="先保存可浏览的课程结构。",
                    priority="focus",
                )
            ]
        )
        return blocks

    monkeypatch.setattr(ai, "_generate_learning_blocks_with_provider", fake_blocks)
    monkeypatch.setattr(
        ai,
        "_generate_guidance_with_provider",
        lambda *args, **kwargs: {
            "prerequisites": ["先出的导览"],
            "thought_prompts": ["先出的思考题"],
            "review_suggestions": ["先出的复习建议"],
        },
    )
    monkeypatch.setattr(
        ai,
        "_generate_outline_with_provider",
        lambda *args, **kwargs: [
            OutlineNode(id="block-1", start=0, end=162, title="新大纲", summary="大纲摘要", children=[]),
        ],
    )
    partials: list[StudyMaterial] = []

    study = generate_study_material(
        title="AI for Everyone",
        transcript=transcript,
        provider=LlmProvider(base_url="https://example.test/v1", api_key="sk-test", model="test-model"),
        output_language="zh-CN",
        partial_study=partials.append,
    )

    assert partials[0].prerequisites == ["先出的导览"]
    assert partials[0].time_map == []
    assert partials[1].outline[0].title == "先出的大纲骨架"
    assert partials[1].detailed_notes == ""
    assert partials[2].detailed_notes == "00:00-02:42 课程主线\n新解读"
    assert partials[1].outline
    assert partials[-1].outline[0].title == "新大纲"
    assert study.outline[0].title == "新大纲"


def test_anthropic_provider_base_url_adds_v1_for_official_endpoint(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"content": [{"type": "text", "text": "ok"}]}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("course_navigator.ai.httpx.post", fake_post)

    text = _chat_text(
        LlmProvider(
            base_url="https://api.anthropic.com",
            api_key="sk-test",
            model="LongContext-M2",
            provider_type="anthropic",
        ),
        [{"role": "system", "content": "Reply briefly."}, {"role": "user", "content": "Health check"}],
        temperature=0,
        max_tokens=16,
        timeout=30,
    )

    assert text == "ok"
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "sk-test"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"


def test_anthropic_provider_base_url_adds_v1_for_anthropic_path_prefix(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"content": [{"type": "text", "text": "ok"}]}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        return Response()

    monkeypatch.setattr("course_navigator.ai.httpx.post", fake_post)

    text = _chat_text(
        LlmProvider(
            base_url="https://token-plan-cn.xiaomimimo.com/anthropic",
            api_key="sk-test",
            model="mimo-v2.5-pro",
            provider_type="anthropic",
        ),
        [{"role": "user", "content": "Health check"}],
        temperature=0,
        max_tokens=16,
        timeout=30,
    )

    assert text == "ok"
    assert captured["url"] == "https://token-plan-cn.xiaomimimo.com/anthropic/v1/messages"


def test_long_transcript_uses_role_specific_model_slots(monkeypatch):
    transcript = [
        TranscriptSegment(start=index * 2, end=index * 2 + 2, text=f"source line {index}")
        for index in range(81)
    ]
    blocks = [
        {
            "id": "block-1",
            "start": 0,
            "end": 162,
            "title": "课程主线",
            "summary": "解释课程。",
            "priority": "focus",
            "key_points": ["重点"],
            "detailed_notes": "解读",
            "high_fidelity_text": "详解文本",
        }
    ]
    used_models: list[tuple[str, str]] = []

    def fake_context(title, transcript, provider, output_language, metadata=None):
        used_models.append(("context", provider.model))
        return "课程摘要"

    def fake_translate(**kwargs):
        used_models.append(("translation", kwargs["provider"].model))
        return [
            TranscriptSegment(start=segment.start, end=segment.end, text=f"译文 {index}")
            for index, segment in enumerate(transcript)
        ]

    def fake_blocks(**kwargs):
        used_models.append(("learning_blocks", kwargs["provider"].model))
        return blocks

    def fake_outline(title, blocks, context_summary, provider, output_language):
        used_models.append(("outline", provider.model))
        return []

    def fake_guidance(title, transcript, context_summary, provider, output_language):
        used_models.append(("guide", provider.model))
        return {}

    monkeypatch.setattr(ai, "_generate_translation_context", fake_context)
    monkeypatch.setattr(ai, "_translate_transcript_with_provider", fake_translate)
    monkeypatch.setattr(ai, "_generate_learning_blocks_with_provider", fake_blocks)
    monkeypatch.setattr(ai, "_generate_outline_with_provider", fake_outline)
    monkeypatch.setattr(ai, "_generate_guidance_with_provider", fake_guidance)

    providers = ai.LlmProviderSet(
        translation=LlmProvider(base_url="https://example.test/v1", api_key="sk-test", model="fast-translate"),
        learning=LlmProvider(base_url="https://example.test/v1", api_key="sk-test", model="deep-learning"),
        global_provider=LlmProvider(base_url="https://example.test/v1", api_key="sk-test", model="long-global"),
    )

    generate_study_material(
        title="AI for Everyone",
        transcript=transcript,
        provider=providers,
        output_language="zh-CN",
    )

    assert used_models == [
        ("context", "long-global"),
        ("guide", "long-global"),
        ("translation", "fast-translate"),
        ("learning_blocks", "deep-learning"),
        ("outline", "long-global"),
    ]


def test_transcript_translation_fails_when_repair_cannot_fill_gaps(monkeypatch):
    transcript = [
        TranscriptSegment(start=index, end=index + 1, text=f"source sentence that should be translated {index}")
        for index in range(31)
    ]

    def fake_translate_chunk(title, chunk, provider, context_summary, output_language):
        if chunk[0].start == 0:
            raise RuntimeError("temporary provider failure")
        return [
            TranscriptSegment(start=segment.start, end=segment.end, text=f"译文 {segment.text}")
            for segment in chunk
        ]

    monkeypatch.setattr(ai, "_translate_chunk_with_provider", fake_translate_chunk)

    with pytest.raises(RuntimeError, match="字幕翻译不完整"):
        ai._translate_transcript_with_provider(
            title="Lesson",
            transcript=transcript,
            provider=LlmProvider(base_url="https://example.test/v1", api_key="sk-test", model="test-model"),
            context_summary="summary",
            output_language="zh-CN",
        )


def test_transcript_translation_repairs_source_echo_segments(monkeypatch):
    transcript = [
        TranscriptSegment(
            start=index,
            end=index + 1,
            text=f"this source sentence should become translated {index}",
        )
        for index in range(5)
    ]
    calls = 0

    def fake_translate_chunk(title, chunk, provider, context_summary, output_language):
        nonlocal calls
        calls += 1
        if calls == 1:
            return [
                TranscriptSegment(start=segment.start, end=segment.end, text=segment.text)
                for segment in chunk
            ]
        return [
            TranscriptSegment(start=segment.start, end=segment.end, text=f"译文 {segment.text}")
            for segment in chunk
        ]

    monkeypatch.setattr(ai, "_translate_chunk_with_provider", fake_translate_chunk)

    translated = ai._translate_transcript_with_provider(
        title="Lesson",
        transcript=transcript,
        provider=LlmProvider(base_url="https://example.test/v1", api_key="sk-test", model="test-model"),
        context_summary="summary",
        output_language="zh-CN",
    )

    assert calls == 2
    assert [segment.text for segment in translated] == [
        f"译文 this source sentence should become translated {index}"
        for index in range(5)
    ]


def test_transcript_translation_repairs_malformed_model_json(monkeypatch):
    calls = []

    def fake_chat_text(provider, messages, **kwargs):
        calls.append(messages[-1]["content"])
        if "Malformed payload:" in messages[-1]["content"]:
            return (
                '{"translated_transcript":['
                '{"start":0,"end":1,"text":"今天我们介绍 Imagen 2.0。"}'
                "]} "
            )
        return '{"translated_transcript":[{"start":0,"end":1,"text":"今天我们介绍'

    monkeypatch.setattr(ai, "_chat_text", fake_chat_text)

    translated = ai._translate_chunk_with_provider(
        title="This is ChatGPT Images 2.0",
        chunk=[TranscriptSegment(start=0, end=1, text="Today, we are launching Imagen 2.0.")],
        provider=LlmProvider(
            base_url="https://example.test/anthropic",
            api_key="sk-test",
            model="mimo-v2.5-pro",
            provider_type="anthropic",
        ),
        context_summary="The video introduces Imagen 2.0.",
        output_language="zh-CN",
    )

    assert any("Malformed payload:" in call for call in calls)
    assert translated == [TranscriptSegment(start=0, end=1, text="今天我们介绍 Imagen 2.0。")]


def test_translation_context_repairs_malformed_model_json(monkeypatch):
    calls = []

    def fake_chat_text(provider, messages, **kwargs):
        calls.append(messages[-1]["content"])
        if "Malformed payload:" in messages[-1]["content"]:
            return '{"summary":"这段课程介绍 ChatGPT Images 2.0 和 Imagen 2.0。"}'
        return '{"summary":"这段课程介绍 ChatGPT Images'

    monkeypatch.setattr(ai, "_chat_text", fake_chat_text)

    summary = ai._generate_translation_context(
        title="This is ChatGPT Images 2.0",
        transcript=[TranscriptSegment(start=0, end=1, text="Today, we are launching Imagen 2.0.")],
        provider=LlmProvider(
            base_url="https://example.test/anthropic",
            api_key="sk-test",
            model="mimo-v2.5-pro",
            provider_type="anthropic",
        ),
        output_language="zh-CN",
    )

    assert any("Malformed payload:" in call for call in calls)
    assert summary == "这段课程介绍 ChatGPT Images 2.0 和 Imagen 2.0。"


def test_transcript_translation_repairs_short_source_echo_segments():
    source = TranscriptSegment(start=0, end=1, text="go.")
    echoed = TranscriptSegment(start=0, end=1, text="go.")

    assert ai._needs_translation_repair(source, echoed, output_language="zh-CN")


def test_transcript_translation_skips_when_source_language_matches_output():
    transcript = [
        TranscriptSegment(start=0, end=1, text="这是中文视频。"),
        TranscriptSegment(start=1, end=2, text="不需要再翻译。"),
    ]
    partials: list[list[TranscriptSegment]] = []

    translated = ai.translate_transcript_material(
        title="中文课程",
        transcript=transcript,
        provider=None,
        output_language="zh-CN",
        source_language="zh",
        partial_translation=lambda value: partials.append(value),
    )

    assert translated == transcript
    assert partials[-1] == transcript


def test_transcript_translation_skips_when_transcript_already_matches_output_language():
    transcript = [
        TranscriptSegment(start=0, end=1, text="这是一个中文视频，内容已经是中文。"),
        TranscriptSegment(start=1, end=2, text="这里继续介绍课程的核心观点。"),
    ]
    partials = []

    translated = ai.translate_transcript_material(
        title="中文课程",
        transcript=transcript,
        provider=None,
        output_language="zh-CN",
        partial_translation=lambda value: partials.append(value),
    )

    assert translated == transcript
    assert partials[-1] == transcript


def test_transcript_translation_context_generation_receives_video_metadata(monkeypatch):
    transcript = [
        TranscriptSegment(start=0, end=2, text="This lesson introduces prompt iteration."),
        TranscriptSegment(start=2, end=4, text="It compares two model answers."),
    ]
    captured = {}

    def fake_context(title, transcript, provider, output_language, metadata=None):
        captured["metadata"] = metadata
        return "课程由 Sample Teacher 发布，介绍 D-tail。"

    monkeypatch.setattr(ai, "_generate_translation_context", fake_context)
    monkeypatch.setattr(
        ai,
        "_translate_transcript_with_provider",
        lambda **kwargs: [
            TranscriptSegment(start=0, end=2, text="本课介绍提示词迭代。"),
            TranscriptSegment(start=2, end=4, text="它比较两个模型回答。"),
        ],
    )

    translated = ai.translate_transcript_material(
        title="Prompting Lesson",
        transcript=transcript,
        provider=LlmProvider(base_url="https://example.test/v1", api_key="sk-test", model="test-model"),
        output_language="zh-CN",
        source_language="en",
        metadata=VideoMetadata(
            id="abc123",
            title="Official Prompting Lesson",
            uploader="Sample Teacher",
            channel="Sample Channel",
            description="A trusted upload summary mentioning D-tail terminology.",
            webpage_url="https://www.youtube.com/watch?v=abc123",
            extractor="youtube",
        ),
    )

    assert translated[0].text == "本课介绍提示词迭代。"
    assert captured["metadata"].uploader == "Sample Teacher"
    assert captured["metadata"].description == "A trusted upload summary mentioning D-tail terminology."


def test_translation_context_prompt_describes_transcript_context_not_translation(monkeypatch):
    captured = {}

    def fake_chat_text(provider, messages, **kwargs):
        captured["messages"] = messages
        return '{"summary":"课程讨论提示工程。"}'

    monkeypatch.setattr(ai, "_chat_text", fake_chat_text)

    summary = ai._generate_translation_context(
        title="提示工程课程",
        transcript=[TranscriptSegment(start=0, end=2, text="这里介绍提示词迭代。")],
        provider=LlmProvider(base_url="https://example.test/v1", api_key="sk-test", model="test-model"),
        output_language="zh-CN",
    )

    system_prompt = captured["messages"][0]["content"]
    assert summary == "课程讨论提示工程。"
    assert "translation" not in system_prompt.lower()
    assert "Simplified Chinese" not in system_prompt


def test_translation_context_prompt_includes_trusted_video_metadata(monkeypatch):
    captured = {}

    def fake_chat_text(provider, messages, **kwargs):
        captured["messages"] = messages
        return '{"summary":"课程由 Sample Teacher 发布，介绍 D-tail。"}'

    monkeypatch.setattr(ai, "_chat_text", fake_chat_text)

    summary = ai._generate_translation_context(
        title="提示工程课程",
        transcript=[TranscriptSegment(start=0, end=2, text="这里介绍提示词迭代。")],
        provider=LlmProvider(base_url="https://example.test/v1", api_key="sk-test", model="test-model"),
        output_language="zh-CN",
        metadata=VideoMetadata(
            id="abc123",
            title="Official Sample Lesson",
            uploader="Sample Teacher",
            channel="Sample Channel",
            creator="Sample Creator",
            description="A trusted upload summary mentioning D-tail terminology.",
            webpage_url="https://www.youtube.com/watch?v=abc123",
            extractor="youtube",
        ),
    )

    prompt = captured["messages"][1]["content"]
    assert summary == "课程由 Sample Teacher 发布，介绍 D-tail。"
    assert "Trusted video metadata" in prompt
    assert "Sample Teacher" in prompt
    assert "A trusted upload summary mentioning D-tail terminology." in prompt


def test_translation_context_prompt_uses_full_transcript(monkeypatch):
    captured = {}
    transcript = [
        TranscriptSegment(start=index * 3, end=index * 3 + 3, text=f"summary line {index}")
        for index in range(100)
    ]

    def fake_chat_text(provider, messages, **kwargs):
        captured["messages"] = messages
        return '{"summary":"课程完整摘要。"}'

    monkeypatch.setattr(ai, "_chat_text", fake_chat_text)

    ai._generate_translation_context(
        title="长课程",
        transcript=transcript,
        provider=LlmProvider(base_url="https://example.test/v1", api_key="sk-test", model="test-model"),
        output_language="zh-CN",
    )

    prompt = captured["messages"][1]["content"]
    assert "Full transcript:" in prompt
    assert "Transcript sample:" not in prompt
    assert "1. [00:00-00:03] summary line 0" in prompt
    assert "100. [04:57-05:00] summary line 99" in prompt


def test_transcript_translation_can_translate_unknown_source_to_english(monkeypatch):
    transcript = [
        TranscriptSegment(start=0, end=2, text="这里介绍提示词迭代。"),
        TranscriptSegment(start=2, end=4, text="然后比较两个输出。"),
    ]

    monkeypatch.setattr(ai, "_generate_translation_context", lambda *args, **kwargs: "课程讨论提示工程。")
    monkeypatch.setattr(
        ai,
        "_translate_transcript_with_provider",
        lambda **kwargs: [
            TranscriptSegment(start=0, end=2, text="This introduces prompt iteration."),
            TranscriptSegment(start=2, end=4, text="Then it compares two outputs."),
        ],
    )

    translated = ai.translate_transcript_material(
        title="提示工程课程",
        transcript=transcript,
        provider=LlmProvider(base_url="https://example.test/v1", api_key="sk-test", model="test-model"),
        output_language="en",
        source_language=None,
    )

    assert translated[0].text == "This introduces prompt iteration."


def test_title_translation_can_translate_to_english(monkeypatch):
    captured = {}

    def fake_chat_json(provider, messages, **kwargs):
        captured["task_key"] = kwargs["task_key"]
        captured["messages"] = messages
        return {"translated_title": "Prompt Engineering Course"}

    monkeypatch.setattr(ai, "_chat_json", fake_chat_json)

    translated = ai._translate_title_with_provider(
        title="提示工程课程",
        context_summary="课程讨论提示词迭代。",
        provider=LlmProvider(base_url="https://example.test/v1", api_key="sk-test", model="test-model"),
        output_language="en",
    )

    assert translated == "Prompt Engineering Course"
    assert captured["task_key"] == "title_translation"


def test_transcript_translation_reports_partial_chunks(monkeypatch):
    transcript = [
        TranscriptSegment(start=index, end=index + 1, text=f"source {index}")
        for index in range(61)
    ]

    def fake_translate_chunk(title, chunk, provider, context_summary, output_language):
        return [
            TranscriptSegment(start=segment.start, end=segment.end, text=f"译文 {segment.text}")
            for segment in chunk
        ]

    partial_lengths: list[int] = []
    monkeypatch.setattr(ai, "_translate_chunk_with_provider", fake_translate_chunk)

    translated = ai._translate_transcript_with_provider(
        title="Lesson",
        transcript=transcript,
        provider=LlmProvider(base_url="https://example.test/v1", api_key="sk-test", model="test-model"),
        context_summary="summary",
        output_language="zh-CN",
        partial_translation=lambda partial: partial_lengths.append(len(partial)),
    )

    assert len(translated) == 61
    assert partial_lengths
    assert partial_lengths[-1] == 61


def test_long_transcript_reuses_existing_context_summary(monkeypatch):
    transcript = [
        TranscriptSegment(start=index * 2, end=index * 2 + 2, text=f"source line {index}")
        for index in range(81)
    ]
    translated = [
        TranscriptSegment(start=segment.start, end=segment.end, text=f"译文 {index}")
        for index, segment in enumerate(transcript)
    ]
    blocks = [
        {
            "id": "block-1",
            "start": 0,
            "end": 162,
            "title": "课程主线",
            "summary": "解释课程。",
            "priority": "focus",
            "key_points": ["重点"],
            "detailed_notes": "解读",
            "high_fidelity_text": "详解文本",
        }
    ]
    used_contexts: list[str] = []

    def fail_context(*args, **kwargs):
        raise AssertionError("context summary should be reused")

    def fake_blocks(**kwargs):
        used_contexts.append(kwargs["context_summary"])
        return blocks

    monkeypatch.setattr(ai, "_generate_translation_context", fail_context)
    monkeypatch.setattr(ai, "_generate_learning_blocks_with_provider", fake_blocks)
    monkeypatch.setattr(ai, "_generate_outline_with_provider", lambda *args, **kwargs: [])
    monkeypatch.setattr(ai, "_generate_guidance_with_provider", lambda *args, **kwargs: {})

    study = generate_study_material(
        title="AI for Everyone",
        transcript=transcript,
        provider=LlmProvider(base_url="https://example.test/v1", api_key="sk-test", model="test-model"),
        output_language="zh-CN",
        existing_translation=translated,
        existing_context_summary="翻译阶段已经生成的上下文摘要",
        existing_translated_title="面向所有人的 AI",
    )

    assert used_contexts == ["翻译阶段已经生成的上下文摘要"]
    assert study.context_summary == "翻译阶段已经生成的上下文摘要"
    assert study.translated_title == "面向所有人的 AI"


def test_long_transcript_reuses_existing_context_summary_even_with_metadata(monkeypatch):
    transcript = [
        TranscriptSegment(start=index * 2, end=index * 2 + 2, text=f"source line {index}")
        for index in range(81)
    ]
    translated = [
        TranscriptSegment(start=segment.start, end=segment.end, text=f"译文 {index}")
        for index, segment in enumerate(transcript)
    ]
    blocks = [
        {
            "id": "block-1",
            "start": 0,
            "end": 162,
            "title": "课程主线",
            "summary": "解释课程。",
            "priority": "focus",
            "key_points": ["重点"],
            "detailed_notes": "解读",
            "high_fidelity_text": "详解文本",
        }
    ]
    used_contexts: list[str] = []

    def fail_context(*args, **kwargs):
        raise AssertionError("context summary should be reused")

    def fake_blocks(**kwargs):
        used_contexts.append(kwargs["context_summary"])
        return blocks

    monkeypatch.setattr(ai, "_generate_translation_context", fail_context)
    monkeypatch.setattr(ai, "_generate_learning_blocks_with_provider", fake_blocks)
    monkeypatch.setattr(ai, "_generate_outline_with_provider", lambda *args, **kwargs: [])
    monkeypatch.setattr(ai, "_generate_guidance_with_provider", lambda *args, **kwargs: {})

    study = generate_study_material(
        title="一个视频搞懂 DeepSeek V4！",
        transcript=transcript,
        provider=LlmProvider(base_url="https://example.test/v1", api_key="sk-test", model="test-model"),
        output_language="zh-CN",
        existing_translation=translated,
        existing_context_summary="已有字幕阶段上下文摘要。",
        metadata=VideoMetadata(
            id="BV1tn9aBqEYg",
            title="一个视频搞懂 DeepSeek V4！",
            uploader="林亦LYi",
            description="我们全面测试了 DeepSeek V4。",
            webpage_url="https://www.bilibili.com/video/BV1tn9aBqEYg/",
            extractor="BiliBili",
        ),
    )

    assert study.context_summary == "已有字幕阶段上下文摘要。"
    assert "林亦LYi" in used_contexts[0]


def test_long_transcript_repairs_incomplete_existing_translation(monkeypatch):
    transcript = [
        TranscriptSegment(
            start=index * 2,
            end=index * 2 + 2,
            text=f"source sentence that needs translation {index}",
        )
        for index in range(81)
    ]
    existing_translation = [
        TranscriptSegment(start=segment.start, end=segment.end, text=segment.text)
        for segment in transcript
    ]
    calls = {"repair": 0}

    def fake_translate_chunk(title, chunk, provider, context_summary, output_language):
        calls["repair"] += 1
        return [
            TranscriptSegment(start=segment.start, end=segment.end, text=f"译文 {segment.text}")
            for segment in chunk
        ]

    monkeypatch.setattr(ai, "_translate_chunk_with_provider", fake_translate_chunk)
    monkeypatch.setattr(
        ai,
        "_generate_learning_blocks_with_provider",
        lambda **kwargs: [
            {
                "id": "block-1",
                "start": 0,
                "end": 162,
                "title": "课程主线",
                "summary": "解释课程。",
                "priority": "focus",
                "key_points": ["重点"],
                "detailed_notes": "解读",
                "high_fidelity_text": "详解文本",
            }
        ],
    )
    monkeypatch.setattr(ai, "_generate_outline_with_provider", lambda *args, **kwargs: [])
    monkeypatch.setattr(ai, "_generate_guidance_with_provider", lambda *args, **kwargs: {})

    study = generate_study_material(
        title="AI for Everyone",
        transcript=transcript,
        provider=LlmProvider(base_url="https://example.test/v1", api_key="sk-test", model="test-model"),
        output_language="zh-CN",
        existing_translation=existing_translation,
        existing_context_summary="已有上下文摘要",
        existing_translated_title="面向所有人的 AI",
    )

    assert calls["repair"] > 0
    assert all(segment.text.startswith("译文 ") for segment in study.translated_transcript)


def test_regenerate_guide_updates_only_guidance(monkeypatch):
    transcript = [
        TranscriptSegment(start=0, end=10, text="Opening idea."),
        TranscriptSegment(start=10, end=20, text="Next idea."),
    ]
    existing = StudyMaterial(
        one_line="旧导览",
        context_summary="已有上下文摘要",
        time_map=[
            TimeRange(start=0, end=20, title="旧时间块", summary="旧摘要", priority="focus"),
        ],
        outline=[
            OutlineNode(id="block-1", start=0, end=20, title="旧大纲", summary="旧摘要", children=[]),
        ],
        detailed_notes="旧解读",
        high_fidelity_text="旧详解",
        translated_transcript=[],
        prerequisites=["旧预备"],
        thought_prompts=["旧问题"],
        review_suggestions=["旧复习"],
        beginner_focus=["旧小白建议"],
        experienced_guidance=["旧进阶建议"],
    )

    monkeypatch.setattr(
        ai,
        "_generate_guidance_with_provider",
        lambda *args, **kwargs: {
            "prerequisites": ["新预备"],
            "thought_prompts": ["新问题"],
            "review_suggestions": ["新复习"],
            "beginner_focus": ["新小白建议"],
            "experienced_guidance": ["新进阶建议"],
            "one_line": "这节课帮助学习者把握核心观点和学习重点。",
        },
    )
    monkeypatch.setattr(
        ai,
        "_generate_translation_context",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("context should be reused")),
    )

    study = ai.regenerate_study_section(
        title="Lesson",
        transcript=transcript,
        existing_study=existing,
        provider=LlmProvider(base_url="https://example.test/v1", api_key="sk-test", model="test-model"),
        output_language="zh-CN",
        section="guide",
    )

    assert study.one_line == "这节课帮助学习者把握核心观点和学习重点。"
    assert study.prerequisites == ["新预备"]
    assert study.thought_prompts == ["新问题"]
    assert study.review_suggestions == ["新复习"]
    assert study.beginner_focus == ["新小白建议"]
    assert study.experienced_guidance == ["新进阶建议"]
    assert study.outline == existing.outline
    assert study.detailed_notes == "旧解读"
    assert study.high_fidelity_text == "旧详解"


def test_guidance_prompt_parses_beginner_and_experienced_arrays(monkeypatch):
    captured_messages = []

    def fake_chat_json(provider, messages, **kwargs):
        captured_messages.extend(messages)
        return {
            "prerequisites": ["预备知识"],
            "thought_prompts": ["思考提示"],
            "review_suggestions": ["复习建议"],
            "beginner_focus": ["小白重点听课程中的基础概念和例子。"],
            "experienced_guidance": ["有经验者可略过入门定义，但复习实践判断。"],
            "one_line": "这节课讲解提示工程中的概念理解和实践判断。",
        }

    monkeypatch.setattr(ai, "_chat_json", fake_chat_json)

    guidance = ai._generate_guidance_with_provider(
        "Prompting Lesson",
        [TranscriptSegment(start=0, end=5, text="This course explains concepts and examples.")],
        "课程摘要",
        LlmProvider(base_url="https://example.test/v1", api_key="sk-test", model="test-model"),
        "zh-CN",
    )

    assert guidance["prerequisites"] == ["预备知识"]
    assert guidance["one_line"] == "这节课讲解提示工程中的概念理解和实践判断。"
    assert guidance["beginner_focus"] == ["小白重点听课程中的基础概念和例子。"]
    assert guidance["experienced_guidance"] == ["有经验者可略过入门定义，但复习实践判断。"]
    assert "beginner_focus" in captured_messages[0]["content"]
    assert "experienced_guidance" in captured_messages[0]["content"]


def test_guidance_prompt_uses_full_transcript(monkeypatch):
    captured_messages = []
    transcript = [
        TranscriptSegment(start=index * 5, end=index * 5 + 5, text=f"line {index}")
        for index in range(100)
    ]

    def fake_chat_json(provider, messages, **kwargs):
        captured_messages.extend(messages)
        return {
            "prerequisites": [],
            "thought_prompts": [],
            "review_suggestions": [],
            "beginner_focus": [],
            "experienced_guidance": [],
            "one_line": "这是一节长课程。",
        }

    monkeypatch.setattr(ai, "_chat_json", fake_chat_json)

    ai._generate_guidance_with_provider(
        "Long Lesson",
        transcript,
        "课程摘要",
        LlmProvider(base_url="https://example.test/v1", api_key="sk-test", model="test-model"),
        "zh-CN",
    )

    user_prompt = captured_messages[1]["content"]
    assert "Full transcript:" in user_prompt
    assert "Transcript sample:" not in user_prompt
    assert "1. [00:00-00:05] line 0" in user_prompt
    assert "100. [08:15-08:20] line 99" in user_prompt


def test_regenerate_outline_preserves_other_sections(monkeypatch):
    transcript = [TranscriptSegment(start=0, end=10, text="Opening idea.")]
    existing = StudyMaterial(
        one_line="旧导览",
        context_summary="已有上下文摘要",
        time_map=[TimeRange(start=0, end=10, title="旧时间块", summary="旧摘要", priority="focus")],
        outline=[OutlineNode(id="block-1", start=0, end=10, title="旧大纲", summary="旧摘要", children=[])],
        detailed_notes="旧解读",
        high_fidelity_text="旧详解",
    )
    new_outline = [
        OutlineNode(id="block-1-new", start=0, end=10, title="新大纲", summary="新摘要", children=[]),
    ]
    monkeypatch.setattr(ai, "_generate_outline_with_provider", lambda *args, **kwargs: new_outline)

    study = ai.regenerate_study_section(
        title="Lesson",
        transcript=transcript,
        existing_study=existing,
        provider=LlmProvider(base_url="https://example.test/v1", api_key="sk-test", model="test-model"),
        output_language="zh-CN",
        section="outline",
    )

    assert study.outline == new_outline
    assert study.one_line == "旧导览"
    assert study.detailed_notes == "旧解读"
    assert study.high_fidelity_text == "旧详解"


def test_regenerate_high_reuses_existing_structure_and_interpretation(monkeypatch):
    transcript = [
        TranscriptSegment(start=0, end=5, text="Opening idea."),
        TranscriptSegment(start=5, end=10, text="Important detail."),
    ]
    existing = StudyMaterial(
        one_line="旧导览",
        context_summary="已有上下文摘要",
        time_map=[TimeRange(start=0, end=10, title="旧结构标题", summary="旧结构摘要", priority="focus")],
        outline=[OutlineNode(id="block-1", start=0, end=10, title="旧大纲", summary="旧摘要", children=[])],
        detailed_notes="00:00-00:10 旧结构标题\n已有解读内容。",
        high_fidelity_text="旧详解",
    )
    calls: dict[str, object] = {"structure": 0, "interpretation": 0}

    def fail_structure(*args, **kwargs):
        calls["structure"] = int(calls["structure"]) + 1
        raise AssertionError("structure should be reused")

    def fail_interpretation(*args, **kwargs):
        calls["interpretation"] = int(calls["interpretation"]) + 1
        raise AssertionError("interpretation should be reused")

    def fake_high(**kwargs):
        calls["structure_payload"] = kwargs["structure"]
        calls["detailed_notes"] = kwargs["detailed_notes"]
        return "新详解内容。"

    monkeypatch.setattr(ai, "_generate_learning_block_structure_with_provider", fail_structure)
    monkeypatch.setattr(ai, "_generate_learning_block_interpretation_with_provider", fail_interpretation)
    monkeypatch.setattr(ai, "_generate_learning_block_high_fidelity_with_provider", fake_high)

    study = ai.regenerate_study_section(
        title="Lesson",
        transcript=transcript,
        existing_study=existing,
        provider=LlmProvider(base_url="https://example.test/v1", api_key="sk-test", model="test-model"),
        output_language="zh-CN",
        section="high",
    )

    assert calls["structure"] == 0
    assert calls["interpretation"] == 0
    assert calls["structure_payload"]["title"] == "旧结构标题"
    assert calls["detailed_notes"] == "已有解读内容。"
    assert study.detailed_notes == existing.detailed_notes
    assert "新详解内容" in study.high_fidelity_text


def test_outline_time_calibration_uses_block_ids():
    outline = [
        OutlineNode(
            id="block-2_block-3",
            start=0.49,
            end=2.03,
            title="合并主题",
            summary="模型可能把 mm:ss 误写成小数。",
            children=[
                OutlineNode(
                    id="block-2",
                    start=0.49,
                    end=1.29,
                    title="子主题",
                    summary="子节点也应校准。",
                    children=[],
                )
            ],
        )
    ]
    blocks = [
        {"id": "block-2", "start": 49.24, "end": 89.27},
        {"id": "block-3", "start": 89.28, "end": 123.43},
    ]

    calibrated = ai._calibrate_outline_times(outline, blocks)

    assert calibrated[0].start == 49.24
    assert calibrated[0].end == 123.43
    assert calibrated[0].children[0].start == 49.24
    assert calibrated[0].children[0].end == 89.27


def test_semantic_segmentation_repairs_gaps_and_overlaps(monkeypatch):
    transcript = [
        TranscriptSegment(start=0, end=20, text="Opening and first idea."),
        TranscriptSegment(start=20, end=40, text="Still first idea."),
        TranscriptSegment(start=40, end=60, text="Second topic starts."),
        TranscriptSegment(start=60, end=80, text="Second topic example."),
    ]

    def fake_chat_json(provider, messages, temperature, max_tokens, timeout, task_key=None):
        return {
            "blocks": [
                {
                    "start": 0,
                    "end": 42,
                    "title": "开场",
                    "summary": "第一主题。",
                    "priority": "focus",
                    "boundary_reason": "Topic setup",
                    "confidence": 0.9,
                },
                {
                    "start": 39,
                    "end": 75,
                    "title": "第二主题",
                    "summary": "例子展开。",
                    "priority": "skim",
                    "boundary_reason": "New example",
                    "confidence": 0.8,
                },
            ]
        }

    monkeypatch.setattr(ai, "_chat_json", fake_chat_json)

    ranges = ai._generate_semantic_ranges_with_provider(
        title="Lesson",
        transcript=transcript,
        context_summary="summary",
        provider=LlmProvider(base_url="https://example.test/v1", api_key="sk-test", model="test-model"),
        output_language="zh-CN",
        strategy=ai._study_strategy("faithful"),
    )

    assert ranges[0].start == 0
    assert ranges[0].end == ranges[1].start
    assert ranges[-1].end == 80
    assert [item.title for item in ranges] == ["开场", "第二主题"]


def test_task_parameter_overrides_are_applied_and_capped():
    provider = LlmProvider(
        base_url="https://example.test/v1",
        api_key="sk-test",
        model="test-model",
        max_tokens=8000,
        task_parameters={
            "guide": ai.TaskParameterOverride(temperature=0.41, max_tokens=12000),
        },
    )

    temperature, max_tokens = ai._effective_task_parameters(
        provider,
        task_key="guide",
        temperature=0.25,
        max_tokens=1600,
    )

    assert temperature == 0.41
    assert max_tokens == 8000


def test_learning_blocks_use_semantic_ranges_before_block_generation(monkeypatch):
    transcript = [
        TranscriptSegment(start=0, end=30, text="Opening."),
        TranscriptSegment(start=30, end=60, text="Topic shift."),
        TranscriptSegment(start=60, end=90, text="Example."),
    ]
    translated = [
        TranscriptSegment(start=segment.start, end=segment.end, text=f"译文 {segment.text}")
        for segment in transcript
    ]
    calls: list[tuple[int, float, float, str]] = []

    monkeypatch.setattr(
        ai,
        "_generate_semantic_ranges_with_provider",
        lambda **kwargs: [
            TimeRange(start=0, end=60, title="第一块", summary="开场。", priority="focus"),
            TimeRange(start=60, end=90, title="第二块", summary="例子。", priority="skim"),
        ],
    )

    def fake_block(title, index, source_chunk, translated_chunk, context_summary, provider, output_language, detail_level="standard", neighbor_context=""):
        calls.append((index, source_chunk[0].start, source_chunk[-1].end, neighbor_context))
        return {
            "id": f"block-{index + 1}",
            "start": source_chunk[0].start,
            "end": source_chunk[-1].end,
            "title": f"块 {index + 1}",
            "summary": "摘要",
            "priority": "focus",
            "key_points": ["重点"],
            "detailed_notes": "解读",
            "high_fidelity_text": "详解",
        }

    monkeypatch.setattr(ai, "_generate_learning_block_with_provider", fake_block)

    blocks = ai._generate_learning_blocks_with_provider(
        title="Lesson",
        source_transcript=transcript,
        translated_transcript=translated,
        context_summary="summary",
        provider=LlmProvider(base_url="https://example.test/v1", api_key="sk-test", model="learning"),
        segmentation_provider=LlmProvider(base_url="https://example.test/v1", api_key="sk-test", model="global"),
        output_language="zh-CN",
        detail_level="detailed",
    )

    assert [block["start"] for block in blocks] == [0, 60]
    assert calls[0][1:3] == (0, 60)
    assert calls[1][1:3] == (60, 90)
    assert "Next:" in calls[0][3]


def test_learning_block_generation_splits_structure_interpretation_and_high_fidelity(monkeypatch):
    source_chunk = [
        TranscriptSegment(start=0, end=5, text="Opening idea corrected."),
        TranscriptSegment(start=5, end=10, text="The example shows two prompt versions."),
    ]
    translated_chunk = [
        TranscriptSegment(start=0, end=5, text="校正后的开场观点。"),
        TranscriptSegment(start=5, end=10, text="例子展示两个提示词版本。"),
    ]
    calls: list[tuple[str | None, str, str]] = []

    def fake_chat_json(provider, messages, temperature, max_tokens, timeout, task_key=None):
        calls.append((task_key, messages[0]["content"], messages[1]["content"]))
        if len(calls) == 1:
            return {
                "title": "提示词版本对比",
                "summary": "这一块用例子说明提示词迭代。",
                "priority": "focus",
                "key_points": [
                    {"type": "example", "text": "比较两个提示词版本。", "evidence": "example line"},
                ],
                "terms": ["提示词迭代"],
                "open_questions": [],
            }
        if len(calls) == 2:
            return {"detailed_notes": "解读层说明这个例子为什么重要。"}
        return {"high_fidelity_text": "详解层保留两个版本的铺垫、比较和结论。"}

    monkeypatch.setattr(ai, "_chat_json", fake_chat_json)

    block = ai._generate_learning_block_with_provider(
        title="Lesson",
        index=0,
        source_chunk=source_chunk,
        translated_chunk=translated_chunk,
        context_summary="课程讲提示词迭代。",
        provider=LlmProvider(base_url="https://example.test/v1", api_key="sk-test", model="learning"),
        output_language="zh-CN",
        detail_level="faithful",
        neighbor_context="Next: another block.",
    )

    assert [call[0] for call in calls] == ["interpretation", "interpretation", "high_fidelity"]
    assert "detailed_notes" not in calls[0][1]
    assert "high_fidelity_text" not in calls[0][1]
    assert "Learning block structure" in calls[1][2]
    assert "detailed_notes" in calls[2][2]
    assert "Opening idea corrected." in calls[0][2]
    assert block["title"] == "提示词版本对比"
    assert block["key_points"] == ["比较两个提示词版本。"]
    assert block["detailed_notes"] == "解读层说明这个例子为什么重要。"
    assert block["high_fidelity_text"] == "详解层保留两个版本的铺垫、比较和结论。"


def test_learning_block_structure_repairs_visible_fields_to_output_language(monkeypatch):
    source_chunk = [
        TranscriptSegment(start=0, end=5, text="AI prompting has changed since ChatGPT first came out."),
        TranscriptSegment(start=5, end=10, text="The goal is to become an expert prompter."),
    ]
    translated_chunk = [
        TranscriptSegment(start=0, end=5, text="自 ChatGPT 首次出现以来，AI 提示方式已经发生变化。"),
        TranscriptSegment(start=5, end=10, text="目标是成为专家级提示者。"),
    ]
    calls: list[tuple[str | None, str, str]] = []

    def fake_chat_json(provider, messages, temperature, max_tokens, timeout, task_key=None):
        calls.append((task_key, messages[0]["content"], messages[1]["content"]))
        if len(calls) == 1:
            return {
                "title": "AI Prompting Evolution",
                "summary": "The speaker sets the context and introduces expert prompting.",
                "priority": "focus",
                "key_points": ["AI prompting changed after ChatGPT."],
                "terms": ["ChatGPT"],
                "open_questions": [],
            }
        if len(calls) == 2:
            return {
                "title": "AI 提示方式的演进",
                "summary": "讲者设定课程背景，并引出成为专家级提示者的目标。",
                "key_points": ["AI 提示方式在 ChatGPT 之后发生变化。"],
            }
        if len(calls) == 3:
            return {"detailed_notes": "解读层说明课程导入为什么重要。"}
        return {"high_fidelity_text": "详解层保留提示方式变化和课程目标。"}

    monkeypatch.setattr(ai, "_chat_json", fake_chat_json)

    block = ai._generate_learning_block_with_provider(
        title="The AI Novice and the AI Power User",
        index=0,
        source_chunk=source_chunk,
        translated_chunk=translated_chunk,
        context_summary="课程讨论 AI 使用能力的差异。",
        provider=LlmProvider(base_url="https://example.test/v1", api_key="sk-test", model="learning"),
        output_language="zh-CN",
        detail_level="standard",
    )

    assert [call[0] for call in calls] == ["interpretation", "interpretation", "interpretation", "high_fidelity"]
    assert "Translate only the user-visible structure fields" in calls[1][1]
    assert block["title"] == "AI 提示方式的演进"
    assert block["summary"] == "讲者设定课程背景，并引出成为专家级提示者的目标。"
    assert block["key_points"] == ["AI 提示方式在 ChatGPT 之后发生变化。"]


def test_fallback_outline_has_three_visible_levels():
    blocks = [
        {
            "id": "block-1",
            "start": 0,
            "end": 60,
            "title": "第一部分",
            "summary": "课程说明核心概念。",
            "priority": "focus",
            "key_points": ["核心概念", "关键例子"],
            "detailed_notes": "这里解释核心概念和关键例子。",
        }
    ]

    outline = ai._outline_from_blocks(blocks)

    assert outline[0].children
    assert outline[0].children[0].children
    assert "block-1" in outline[0].children[0].children[0].id
