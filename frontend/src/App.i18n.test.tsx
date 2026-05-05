import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  extractCourse,
  getModelSettings,
  getStudyJob,
  listItems,
  previewCourse,
  saveModelSettings,
  startDownloadJob,
  updateCourseItem,
} from "./api";
import { App } from "./App";

vi.mock("./api", () => ({
  deleteCourse: vi.fn(),
  deleteLocalVideo: vi.fn(),
  downloadVideo: vi.fn(),
  extractCourse: vi.fn(),
  previewCourse: vi.fn(),
  getModelSettings: vi.fn().mockResolvedValue({
    profiles: [
      {
        id: "default",
        name: "DeepSeek V3.2",
        provider_type: "openai",
        base_url: "https://api.siliconflow.cn/v1",
        model: "deepseek-ai/DeepSeek-V3.2",
        context_window: null,
        max_tokens: null,
        has_api_key: true,
        api_key_preview: "sk...test",
      },
    ],
    translation_model_id: "default",
    learning_model_id: "default",
    global_model_id: "default",
    asr_model_id: "default",
    study_detail_level: "faithful",
    task_parameters: {},
  }),
  getStudyJob: vi.fn(),
  getAsrCorrectionResult: vi.fn(),
  itemVideoPath: (itemId: string) => `/api/items/${itemId}/video`,
  listAvailableModels: vi.fn(),
  listItems: vi.fn().mockResolvedValue([]),
  saveModelSettings: vi.fn(),
  saveTranscript: vi.fn(),
  startAsrCorrectionJob: vi.fn(),
  startDownloadJob: vi.fn(),
  startStudyJob: vi.fn(),
  startTranslationJob: vi.fn(),
  updateCourseItem: vi.fn(),
}));

describe("App language defaults", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    installTestLocalStorage();
    window.localStorage.removeItem("course-navigator-manual-collections");
    window.localStorage.removeItem("course-navigator-collapsed-collections");
    window.localStorage.removeItem("course-navigator-time-map-auto-open");
    window.localStorage.removeItem("course-navigator-last-selected-course");
    window.localStorage.removeItem("course-navigator-asr-save-accepted-changes");
  });

  it("uses Chinese UI and a language menu by default", async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "翻译字幕" })).toBeTruthy();
    });

    expect((screen.getByRole("combobox", { name: "界面" }) as HTMLSelectElement).value).toBe("zh-CN");
    expect((screen.getByRole("combobox", { name: "输出" }) as HTMLSelectElement).value).toBe("zh-CN");
    expect(screen.getByRole("button", { name: "打开视频并提取字幕" })).toBeTruthy();
    expect(screen.queryByText("打开预览")).toBeNull();
    expect(screen.queryByRole("button", { name: "分析" })).toBeNull();
    expect(screen.queryByDisplayValue("https://www.youtube.com/watch?v=JPcx9qHzzgk&t=13s")).toBeNull();
    expect(screen.getByText("提取登录")).toBeTruthy();
    expect(screen.getByText("Cookie 来源")).toBeTruthy();
    expect((screen.getByRole("combobox", { name: "字幕来源" }) as HTMLSelectElement).value).toBe("subtitles");
    expect(screen.queryByRole("button", { name: "时间地图双语" })).toBeNull();
    expect(screen.getByRole("button", { name: "字幕列表双语" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "视频字幕隐藏字幕" })).toBeNull();
    expect(screen.queryByRole("button", { name: "全屏" })).toBeNull();
    expect(screen.getByRole("button", { name: "模型设置" })).toBeTruthy();
    expect(screen.getByText("视频学习工作台")).toBeTruthy();
    expect(screen.queryByText("本地视频学习工作台")).toBeNull();
    expect(screen.queryByText("字幕源")).toBeNull();
    expect(screen.getByText("课程库")).toBeTruthy();
    expect(screen.getByRole("button", { name: "导览" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "大纲" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "解读" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "详解" })).toBeTruthy();
    expect(screen.queryByPlaceholderText("en")).toBeNull();
  });

  it("does not embed Bilibili by default and offers force streaming", async () => {
    vi.mocked(listItems).mockResolvedValueOnce([
      {
        id: "bili-lesson",
        source_url: "https://www.bilibili.com/video/BV1iVoVBgERD/",
        title: "Bilibili lesson",
        duration: 120,
        created_at: new Date().toISOString(),
        transcript: [{ start: 0, end: 2, text: "Hello" }],
        metadata: {
          id: "BV1iVoVBgERD",
          title: "Bilibili lesson",
          duration: 120,
          webpage_url: "https://www.bilibili.com/video/BV1iVoVBgERD/",
          extractor: "BiliBili",
          stream_url: null,
          hls_manifest_url: null,
          language: "zh-CN",
          subtitles: [],
          automatic_captions: [],
        },
        study: null,
        local_video_path: null,
      },
    ]);

    render(<App />);

    expect(await screen.findByText("bilibili站外播放不提供字幕时间轴功能，建议缓存后观看。")).toBeTruthy();
    expect(screen.queryByTitle("Bilibili lesson")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "强制在线播放" }));

    expect(await screen.findByTitle("Bilibili lesson")).toBeTruthy();
  });

  it("uses the local player by default for cached videos and keeps native fullscreen available", async () => {
    vi.mocked(listItems).mockResolvedValueOnce([
      {
        id: "cached-bili",
        source_url: "https://www.bilibili.com/video/BV1iVoVBgERD/",
        title: "Cached Bilibili lesson",
        duration: 120,
        created_at: new Date().toISOString(),
        transcript: [{ start: 0, end: 2, text: "Hello" }],
        metadata: {
          id: "BV1iVoVBgERD",
          title: "Cached Bilibili lesson",
          duration: 120,
          webpage_url: "https://www.bilibili.com/video/BV1iVoVBgERD/",
          extractor: "BiliBili",
          stream_url: null,
          hls_manifest_url: null,
          language: "zh-CN",
          subtitles: [],
          automatic_captions: [],
        },
        study: null,
        local_video_path: "/tmp/cached-bili.mp4",
      },
    ]);

    const { container } = render(<App />);

    await waitFor(() => {
      expect(container.querySelector("video")).toBeTruthy();
    });
    const video = container.querySelector("video");
    expect(video).toBeTruthy();
    expect(video?.getAttribute("controlsList")).toBeNull();
    await waitFor(() => {
      expect(container.querySelector("video track")).toBeTruthy();
    });
  });

  it("falls back to transcript duration and shows translated title when available", async () => {
    vi.mocked(listItems).mockResolvedValueOnce([
      {
        id: "dlai-lesson",
        source_url: "https://learn.deeplearning.ai/courses/example",
        title: "AI Prompting for Everyone",
        duration: null,
        created_at: new Date().toISOString(),
        transcript: [{ start: 0, end: 98, text: "Opening idea." }],
        metadata: {
          id: "dlai-lesson",
          title: "AI Prompting for Everyone",
          duration: null,
          webpage_url: "https://learn.deeplearning.ai/courses/example",
          extractor: "html5",
          stream_url: null,
          hls_manifest_url: null,
          language: "en",
          subtitles: [],
          automatic_captions: [],
        },
        study: {
          one_line: "课程摘要。",
          translated_title: "面向所有人的 AI 提示",
          time_map: [],
          outline: [],
          detailed_notes: "",
          high_fidelity_text: "",
          translated_transcript: [],
          prerequisites: [],
          thought_prompts: [],
          review_suggestions: [],
        },
        local_video_path: null,
      },
    ]);

    render(<App />);

    expect(await screen.findByText("01:38")).toBeTruthy();
    expect(screen.getAllByText("面向所有人的 AI 提示").length).toBeGreaterThan(0);
  });

  it("opens a pasted URL by extracting the real course item", async () => {
    const previewItem = {
      id: "dlai-lesson",
      source_url: "https://learn.deeplearning.ai/courses/example",
      title: "AI Prompting for Everyone",
      duration: 579,
      created_at: new Date().toISOString(),
      transcript: [],
      metadata: {
        id: "dlai-lesson",
        title: "AI Prompting for Everyone",
        duration: 579,
        webpage_url: "https://learn.deeplearning.ai/courses/example",
        extractor: "html5",
        stream_url: "https://video.deeplearning.ai/example/master.m3u8",
        hls_manifest_url: "https://video.deeplearning.ai/example/master.m3u8",
        language: "en",
        subtitles: [],
        automatic_captions: [],
      },
      study: null,
      local_video_path: null,
    };
    const extractedItem = {
      ...previewItem,
      transcript: [{ start: 1, end: 3, text: "Opening idea." }],
    };
    let resolveExtract!: (item: typeof extractedItem) => void;
    vi.mocked(previewCourse).mockResolvedValueOnce(previewItem);
    vi.mocked(extractCourse).mockReturnValueOnce(new Promise((resolve) => {
      resolveExtract = resolve;
    }));
    render(<App />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "打开视频并提取字幕" })).toBeTruthy();
    });

    const input = screen.getByPlaceholderText("粘贴课程或视频 URL");
    fireEvent.change(input, { target: { value: "https://learn.deeplearning.ai/courses/example" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    expect((await screen.findAllByText("AI Prompting for Everyone")).length).toBeGreaterThan(0);
    expect(previewCourse).toHaveBeenCalledWith(expect.objectContaining({ url: "https://learn.deeplearning.ai/courses/example" }));
    expect(screen.getByText("正在提取字幕")).toBeTruthy();
    resolveExtract(extractedItem);
    expect(await screen.findByText("Opening idea.")).toBeTruthy();
    expect(extractCourse).toHaveBeenCalledWith(expect.objectContaining({ url: "https://learn.deeplearning.ai/courses/example" }));
  });

  it("caches an already extracted URL without a hidden extraction step", async () => {
    const previewItem = {
      id: "dlai-lesson",
      source_url: "https://learn.deeplearning.ai/courses/example",
      title: "AI Prompting for Everyone",
      duration: null,
      created_at: new Date().toISOString(),
      transcript: [],
      metadata: {
        id: "dlai-lesson",
        title: "AI Prompting for Everyone",
        duration: null,
        webpage_url: "https://learn.deeplearning.ai/courses/example",
        extractor: "html5",
        stream_url: "https://video.deeplearning.ai/example/master.m3u8",
        language: null,
        subtitles: [],
        automatic_captions: [],
      },
      study: null,
      local_video_path: null,
    };
    vi.mocked(previewCourse).mockResolvedValueOnce(previewItem);
    vi.mocked(extractCourse).mockResolvedValueOnce(previewItem);
    vi.mocked(startDownloadJob).mockResolvedValueOnce({
      job_id: "download-job",
      item_id: "dlai-lesson",
      status: "running",
      progress: 12,
      phase: "download",
      message: "正在缓存视频",
      error: null,
    });
    vi.mocked(getStudyJob)
      .mockResolvedValueOnce({
        job_id: "download-job",
        item_id: "dlai-lesson",
        status: "running",
        progress: 48,
        phase: "download",
        message: "正在缓存视频",
        error: null,
      })
      .mockResolvedValueOnce({
        job_id: "download-job",
        item_id: "dlai-lesson",
        status: "succeeded",
        progress: 100,
        phase: "complete",
        message: "视频缓存完成",
        error: null,
      });
    render(<App />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "打开视频并提取字幕" })).toBeTruthy();
    });

    const input = screen.getByPlaceholderText("粘贴课程或视频 URL");
    fireEvent.change(input, { target: { value: "https://learn.deeplearning.ai/courses/example" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    await waitFor(() => {
      expect(extractCourse).toHaveBeenCalledWith(
        expect.objectContaining({
          url: "https://learn.deeplearning.ai/courses/example",
        }),
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "缓存" }));

    await waitFor(() => {
      expect(startDownloadJob).toHaveBeenCalledWith(
        "dlai-lesson",
        expect.objectContaining({
          url: "https://learn.deeplearning.ai/courses/example",
        }),
      );
    });
    expect(await screen.findByText("正在缓存视频 48%")).toBeTruthy();
  });

  it("keeps the top-right fullscreen control available after entering shell fullscreen", async () => {
    vi.mocked(listItems).mockResolvedValueOnce([
      {
        id: "cached-video",
        source_url: "https://example.com/video.mp4",
        title: "Cached video",
        duration: 60,
        created_at: new Date().toISOString(),
        transcript: [{ start: 0, end: 2, text: "Hello" }],
        metadata: null,
        study: null,
        local_video_path: "/tmp/cached-video.mp4",
      },
    ]);
    let fullscreenElement: Element | null = null;
    Object.defineProperty(document, "fullscreenElement", {
      configurable: true,
      get: () => fullscreenElement,
    });
    const requestFullscreen = vi.fn(function requestFullscreen(this: Element) {
      fullscreenElement = this;
      document.dispatchEvent(new Event("fullscreenchange"));
      return Promise.resolve();
    });
    const exitFullscreen = vi.fn(() => {
      fullscreenElement = null;
      document.dispatchEvent(new Event("fullscreenchange"));
      return Promise.resolve();
    });
    Object.defineProperty(HTMLElement.prototype, "requestFullscreen", {
      configurable: true,
      value: requestFullscreen,
    });
    Object.defineProperty(document, "exitFullscreen", {
      configurable: true,
      value: exitFullscreen,
    });

    const { container } = render(<App />);

    await waitFor(() => {
      expect(container.querySelector(".player-fullscreen-button")).toBeTruthy();
    });
    fireEvent.click(container.querySelector(".player-fullscreen-button") as HTMLButtonElement);

    await waitFor(() => {
      expect(container.querySelector(".player-fullscreen-button")).toBeTruthy();
      expect(container.querySelector(".player-fullscreen-button")?.getAttribute("aria-label")).toBe("退出全屏");
    });
  });

  it("shows separate model slots in settings", async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "模型设置" })).toBeTruthy();
    });

    fireEvent.click(screen.getByRole("button", { name: "模型设置" }));

    expect(await screen.findByText("字幕模型")).toBeTruthy();
    expect(screen.getByText("详解模型")).toBeTruthy();
    expect(screen.getByText("结构模型")).toBeTruthy();
    expect(screen.queryByText("学习材料详细程度")).toBeNull();
    expect(screen.getByText("模型档案")).toBeTruthy();
    expect(screen.getByText("OpenAI 格式")).toBeTruthy();
    expect(screen.getByText("Anthropic 格式")).toBeTruthy();
    expect(screen.getByText("高级调用参数")).toBeTruthy();
    expect(screen.queryByText("上下文窗口上限（选填）")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /高级调用参数/ }));
    expect(screen.getByText("模型能力覆盖")).toBeTruthy();
    expect(screen.getByText("任务策略覆盖")).toBeTruthy();
    expect(screen.getByText("上下文窗口上限（选填）")).toBeTruthy();
    expect(screen.getByText("最大输出上限（选填）")).toBeTruthy();
  });

  it("auto-saves model slot changes without saving the profile draft", async () => {
    const settings = {
      profiles: [
        {
          id: "default",
          name: "DeepSeek V3.2",
          provider_type: "openai" as const,
          base_url: "https://api.siliconflow.cn/v1",
          model: "deepseek-ai/DeepSeek-V3.2",
          context_window: null,
          max_tokens: null,
          has_api_key: true,
          api_key_preview: "sk...test",
        },
        {
          id: "mimo",
          name: "mimo-v2.5-pro",
          provider_type: "anthropic" as const,
          base_url: "https://api.minimaxi.com/anthropic/v1",
          model: "MiniMax-M2.7",
          context_window: null,
          max_tokens: null,
          has_api_key: true,
          api_key_preview: "mk...test",
        },
      ],
      translation_model_id: "default",
      learning_model_id: "default",
      global_model_id: "mimo",
      asr_model_id: "default",
      study_detail_level: "faithful" as const,
      task_parameters: {},
    };
    vi.mocked(getModelSettings).mockResolvedValueOnce(settings);
    vi.mocked(saveModelSettings).mockResolvedValueOnce({
      ...settings,
      translation_model_id: "mimo",
    });

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "模型设置" }));
    fireEvent.click(await screen.findByRole("button", { name: "新增档案" }));
    fireEvent.change(screen.getByLabelText("档案名称"), { target: { value: "未保存档案" } });

    fireEvent.change(screen.getByLabelText(/^字幕模型/) as HTMLSelectElement, {
      target: { value: "mimo" },
    });

    await waitFor(() => {
      expect(saveModelSettings).toHaveBeenCalledWith(
        expect.objectContaining({
          translation_model_id: "mimo",
          learning_model_id: "default",
          global_model_id: "mimo",
          study_detail_level: "faithful",
        }),
      );
    });
    const payload = vi.mocked(saveModelSettings).mock.calls[0][0];
    expect(payload.profiles.map((profile) => profile.name)).toEqual(["DeepSeek V3.2", "mimo-v2.5-pro"]);
    expect(await screen.findByText("模型选择已保存")).toBeTruthy();
  });

  it("keeps a new model profile blank and uses provider-specific base URL examples only", async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "模型设置" })).toBeTruthy();
    });

    fireEvent.click(screen.getByRole("button", { name: "模型设置" }));
    fireEvent.click(await screen.findByRole("button", { name: "新增档案" }));

    const activeProfile = screen.getByLabelText("正在编辑") as HTMLSelectElement;
    const profileName = screen.getByLabelText("档案名称") as HTMLInputElement;
    const baseUrl = screen.getByLabelText("接口地址") as HTMLInputElement;
    const model = screen.getByLabelText("模型") as HTMLInputElement;
    fireEvent.click(screen.getByRole("button", { name: /高级调用参数/ }));
    const contextWindow = screen.getByLabelText("上下文窗口上限（选填）") as HTMLInputElement;
    const maxTokens = screen.getByLabelText("最大输出上限（选填）") as HTMLInputElement;

    expect(activeProfile.options[activeProfile.selectedIndex]?.textContent).toBe("未命名档案");
    expect(profileName.value).toBe("");
    expect(baseUrl.value).toBe("");
    expect(model.value).toBe("");
    expect(contextWindow.value).toBe("");
    expect(maxTokens.value).toBe("");
    expect(baseUrl.placeholder).toBe("https://api.openai.com/v1");
    expect(model.placeholder).toBe("");
    expect(contextWindow.placeholder).toBe("");
    expect(maxTokens.placeholder).toBe("");
    expect(screen.getByLabelText("标题翻译 Temperature")).toBeTruthy();
    expect(screen.getByLabelText("字幕翻译 最大输出")).toBeTruthy();

    fireEvent.change(screen.getByRole("combobox", { name: "接口格式" }), {
      target: { value: "anthropic" },
    });

    expect(baseUrl.placeholder).toBe("https://api.anthropic.com/v1");
  });

  it("treats provider format as a profile option and allows decimal temperature input", async () => {
    vi.mocked(getModelSettings).mockResolvedValueOnce({
      profiles: [
        {
          id: "default",
          name: "DeepSeek V3.2",
          provider_type: "openai",
          base_url: "https://api.siliconflow.cn/v1",
          model: "deepseek-ai/DeepSeek-V3.2",
          context_window: 160000,
          max_tokens: 24000,
          has_api_key: true,
          api_key_preview: "sk...test",
        },
      ],
      translation_model_id: "default",
      learning_model_id: "default",
      global_model_id: "default",
      asr_model_id: "default",
      study_detail_level: "faithful",
      task_parameters: {
        title_translation: { temperature: 0.3, max_tokens: 512 },
      },
    });
    render(<App />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "模型设置" })).toBeTruthy();
    });

    fireEvent.click(screen.getByRole("button", { name: "模型设置" }));

    const baseUrl = await screen.findByLabelText("接口地址") as HTMLInputElement;
    const model = screen.getByLabelText("模型") as HTMLInputElement;
    fireEvent.click(screen.getByRole("button", { name: /高级调用参数/ }));
    const contextWindow = screen.getByLabelText("上下文窗口上限（选填）") as HTMLInputElement;
    const maxTokens = screen.getByLabelText("最大输出上限（选填）") as HTMLInputElement;
    const titleTemperature = screen.getByLabelText("标题翻译 Temperature") as HTMLInputElement;
    const titleMaxTokens = screen.getByLabelText("标题翻译 最大输出") as HTMLInputElement;
    const providerType = screen.getByRole("combobox", { name: "接口格式" }) as HTMLSelectElement;

    expect(providerType.value).toBe("openai");
    expect((screen.getByLabelText("档案名称") as HTMLInputElement).value).toBe("DeepSeek V3.2");
    expect(baseUrl.value).toBe("https://api.siliconflow.cn/v1");
    expect(model.value).toBe("deepseek-ai/DeepSeek-V3.2");
    expect(contextWindow.value).toBe("160000");
    expect(maxTokens.value).toBe("24000");
    expect(titleTemperature.value).toBe("0.3");
    expect(titleMaxTokens.value).toBe("512");

    fireEvent.change(providerType, { target: { value: "anthropic" } });

    expect(providerType.value).toBe("anthropic");
    expect((screen.getByLabelText("档案名称") as HTMLInputElement).value).toBe("DeepSeek V3.2");
    expect(baseUrl.value).toBe("https://api.siliconflow.cn/v1");
    expect(baseUrl.placeholder).toBe("https://api.anthropic.com/v1");
    expect(model.value).toBe("deepseek-ai/DeepSeek-V3.2");
    expect(contextWindow.value).toBe("160000");
    expect(maxTokens.value).toBe("24000");
    expect(titleTemperature.value).toBe("0.3");
    expect(titleMaxTokens.value).toBe("512");

    fireEvent.change(titleTemperature, { target: { value: "0." } });
    expect(titleTemperature.value).toBe("0.");
    fireEvent.change(titleTemperature, { target: { value: "0.35" } });
    expect(titleTemperature.value).toBe("0.35");
  });

  it("shows the first study-map action in the empty center state only", async () => {
    vi.mocked(listItems).mockResolvedValueOnce([
      {
        id: "lesson-with-transcript",
        source_url: "https://www.youtube.com/watch?v=abc123",
        title: "Sample Lesson",
        duration: 42,
        created_at: new Date().toISOString(),
        transcript: [{ start: 0, end: 4, text: "Opening idea." }],
        metadata: null,
        study: null,
        local_video_path: null,
      },
    ]);

    render(<App />);

    const generateButton = await screen.findByRole("button", { name: "生成学习地图" });
    expect(generateButton.closest(".study-actions")).toBeNull();
    expect(generateButton.closest(".empty-state")).toBeTruthy();
  });

  it("renames a course title from the library", async () => {
    const item = {
      id: "abc123",
      source_url: "https://www.youtube.com/watch?v=abc123",
      title: "Sample Lesson",
      duration: 42,
      created_at: new Date().toISOString(),
      transcript: [],
      metadata: null,
      study: {
        one_line: "课程摘要。",
        translated_title: "旧译名",
        time_map: [],
        outline: [],
        detailed_notes: "",
        high_fidelity_text: "",
        translated_transcript: [],
        prerequisites: [],
        thought_prompts: [],
        review_suggestions: [],
      },
      local_video_path: null,
      custom_title: false,
      collection_title: "AI Prompting",
      course_index: 1,
      sort_order: 1,
    };
    vi.mocked(listItems).mockResolvedValueOnce([item]);
    vi.mocked(updateCourseItem).mockResolvedValueOnce({
      ...item,
      title: "我的课程标题",
      study: {
        ...item.study,
        translated_title: "我的译文标题",
      },
      custom_title: true,
    });

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "编辑标题 Sample Lesson" }));
    const input = screen.getByLabelText("课程标题") as HTMLInputElement;
    const translatedTitleInput = screen.getByLabelText("译文标题") as HTMLInputElement;
    const collectionSelect = screen.getByLabelText("所属专辑") as HTMLSelectElement;
    fireEvent.change(input, { target: { value: "我的课程标题" } });
    fireEvent.change(translatedTitleInput, { target: { value: "我的译文标题" } });
    expect(collectionSelect.value).toBe("AI Prompting");
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    await waitFor(() => {
      expect(updateCourseItem).toHaveBeenCalledWith(
        "abc123",
        expect.objectContaining({
          title: "我的课程标题",
          translated_title: "我的译文标题",
          collection_title: "AI Prompting",
        }),
      );
    });
    expect((await screen.findAllByText("我的课程标题")).length).toBeGreaterThan(0);
  });

  it("collapses and renames course collections from the library", async () => {
    const first = {
      id: "lesson-1",
      source_url: "https://example.com/lesson-1",
      title: "Lesson One",
      duration: 60,
      created_at: new Date().toISOString(),
      transcript: [],
      metadata: null,
      study: null,
      local_video_path: null,
      collection_title: "AI Prompting",
      course_index: 1,
      sort_order: 1,
    };
    const second = {
      ...first,
      id: "lesson-2",
      source_url: "https://example.com/lesson-2",
      title: "Lesson Two",
      course_index: 2,
      sort_order: 2,
    };
    vi.mocked(listItems).mockResolvedValueOnce([first, second]);
    vi.mocked(updateCourseItem).mockImplementation(async (itemId, input) => ({
      ...(itemId === "lesson-1" ? first : second),
      collection_title: input.collection_title ?? null,
    }));

    render(<App />);

    await waitFor(() => expect(getLibraryCourseButtons("Lesson One").length).toBeGreaterThan(0));
    fireEvent.click(screen.getByRole("button", { name: "收起专辑 AI Prompting" }));
    expect(getLibraryCourseButtons("Lesson One")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "展开专辑 AI Prompting" }));

    fireEvent.click(screen.getByRole("button", { name: "编辑专辑 AI Prompting" }));
    const input = screen.getByLabelText("专辑名称") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "AI Prompting Updated" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    await waitFor(() => {
      expect(updateCourseItem).toHaveBeenCalledWith(
        "lesson-1",
        expect.objectContaining({ collection_title: "AI Prompting Updated" }),
      );
      expect(updateCourseItem).toHaveBeenCalledWith(
        "lesson-2",
        expect.objectContaining({ collection_title: "AI Prompting Updated" }),
      );
    });
    expect(await screen.findByText("AI Prompting Updated")).toBeTruthy();
  });

  it("remembers manual time-map collapse preference", async () => {
    const study = (title: string) => ({
      one_line: "课程摘要。",
      time_map: [{ start: 0, end: 5, title, summary: "分块摘要", priority: "focus" as const }],
      outline: [],
      detailed_notes: "",
      high_fidelity_text: "",
      translated_transcript: [],
      prerequisites: [],
      thought_prompts: [],
      review_suggestions: [],
    });
    const first = {
      id: "lesson-1",
      source_url: "https://example.com/lesson-1",
      title: "Lesson One",
      duration: 60,
      created_at: new Date().toISOString(),
      transcript: [{ start: 0, end: 1, text: "One." }],
      metadata: null,
      study: study("First map"),
      local_video_path: null,
      collection_title: "AI Prompting",
      course_index: 1,
      sort_order: 1,
    };
    const second = {
      ...first,
      id: "lesson-2",
      source_url: "https://example.com/lesson-2",
      title: "Lesson Two",
      study: study("Second map"),
      course_index: 2,
      sort_order: 2,
    };
    vi.mocked(listItems).mockResolvedValueOnce([first, second]);

    render(<App />);

    expect(await screen.findByText("First map")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "收起时间地图" }));
    expect(window.localStorage.getItem("course-navigator-time-map-auto-open")).toBe("false");

    fireEvent.click(screen.getByText("Lesson Two"));
    expect(screen.queryByText("Second map")).toBeNull();
    expect(screen.getByRole("button", { name: "展开时间地图" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "展开时间地图" }));
    expect(window.localStorage.getItem("course-navigator-time-map-auto-open")).toBe("true");
    expect(await screen.findByText("Second map")).toBeTruthy();
  });

  it("restores the last selected course after reloading the workspace", async () => {
    const first = {
      id: "deeplearning-default",
      source_url: "https://learn.deeplearning.ai/courses/example",
      title: "DeepLearning default lesson",
      duration: 60,
      created_at: new Date().toISOString(),
      transcript: [],
      metadata: null,
      study: null,
      local_video_path: null,
    };
    const second = {
      ...first,
      id: "last-edited-video",
      source_url: "https://example.com/last",
      title: "Last edited video",
    };
    window.localStorage.setItem("course-navigator-last-selected-course", "last-edited-video");
    vi.mocked(listItems).mockResolvedValueOnce([first, second]);

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Last edited video" })).toBeTruthy();
  });
});

function installTestLocalStorage() {
  if (
    typeof window.localStorage.getItem === "function" &&
    typeof window.localStorage.setItem === "function" &&
    typeof window.localStorage.removeItem === "function"
  ) {
    return;
  }
  const store = new Map<string, string>();
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => store.set(key, String(value)),
      removeItem: (key: string) => store.delete(key),
      clear: () => store.clear(),
    },
  });
}

function getLibraryCourseButtons(title: string): HTMLElement[] {
  return screen
    .queryAllByText(title)
    .map((node) => node.closest("button.library-item"))
    .filter((button): button is HTMLElement => button instanceof HTMLElement);
}
