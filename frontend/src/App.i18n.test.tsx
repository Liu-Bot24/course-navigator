import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { StrictMode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  bindVideoSource,
  bindVideoSourceFromPicker,
  cancelStudyJob,
  deleteLocalVideo,
  extractCourse,
  getAsrCacheSettings,
  getOnlineAsrSettings,
  getLibraryState,
  getModelSettings,
  getAsrCorrectionResult,
  getStudyJob,
  importLocalVideo,
  importWorkspaceVideoFromPicker,
  listItems,
  previewCourse,
  saveAsrSearchSettings,
  saveAsrCacheSettings,
  saveCookieText,
  saveLibraryState,
  saveOnlineAsrSettings,
  saveModelSettings,
  saveTranscript,
  startAsrCorrectionJob,
  startExtractJob,
  startDownloadJob,
  startStudyJob,
  updateCourseItem,
} from "./api";
import { App } from "./App";
import type { CourseItem, LibraryState, StudyJobStatus } from "./types";

const apiMocks = vi.hoisted(() => ({
  getItem: vi.fn(),
}));

vi.mock("./api", () => ({
  cleanupAsrCache: vi.fn().mockResolvedValue({
    size_bytes: 0,
    threshold_bytes: 524288000,
    auto_cleanup_enabled: true,
    cleaned_bytes: 0,
  }),
  bindVideoSource: vi.fn(),
  bindVideoSourceFromPicker: vi.fn(),
  cancelStudyJob: vi.fn(),
  deleteCourse: vi.fn(),
  deleteLocalVideo: vi.fn(),
  downloadVideo: vi.fn(),
  extractCourse: vi.fn(),
  previewCourse: vi.fn(),
  getModelSettings: vi.fn().mockResolvedValue({
    profiles: [
      {
        id: "default",
        name: "Primary Chat Model",
        provider_type: "openai",
        base_url: "https://api.primary.example/v1",
        model: "provider/primary-chat",
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
  getOnlineAsrSettings: vi.fn().mockResolvedValue({
    provider: "xai",
    openai: { has_api_key: false, api_key_preview: null },
    groq: { has_api_key: true, api_key_preview: "gsk...test" },
    xai: { has_api_key: true, api_key_preview: "xai...test" },
    custom: { base_url: null, model: null, has_api_key: false, api_key_preview: null },
  }),
  getItem: apiMocks.getItem,
  getStudyJob: vi.fn(),
  getAsrCorrectionResult: vi.fn(),
  getLibraryState: vi.fn().mockResolvedValue({
    manual_collections: [],
    manual_collection_groups: [],
    collection_order: [],
    collection_group_order: [],
    collection_group_assignments: {},
  }),
  getAsrSearchSettings: vi.fn().mockResolvedValue({
    enabled: false,
    provider: "tavily",
    result_limit: 5,
    tavily: { base_url: "https://api.tavily.com", has_api_key: false, api_key_preview: null },
    firecrawl: { base_url: null, has_api_key: false, api_key_preview: null },
  }),
  getAsrCacheSettings: vi.fn().mockResolvedValue({
    size_bytes: 0,
    threshold_bytes: 524288000,
    auto_cleanup_enabled: true,
  }),
  importCoursePackage: vi.fn(),
  importLocalVideo: vi.fn(),
  importWorkspaceVideoFromPicker: vi.fn(),
  itemVideoPath: (itemId: string) => `/api/items/${itemId}/video`,
  listAvailableModels: vi.fn(),
  listItems: vi.fn().mockResolvedValue([]),
  saveModelSettings: vi.fn(),
  saveAsrSearchSettings: vi.fn(),
  saveAsrCacheSettings: vi.fn().mockResolvedValue({
    size_bytes: 0,
    threshold_bytes: 524288000,
    auto_cleanup_enabled: true,
  }),
  saveCookieText: vi.fn().mockResolvedValue({ path: "/Users/LQ/cookies/manual.cookies.txt" }),
  saveLibraryState: vi.fn().mockImplementation(async (state) => state),
  saveOnlineAsrSettings: vi.fn().mockResolvedValue({
    provider: "xai",
    openai: { has_api_key: false, api_key_preview: null },
    groq: { has_api_key: true, api_key_preview: "gsk...test" },
    xai: { has_api_key: true, api_key_preview: "xai...test" },
    custom: { base_url: null, model: null, has_api_key: false, api_key_preview: null },
  }),
  saveTranscript: vi.fn(),
  startAsrCorrectionJob: vi.fn(),
  startExtractJob: vi.fn(),
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
    window.localStorage.removeItem("course-navigator-manual-collection-groups");
    window.localStorage.removeItem("course-navigator-collapsed-collections");
    window.localStorage.removeItem("course-navigator-collapsed-collection-groups");
    window.localStorage.removeItem("course-navigator-collection-order");
    window.localStorage.removeItem("course-navigator-collection-group-order");
    window.localStorage.removeItem("course-navigator-collection-group-assignments");
    window.localStorage.removeItem("course-navigator-time-map-auto-open");
    window.localStorage.removeItem("course-navigator-last-selected-course");
    window.localStorage.removeItem("course-navigator-asr-save-accepted-changes");
    window.localStorage.removeItem("course-navigator-asr-sort-by-confidence");
    window.localStorage.removeItem("course-navigator-study-detail-level");
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

  it("saves pasted cookie text and fills the cookie file path", async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "翻译字幕" })).toBeTruthy();
    });

    fireEvent.change(screen.getByRole("combobox", { name: "提取登录" }), {
      target: { value: "cookies" },
    });
    fireEvent.click(screen.getByRole("button", { name: "填写 Cookie" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Cookie 内容" }), {
      target: { value: "Cookie: SID=one" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存 Cookie" }));

    await waitFor(() => {
      expect(saveCookieText).toHaveBeenCalledWith("Cookie: SID=one");
    });
    expect(screen.getByDisplayValue("/Users/LQ/cookies/manual.cookies.txt")).toBeTruthy();
  });

  it("uses a compact default study rail width", async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "翻译字幕" })).toBeTruthy();
    });

    const workspace = document.querySelector(".workspace") as HTMLElement;
    expect(workspace.style.getPropertyValue("--right-rail-width")).toBe("500px");
  });

  it("shows app captions on YouTube embeds without adding a native caption shield", async () => {
    vi.mocked(listItems).mockResolvedValueOnce([
      {
        id: "youtube-captions",
        source_url: "https://www.youtube.com/watch?v=abc123",
        title: "YouTube caption lesson",
        duration: 42,
        created_at: new Date().toISOString(),
        transcript: [{ start: 0, end: 4, text: "Opening idea." }],
        metadata: null,
        study: null,
        local_video_path: null,
      },
    ]);

    const { container } = render(<App />);

    expect(await screen.findByTitle("YouTube caption lesson")).toBeTruthy();
    expect(container.querySelector(".caption-overlay")).toBeTruthy();
    expect(container.querySelector(".caption-native-shield")).toBeNull();
  });

  it("imports local subtitle files from the subtitle source menu", async () => {
    const item: CourseItem = {
      id: "local-upload-course",
      source_url: "https://example.com/video",
      title: "Local upload demo",
      duration: 10,
      created_at: new Date().toISOString(),
      transcript: [],
      metadata: null,
      study: null,
      local_video_path: null,
    };
    const parsedTranscript = [{ start: 1, end: 3.5, text: "Hello world" }];
    vi.mocked(listItems).mockResolvedValueOnce([item]);
    vi.mocked(saveTranscript).mockResolvedValueOnce({ ...item, transcript: parsedTranscript });

    render(<App />);

    expect((await screen.findAllByText("Local upload demo")).length).toBeGreaterThan(0);

    const sourceSelect = screen.getByRole("combobox", { name: "字幕来源" }) as HTMLSelectElement;
    fireEvent.change(sourceSelect, { target: { value: "local_upload" } });
    const file = new File(["1\n00:00:01,000 --> 00:00:03,500\nHello world"], "demo.srt", { type: "text/plain" });
    Object.defineProperty(file, "text", {
      value: vi.fn().mockResolvedValue("1\n00:00:01,000 --> 00:00:03,500\nHello world"),
    });
    fireEvent.change(screen.getByLabelText("上传字幕文件"), {
      target: {
        files: [file],
      },
    });

    await waitFor(() => {
      expect(saveTranscript).toHaveBeenCalledWith("local-upload-course", parsedTranscript);
    });
    expect(sourceSelect.value).toBe("local_upload");
  });

  it("imports local videos from the topbar icon button", async () => {
    const importedItem = {
      id: "local-video",
      source_url: "local-video://local-video",
      title: "Local Video",
      duration: null,
      created_at: new Date().toISOString(),
      transcript: [],
      metadata: null,
      study: null,
      local_video_path: "downloads/local-video.mp4",
    };
    vi.mocked(importLocalVideo).mockResolvedValueOnce(importedItem);

    const { container } = render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "导入本地视频" }));
    const file = new File(["video"], "local-video.mp4", { type: "video/mp4" });
    fireEvent.change(screen.getByLabelText("选择本地视频文件"), {
      target: {
        files: [file],
      },
    });

    await waitFor(() => {
      expect(importLocalVideo).toHaveBeenCalledWith(file);
    });
    expect((await screen.findAllByText("Local Video")).length).toBeGreaterThan(0);
    expect(container.querySelector("video")).toBeTruthy();
  });

  it("does not offer cache-only actions for local imported videos", async () => {
    vi.mocked(listItems).mockResolvedValueOnce([
      {
        id: "local-video",
        source_url: "local-video://local-video",
        title: "Local Video",
        duration: 67.5,
        created_at: new Date().toISOString(),
        transcript: [],
        metadata: null,
        study: null,
        local_video_path: "downloads/local-video.mp4",
      },
    ]);

    render(<App />);

    const cacheButton = await screen.findByRole("button", { name: "缓存" });
    expect((cacheButton as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByRole("button", { name: "移除缓存" })).toBeNull();
    expect(deleteLocalVideo).not.toHaveBeenCalled();
  });

  it("offers binding a video source for imported artifacts without a video file", async () => {
    const importedItem: CourseItem = {
      id: "shared-course",
      source_url: "local-video://original-shared-course",
      title: "Shared Lesson",
      duration: 12,
      created_at: new Date().toISOString(),
      transcript: [{ start: 0, end: 2, text: "Corrected opening." }],
      metadata: null,
      study: {
        one_line: "已有导览",
        translated_title: null,
        time_map: [],
        outline: [],
        detailed_notes: "已有解读",
        high_fidelity_text: "已有详解",
        translated_transcript: [],
        prerequisites: [],
        thought_prompts: [],
        review_suggestions: [],
      },
      local_video_path: null,
    };
    const linkedItem: CourseItem = {
      ...importedItem,
      source_url: "external-video://shared-course",
      video_source_type: "external",
      local_video_path: "/Volumes/NAS/Shared Lesson.mp4",
    };
    vi.mocked(listItems).mockResolvedValueOnce([importedItem]);
    vi.mocked(bindVideoSourceFromPicker).mockResolvedValueOnce(linkedItem);

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "绑定视频源" }));
    fireEvent.click(await screen.findByRole("button", { name: "选择本地或 NAS 文件" }));

    await waitFor(() => {
      expect(bindVideoSourceFromPicker).toHaveBeenCalledWith("shared-course");
    });
    expect(await screen.findByRole("heading", { name: "Shared Lesson" })).toBeTruthy();
    expect((screen.getByRole("button", { name: "本地" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("treats imported local-video artifacts without a path as unbound instead of workspace-cached", async () => {
    vi.mocked(listItems).mockResolvedValueOnce([
      {
        id: "shared-course",
        source_url: "local-video://original-shared-course",
        title: "Shared Lesson",
        duration: 12,
        created_at: new Date().toISOString(),
        transcript: [{ start: 0, end: 2, text: "Corrected opening." }],
        metadata: null,
        study: null,
        local_video_path: null,
      },
    ]);

    render(<App />);

    const cacheButton = await screen.findByRole("button", { name: "缓存" });
    expect((cacheButton as HTMLButtonElement).disabled).toBe(true);
    expect(cacheButton.getAttribute("title")).toBe("缓存");
    expect(await screen.findByRole("button", { name: "导入" })).toBeTruthy();
    expect(await screen.findByRole("button", { name: "绑定视频源" })).toBeTruthy();
  });

  it("imports a missing course video into Workspace from the detail toolbar", async () => {
    const importedItem: CourseItem = {
      id: "shared-course",
      source_url: "local-video://original-shared-course",
      title: "Shared Lesson",
      duration: 12,
      created_at: new Date().toISOString(),
      transcript: [{ start: 0, end: 2, text: "Corrected opening." }],
      metadata: null,
      study: null,
      local_video_path: null,
    };
    const workspaceItem: CourseItem = {
      ...importedItem,
      source_url: "local-video://shared-course",
      video_source_type: "workspace",
      local_video_path: "downloads/shared-course.mp4",
    };
    vi.mocked(listItems).mockResolvedValueOnce([importedItem]);
    vi.mocked(importWorkspaceVideoFromPicker).mockResolvedValueOnce(workspaceItem);

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "导入" }));

    await waitFor(() => {
      expect(importWorkspaceVideoFromPicker).toHaveBeenCalledWith("shared-course");
    });
    expect((await screen.findByRole("button", { name: "本地" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("lets an external linked video source change to an online link", async () => {
    const externalItem: CourseItem = {
      id: "external-course",
      source_url: "external-video://external-course",
      title: "External Lesson",
      duration: 67.5,
      created_at: new Date().toISOString(),
      transcript: [{ start: 0, end: 2, text: "Opening." }],
      metadata: null,
      study: null,
      video_source_type: "external",
      local_video_path: "/Volumes/NAS/External Lesson.mp4",
    };
    const remoteItem: CourseItem = {
      ...externalItem,
      source_url: "https://example.com/new-video",
      video_source_type: "remote",
      local_video_path: null,
    };
    vi.mocked(listItems).mockResolvedValueOnce([externalItem]);
    vi.mocked(bindVideoSource).mockResolvedValueOnce(remoteItem);

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "更换视频源" }));
    fireEvent.change(await screen.findByLabelText("线上视频链接"), { target: { value: "https://example.com/new-video" } });
    fireEvent.click(screen.getByRole("button", { name: "使用线上链接" }));

    await waitFor(() => {
      expect(bindVideoSource).toHaveBeenCalledWith("external-course", {
        source_type: "remote",
        url: "https://example.com/new-video",
      });
    });
  });

  it("keeps direct video source changes disabled for workspace-managed videos", async () => {
    vi.mocked(listItems).mockResolvedValueOnce([
      {
        id: "workspace-video",
        source_url: "local-video://workspace-video",
        title: "Workspace Video",
        duration: 67.5,
        created_at: new Date().toISOString(),
        transcript: [],
        metadata: null,
        study: null,
        video_source_type: "workspace",
        local_video_path: "downloads/workspace-video.mp4",
      },
    ]);

    render(<App />);

    const changeButton = await screen.findByRole("button", { name: "更换视频源" });
    expect((changeButton as HTMLButtonElement).disabled).toBe(true);
    expect(bindVideoSource).not.toHaveBeenCalled();
    expect(bindVideoSourceFromPicker).not.toHaveBeenCalled();
  });

  it("opens a collapsed video source binding manager grouped by collection", async () => {
    vi.mocked(listItems).mockResolvedValueOnce([
      {
        id: "missing-course",
        source_url: "local-video://missing-course",
        title: "Missing Lesson",
        collection_title: "Batch Course",
        course_index: 1,
        duration: 12,
        created_at: new Date().toISOString(),
        transcript: [],
        metadata: null,
        study: null,
        local_video_path: null,
      },
      {
        id: "remote-course",
        source_url: "https://example.com/remote",
        title: "Remote Lesson",
        collection_title: "Batch Course",
        course_index: 2,
        duration: 12,
        created_at: new Date().toISOString(),
        transcript: [],
        metadata: null,
        study: null,
        video_source_type: "remote",
        local_video_path: null,
      },
      {
        id: "external-course",
        source_url: "external-video://external-course",
        title: "External Lesson",
        collection_title: "Batch Course",
        course_index: 3,
        duration: 12,
        created_at: new Date().toISOString(),
        transcript: [],
        metadata: null,
        study: null,
        video_source_type: "external",
        local_video_path: "/Volumes/NAS/External Lesson.mp4",
      },
      {
        id: "workspace-course",
        source_url: "local-video://workspace-course",
        title: "Workspace Lesson",
        collection_title: "Batch Course",
        course_index: 4,
        duration: 12,
        created_at: new Date().toISOString(),
        transcript: [],
        metadata: null,
        study: null,
        video_source_type: "workspace",
        local_video_path: "downloads/workspace-course.mp4",
      },
    ]);

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "管理视频源绑定" }));
    const dialog = await screen.findByRole("dialog", { name: "管理视频源绑定" });
    const modal = within(dialog);

    expect(modal.queryByText("逐行绑定或更换视频源；不会自动匹配，也不会批量提交。")).toBeNull();
    expect(modal.getByRole("button", { name: "展开 Batch Course" })).toBeTruthy();
    expect(modal.queryByText("Missing Lesson")).toBeNull();

    fireEvent.click(modal.getByRole("button", { name: "展开 Batch Course" }));

    expect(modal.getByText("Missing Lesson")).toBeTruthy();
    expect(modal.getByText("Remote Lesson")).toBeTruthy();
    expect(modal.getByText("External Lesson")).toBeTruthy();
    expect(modal.getByText("Workspace Lesson")).toBeTruthy();
    expect(modal.getByText("暂未绑定")).toBeTruthy();
    expect(modal.queryByText("未绑定")).toBeNull();
    expect(modal.getByText("在线视频")).toBeTruthy();
    expect(modal.getByText("文件链接")).toBeTruthy();
    expect(modal.getByText("本地视频")).toBeTruthy();
    expect(modal.getAllByText(/暂未绑定|在线视频|文件链接|本地视频/).every((node) =>
      node.classList.contains("video-source-status"),
    )).toBe(true);
    expect((modal.getByLabelText("视频源 Workspace Lesson") as HTMLInputElement).readOnly).toBe(true);
    expect(modal.queryByRole("button", { name: "绑定 Workspace Lesson" })).toBeNull();
    expect(modal.queryByRole("button", { name: "更换 Workspace Lesson" })).toBeNull();
    const missingBindButton = modal.getByRole("button", { name: "绑定 Missing Lesson" });
    const deleteWorkspaceButton = modal.getByRole("button", { name: "删除 Workspace Lesson" });
    expect(missingBindButton.parentElement?.classList.contains("split")).toBe(true);
    expect(deleteWorkspaceButton.parentElement?.classList.contains("single")).toBe(true);
  });

  it("edits centralized video source rows one at a time", async () => {
    const missingImportItem: CourseItem = {
      id: "missing-import-course",
      source_url: "local-video://missing-course",
      title: "Missing Import Lesson",
      collection_title: "Batch Course",
      course_index: 1,
      duration: 12,
      created_at: new Date().toISOString(),
      transcript: [],
      metadata: null,
      study: null,
      local_video_path: null,
    };
    const missingBindItem: CourseItem = {
      ...missingImportItem,
      id: "missing-bind-course",
      title: "Missing Bind Lesson",
      course_index: 2,
    };
    const remoteItem: CourseItem = {
      id: "remote-course",
      source_url: "https://example.com/remote",
      title: "Remote Lesson",
      collection_title: "Batch Course",
      course_index: 3,
      duration: 12,
      created_at: new Date().toISOString(),
      transcript: [],
      metadata: null,
      study: null,
      video_source_type: "remote",
      local_video_path: null,
    };
    const externalItem: CourseItem = {
      id: "external-course",
      source_url: "external-video://external-course",
      title: "External Lesson",
      collection_title: "Batch Course",
      course_index: 4,
      duration: 12,
      created_at: new Date().toISOString(),
      transcript: [],
      metadata: null,
      study: null,
      video_source_type: "external",
      local_video_path: "/Volumes/NAS/External Lesson.mp4",
    };
    vi.mocked(listItems).mockResolvedValueOnce([missingImportItem, missingBindItem, remoteItem, externalItem]);
    vi.mocked(importWorkspaceVideoFromPicker).mockResolvedValueOnce({
      ...missingImportItem,
      source_url: "local-video://missing-import-course",
      video_source_type: "workspace",
      local_video_path: "downloads/missing-import-course.mp4",
    });
    vi.mocked(bindVideoSourceFromPicker).mockResolvedValueOnce({
      ...missingBindItem,
      source_url: "external-video://missing-bind-course",
      video_source_type: "external",
      local_video_path: "/Volumes/NAS/Missing Bind Lesson.mp4",
    }).mockResolvedValueOnce({
      ...externalItem,
      source_url: "external-video://external-course",
      video_source_type: "external",
      local_video_path: "/Volumes/NAS/External Replacement.mp4",
    });
    vi.mocked(bindVideoSource).mockResolvedValueOnce({
      ...remoteItem,
      source_url: "external-video://remote-course",
      video_source_type: "external",
      local_video_path: "/Volumes/NAS/Remote Lesson.mp4",
    });

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "管理视频源绑定" }));
    const dialog = await screen.findByRole("dialog", { name: "管理视频源绑定" });
    const modal = within(dialog);
    fireEvent.click(modal.getByRole("button", { name: "展开 Batch Course" }));

    expect(modal.queryByRole("button", { name: "保存视频源 Remote Lesson" })).toBeNull();
    fireEvent.click(modal.getByRole("button", { name: "导入 Missing Import Lesson" }));
    await waitFor(() => {
      expect(importWorkspaceVideoFromPicker).toHaveBeenCalledWith("missing-import-course");
    });

    fireEvent.click(modal.getByRole("button", { name: "绑定 Missing Bind Lesson" }));
    await waitFor(() => {
      expect(bindVideoSourceFromPicker).toHaveBeenCalledWith("missing-bind-course");
    });

    fireEvent.click(modal.getByRole("button", { name: "更换 External Lesson" }));
    await waitFor(() => {
      expect(bindVideoSourceFromPicker).toHaveBeenCalledWith("external-course");
    });

    const remoteInput = modal.getByLabelText("视频源 Remote Lesson");
    fireEvent.click(modal.getByRole("button", { name: "更换 Remote Lesson" }));
    expect(bindVideoSourceFromPicker).not.toHaveBeenCalledWith("remote-course");
    expect(modal.getByRole("button", { name: "保存视频源 Remote Lesson" })).toBeTruthy();
    fireEvent.change(remoteInput, { target: { value: "/Volumes/NAS/Remote Lesson.mp4" } });
    expect(modal.getByRole("button", { name: "保存视频源 Remote Lesson" })).toBeTruthy();
    expect(modal.getByRole("button", { name: "取消编辑视频源 Remote Lesson" })).toBeTruthy();
    fireEvent.click(modal.getByRole("button", { name: "保存视频源 Remote Lesson" }));

    await waitFor(() => {
      expect(bindVideoSource).toHaveBeenCalledWith("remote-course", {
        source_type: "external",
        path: "/Volumes/NAS/Remote Lesson.mp4",
      });
    });
  });

  it("deletes workspace local videos from the binding manager without deleting course materials", async () => {
    const workspaceItem: CourseItem = {
      id: "workspace-course",
      source_url: "local-video://workspace-course",
      title: "Workspace Lesson",
      collection_title: "Batch Course",
      course_index: 1,
      duration: 12,
      created_at: new Date().toISOString(),
      transcript: [{ start: 0, end: 2, text: "Opening." }],
      metadata: null,
      study: {
        one_line: "已有导览",
        translated_title: null,
        time_map: [],
        outline: [],
        detailed_notes: "已有解读",
        high_fidelity_text: "已有详解",
        translated_transcript: [],
        prerequisites: [],
        thought_prompts: [],
        review_suggestions: [],
      },
      video_source_type: "workspace",
      local_video_path: "downloads/workspace-course.mp4",
    };
    vi.mocked(listItems).mockResolvedValueOnce([workspaceItem]);
    vi.mocked(deleteLocalVideo).mockResolvedValueOnce({
      ...workspaceItem,
      local_video_path: null,
    });
    vi.spyOn(window, "confirm").mockReturnValueOnce(true);

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "管理视频源绑定" }));
    const dialog = await screen.findByRole("dialog", { name: "管理视频源绑定" });
    const modal = within(dialog);
    fireEvent.click(modal.getByRole("button", { name: "展开 Batch Course" }));

    fireEvent.click(modal.getByRole("button", { name: "删除 Workspace Lesson" }));

    await waitFor(() => {
      expect(deleteLocalVideo).toHaveBeenCalledWith("workspace-course");
    });
    expect(await modal.findByText("暂未绑定")).toBeTruthy();
    expect(modal.getByText("Workspace Lesson")).toBeTruthy();
    expect(modal.getByRole("button", { name: "导入 Workspace Lesson" })).toBeTruthy();
    expect(modal.getByRole("button", { name: "绑定 Workspace Lesson" })).toBeTruthy();
  });

  it("shows structured extraction errors instead of object strings", async () => {
    vi.mocked(listItems).mockResolvedValueOnce([
      {
        id: "local-video",
        source_url: "local-video://local-video",
        title: "Local Video",
        duration: 67.5,
        created_at: new Date().toISOString(),
        transcript: [],
        metadata: null,
        study: null,
        local_video_path: "downloads/local-video.mp4",
      },
    ]);
    vi.mocked(startExtractJob).mockRejectedValueOnce({ detail: "无法读取本地视频音频" });

    render(<App />);

    expect((await screen.findAllByText("Local Video")).length).toBeGreaterThan(0);
    fireEvent.change(screen.getByRole("combobox", { name: "字幕来源" }), { target: { value: "online_asr" } });
    fireEvent.click(screen.getByRole("button", { name: "获取字幕" }));

    expect(await screen.findByText("无法读取本地视频音频")).toBeTruthy();
    expect(screen.queryByText("[object Object]")).toBeNull();
  });

  it("does not force online ASR when no online ASR service is configured", async () => {
    const alertSpy = vi.spyOn(window, "alert").mockImplementation(() => undefined);
    vi.mocked(getOnlineAsrSettings).mockResolvedValueOnce({
      provider: "none",
      openai: { has_api_key: false, api_key_preview: null },
      groq: { has_api_key: false, api_key_preview: null },
      xai: { has_api_key: false, api_key_preview: null },
      custom: { base_url: null, model: null, has_api_key: false, api_key_preview: null },
    });
    const localItem = {
      id: "local-video",
      source_url: "local-video://local-video",
      title: "Local Video",
      duration: 67.5,
      created_at: new Date().toISOString(),
      transcript: [],
      metadata: null,
      study: null,
      local_video_path: "downloads/local-video.mp4",
    };
    vi.mocked(listItems).mockResolvedValueOnce([
      localItem,
    ]).mockResolvedValueOnce([
      {
        ...localItem,
        transcript: [{ start: 0, end: 2, text: "Generated subtitle" }],
      },
    ]);
    vi.mocked(startExtractJob).mockResolvedValueOnce({
      job_id: "extract-job",
      item_id: "local-video",
      status: "succeeded",
      progress: 100,
      phase: "complete",
      message: "字幕提取完成",
      error: null,
    });

    render(<App />);

    expect((await screen.findAllByText("Local Video")).length).toBeGreaterThan(0);
    const sourceSelect = screen.getByRole("combobox", { name: "字幕来源" }) as HTMLSelectElement;
    fireEvent.change(sourceSelect, { target: { value: "online_asr" } });

    await waitFor(() => {
      expect(alertSpy).toHaveBeenCalledWith("尚未配置在线 ASR 模型。请先在模型设置中选择并保存在线 ASR 服务，或将字幕来源改为本地 ASR。");
    });
    expect(sourceSelect.value).toBe("subtitles");
    fireEvent.click(screen.getByRole("button", { name: "获取字幕" }));
    await waitFor(() => {
      expect(startExtractJob).toHaveBeenCalledWith(expect.objectContaining({ subtitle_source: "subtitles" }));
    });
    expect(startExtractJob).not.toHaveBeenCalledWith(expect.objectContaining({ subtitle_source: "online_asr" }));
    alertSpy.mockRestore();
  });

  it("keeps local video playback selected after fetching subtitles", async () => {
    const localItem = {
      id: "local-video",
      source_url: "local-video://local-video",
      title: "Local Video",
      duration: 67.5,
      created_at: new Date().toISOString(),
      transcript: [],
      metadata: null,
      study: null,
      local_video_path: "downloads/local-video.mp4",
    };
    vi.mocked(listItems)
      .mockResolvedValueOnce([localItem])
      .mockResolvedValueOnce([
        {
          ...localItem,
          transcript: [{ start: 0, end: 2, text: "Generated subtitle" }],
        },
      ]);
    vi.mocked(startExtractJob).mockResolvedValueOnce({
      job_id: "extract-job",
      item_id: "local-video",
      status: "succeeded",
      progress: 100,
      phase: "complete",
      message: "字幕提取完成",
      error: null,
    });

    const { container } = render(<App />);

    await waitFor(() => {
      expect(container.querySelector("video")).toBeTruthy();
    });
    fireEvent.change(screen.getByRole("combobox", { name: "字幕来源" }), { target: { value: "online_asr" } });
    fireEvent.click(screen.getByRole("button", { name: "获取字幕" }));

    await waitFor(() => {
      expect(startExtractJob).toHaveBeenCalledWith(expect.objectContaining({ url: "local-video://local-video" }));
    });
    await waitFor(() => {
      expect(container.querySelector("video")).toBeTruthy();
    });
    expect(screen.queryByText("这个来源暂时不能嵌入播放，但字幕导航仍可使用。")).toBeNull();
    expect(screen.getByRole("button", { name: "本地" }).className).toContain("active");
  });

  it("uses the extraction job for source-first local video fallback progress", async () => {
    const localItem = {
      id: "local-video",
      source_url: "local-video://local-video",
      title: "Local Video",
      duration: 67.5,
      created_at: new Date().toISOString(),
      transcript: [],
      metadata: null,
      study: null,
      local_video_path: "downloads/local-video.mp4",
    };
    vi.mocked(listItems)
      .mockResolvedValueOnce([localItem])
      .mockResolvedValueOnce([
        {
          ...localItem,
          transcript: [{ start: 0, end: 2, text: "Generated subtitle" }],
        },
      ]);
    vi.mocked(startExtractJob).mockResolvedValueOnce({
      job_id: "extract-job",
      item_id: "local-video",
      status: "succeeded",
      progress: 100,
      phase: "complete",
      message: "字幕提取完成",
      error: null,
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "获取字幕" })).toBeTruthy();
    });
    expect((screen.getByRole("combobox", { name: "字幕来源" }) as HTMLSelectElement).value).toBe("subtitles");
    fireEvent.click(screen.getByRole("button", { name: "获取字幕" }));

    await waitFor(() => {
      expect(startExtractJob).toHaveBeenCalledWith(
        expect.objectContaining({
          url: "local-video://local-video",
          subtitle_source: "subtitles",
        }),
      );
    });
    expect(extractCourse).not.toHaveBeenCalled();
  });

  it("supports keyboard review shortcuts for ASR suggestions", async () => {
    const item: CourseItem = {
      id: "asr-lesson",
      source_url: "https://example.com/asr-lesson",
      title: "ASR Lesson",
      duration: 12,
      created_at: new Date().toISOString(),
      transcript: [
        { start: 0, end: 2, text: "我是林毅" },
        { start: 2, end: 4, text: "Deep Seek V4 很强" },
      ],
      metadata: null,
      study: null,
      local_video_path: null,
    };
    vi.mocked(listItems).mockResolvedValueOnce([item]);
    vi.mocked(saveAsrSearchSettings).mockResolvedValue({
      enabled: false,
      provider: "tavily",
      result_limit: 5,
      tavily: { base_url: "https://api.tavily.com", has_api_key: false, api_key_preview: null },
      firecrawl: { base_url: null, has_api_key: false, api_key_preview: null },
    });
    vi.mocked(startAsrCorrectionJob).mockResolvedValueOnce({
      job_id: "asr-job",
      item_id: "asr-lesson",
      status: "succeeded",
      progress: 100,
      phase: "complete",
      message: "完成",
      error: null,
    });
    vi.mocked(getAsrCorrectionResult).mockResolvedValueOnce({
      job_id: "asr-job",
      item_id: "asr-lesson",
      generated_at: new Date().toISOString(),
      search_enabled: false,
      search_provider: null,
      suggestions: [
        {
          id: "name-fix",
          segment_index: 0,
          start: 0,
          end: 2,
          original_text: "林毅",
          corrected_text: "林亦LYi",
          confidence: 0.91,
          reason: "人名校正",
          evidence: null,
          status: "pending",
          source: "model",
        },
        {
          id: "term-fix",
          segment_index: 1,
          start: 2,
          end: 4,
          original_text: "Deep Seek",
          corrected_text: "DeepSeek",
          confidence: 0.99,
          reason: "术语校正",
          evidence: null,
          status: "pending",
          source: "model",
        },
      ],
    });

    render(<App />);

    await waitFor(() => expect(screen.getAllByText("ASR Lesson").length).toBeGreaterThan(0));
    fireEvent.click(screen.getByRole("button", { name: "ASR 校正" }));
    fireEvent.click(await screen.findByRole("button", { name: "生成校正建议" }));

    await screen.findByText("1/2");
    expect(screen.getByRole("button", { name: "再次生成校正建议" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "再次校正" })).toBeNull();
    const sourceEditor = document.querySelector(".asr-transcript-pane.source textarea") as HTMLTextAreaElement;
    sourceEditor.focus();
    fireEvent.keyDown(window, { key: "ArrowDown" });
    expect(screen.getByText("1/2")).toBeTruthy();

    sourceEditor.blur();
    fireEvent.keyDown(window, { key: "ArrowDown" });
    expect(await screen.findByText("2/2")).toBeTruthy();
    expect(await screen.findByText("术语校正")).toBeTruthy();
    expect(await screen.findByRole("dialog", { name: "理由 / 证据" })).toBeTruthy();

    fireEvent.keyDown(window, { key: "Enter" });
    await waitFor(() => {
      expect(screen.getByText("待处理 1 · 已接受 1 · 已拒绝 0")).toBeTruthy();
    });
    expect(screen.getByText("1/1")).toBeTruthy();
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

    expect(await screen.findAllByText("bilibili站外播放不提供字幕时间轴功能，建议缓存后观看。")).not.toHaveLength(0);
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

  it("exports course packages without local workspace video paths", async () => {
    let exportedBlob: Blob | null = null;
    const createObjectUrl = vi.spyOn(URL, "createObjectURL").mockImplementation((blob) => {
      exportedBlob = blob as Blob;
      return "blob:course-package";
    });
    const revokeObjectUrl = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    vi.mocked(listItems).mockResolvedValueOnce([
      {
        id: "cached-course",
        source_url: "https://example.com/video",
        title: "Cached Course",
        duration: 60,
        created_at: new Date().toISOString(),
        transcript: [{ start: 0, end: 2, text: "Opening." }],
        metadata: null,
        study: {
          one_line: "课程摘要。",
          time_map: [],
          outline: [],
          detailed_notes: "",
          high_fidelity_text: "",
          translated_transcript: [],
          prerequisites: [],
          thought_prompts: [],
          review_suggestions: [],
        },
        local_video_path: "downloads/cached-course.mp4",
      },
    ]);

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "导出课程" }));
    fireEvent.click(await screen.findByRole("button", { name: "导出所选" }));

    await waitFor(() => {
      expect(exportedBlob).toBeTruthy();
    });
    const exported = JSON.parse(await readBlobText(exportedBlob!));
    expect(exported.format).toBe("course-navigator-share");
    expect(exported.items[0].id).toBe("cached-course");
    expect(exported.items[0].study.one_line).toBe("课程摘要。");
    expect(exported.items[0].transcript[0].text).toBe("Opening.");
    expect(exported.items[0]).not.toHaveProperty("local_video_path");
    expect(JSON.stringify(exported)).not.toContain("downloads/cached-course.mp4");

    anchorClick.mockRestore();
    revokeObjectUrl.mockRestore();
    createObjectUrl.mockRestore();
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
    let resolveExtractJob!: (status: {
      job_id: string;
      item_id: string;
      status: "succeeded";
      progress: number;
      phase: string;
      message: string;
      error: null;
    }) => void;
    vi.mocked(listItems).mockResolvedValueOnce([]).mockResolvedValueOnce([extractedItem]);
    vi.mocked(previewCourse).mockResolvedValueOnce(previewItem);
    vi.mocked(startExtractJob).mockReturnValueOnce(new Promise((resolve) => {
      resolveExtractJob = resolve;
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
    expect(screen.getByText("正在提取字幕 0%")).toBeTruthy();
    await act(async () => {
      resolveExtractJob({
        job_id: "extract-job",
        item_id: "dlai-lesson",
        status: "succeeded",
        progress: 100,
        phase: "complete",
        message: "字幕提取完成",
        error: null,
      });
    });
    expect(await screen.findByText("Opening idea.")).toBeTruthy();
    expect(startExtractJob).toHaveBeenCalledWith(expect.objectContaining({ url: "https://learn.deeplearning.ai/courses/example" }));
    expect(extractCourse).not.toHaveBeenCalled();
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
    vi.mocked(listItems).mockResolvedValueOnce([]).mockResolvedValueOnce([previewItem]);
    vi.mocked(previewCourse).mockResolvedValueOnce(previewItem);
    vi.mocked(startExtractJob).mockResolvedValueOnce({
      job_id: "extract-job",
      item_id: "dlai-lesson",
      status: "succeeded",
      progress: 100,
      phase: "complete",
      message: "字幕提取完成",
      error: null,
    });
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
      expect(startExtractJob).toHaveBeenCalledWith(
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
    const modelApiKey = screen.getByLabelText("API Key") as HTMLInputElement;
    expect(modelApiKey.value).toBe("sk...test");
    expect(modelApiKey.placeholder).toBe("");
    expect(screen.getByText("高级调用参数")).toBeTruthy();
    expect(screen.queryByText("上下文窗口上限（选填）")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /高级调用参数/ }));
    expect(screen.getByText("模型能力覆盖")).toBeTruthy();
    expect(screen.getByText("任务策略覆盖")).toBeTruthy();
    expect(screen.getByText("上下文窗口上限（选填）")).toBeTruthy();
    expect(screen.getByText("最大输出上限（选填）")).toBeTruthy();
  });

  it("configures online ASR presets from the main settings dialog", async () => {
    vi.mocked(saveModelSettings).mockResolvedValueOnce({
      profiles: [
        {
          id: "default",
          name: "Primary Chat Model",
          provider_type: "openai",
          base_url: "https://api.primary.example/v1",
          model: "provider/primary-chat",
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
    });
    vi.mocked(saveOnlineAsrSettings).mockResolvedValueOnce({
      provider: "xai",
      openai: { has_api_key: false, api_key_preview: null },
      groq: { has_api_key: true, api_key_preview: "gsk...test" },
      xai: { has_api_key: true, api_key_preview: "xai...test" },
      custom: { base_url: null, model: null, has_api_key: false, api_key_preview: null },
    });

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "模型设置" }));
    fireEvent.click(await screen.findByRole("button", { name: "ASR" }));
    fireEvent.change(screen.getByLabelText("在线 ASR 服务"), { target: { value: "xai" } });
    const onlineAsrKey = await screen.findByLabelText("在线 ASR API Key") as HTMLInputElement;
    expect(onlineAsrKey.value).toBe("xai...test");
    expect(onlineAsrKey.placeholder).toBe("");
    fireEvent.change(onlineAsrKey, { target: { value: "xai-new-key" } });
    fireEvent.click(screen.getByRole("button", { name: "保存档案" }));

    await waitFor(() => {
      expect(saveOnlineAsrSettings).toHaveBeenCalledWith(
        expect.objectContaining({
          provider: "xai",
          xai: { api_key: "xai-new-key" },
        }),
      );
    });
  });

  it("auto-saves model slot changes without saving the profile draft", async () => {
    const settings = {
      profiles: [
        {
          id: "default",
          name: "Primary Chat Model",
          provider_type: "openai" as const,
          base_url: "https://api.primary.example/v1",
          model: "provider/primary-chat",
          context_window: null,
          max_tokens: null,
          has_api_key: true,
          api_key_preview: "sk...test",
        },
        {
          id: "mimo",
          name: "Secondary Chat Model",
          provider_type: "anthropic" as const,
          base_url: "https://api.secondary.example/anthropic/v1",
          model: "provider/secondary-chat",
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
    expect(payload.profiles.map((profile) => profile.name)).toEqual(["Primary Chat Model", "Secondary Chat Model"]);
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
    const apiKey = screen.getByLabelText("API Key") as HTMLInputElement;
    const model = screen.getByLabelText("模型") as HTMLInputElement;
    fireEvent.click(screen.getByRole("button", { name: /高级调用参数/ }));
    const contextWindow = screen.getByLabelText("上下文窗口上限（选填）") as HTMLInputElement;
    const maxTokens = screen.getByLabelText("最大输出上限（选填）") as HTMLInputElement;

    expect(activeProfile.options[activeProfile.selectedIndex]?.textContent).toBe("未命名档案");
    expect(profileName.value).toBe("");
    expect(baseUrl.value).toBe("");
    expect(apiKey.value).toBe("");
    expect(apiKey.placeholder).toBe("");
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

  it("ignores untouched blank model profile drafts when saving settings", async () => {
    vi.mocked(saveModelSettings).mockImplementationOnce(async (input) => ({
      profiles: input.profiles.map((profile) => ({
        id: profile.id,
        name: profile.name,
        provider_type: profile.provider_type,
        base_url: profile.base_url,
        model: profile.model,
        context_window: profile.context_window,
        max_tokens: profile.max_tokens,
        has_api_key: Boolean(profile.api_key),
        api_key_preview: profile.api_key ? "sk...test" : null,
      })),
      translation_model_id: input.translation_model_id,
      learning_model_id: input.learning_model_id,
      global_model_id: input.global_model_id,
      asr_model_id: input.asr_model_id,
      study_detail_level: input.study_detail_level,
      task_parameters: input.task_parameters,
    }));

    render(<App />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "模型设置" })).toBeTruthy();
    });

    fireEvent.click(screen.getByRole("button", { name: "模型设置" }));
    fireEvent.click(await screen.findByRole("button", { name: "新增档案" }));
    fireEvent.change(screen.getByLabelText("正在编辑"), { target: { value: "default" } });
    fireEvent.click(screen.getByRole("button", { name: "保存档案" }));

    await waitFor(() => {
      expect(saveModelSettings).toHaveBeenCalledTimes(1);
    });
    const payload = vi.mocked(saveModelSettings).mock.calls[0][0];
    expect(payload.profiles).toHaveLength(1);
    expect(payload.profiles).toEqual([
      expect.objectContaining({
        id: "default",
        base_url: "https://api.primary.example/v1",
        model: "provider/primary-chat",
      }),
    ]);
  });

  it("treats provider format as a profile option and allows decimal temperature input", async () => {
    vi.mocked(getModelSettings).mockResolvedValueOnce({
      profiles: [
        {
          id: "default",
          name: "Primary Chat Model",
          provider_type: "openai",
          base_url: "https://api.primary.example/v1",
          model: "provider/primary-chat",
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
    expect((screen.getByLabelText("档案名称") as HTMLInputElement).value).toBe("Primary Chat Model");
    expect(baseUrl.value).toBe("https://api.primary.example/v1");
    expect(model.value).toBe("provider/primary-chat");
    expect(contextWindow.value).toBe("160000");
    expect(maxTokens.value).toBe("24000");
    expect(titleTemperature.value).toBe("0.3");
    expect(titleMaxTokens.value).toBe("512");

    fireEvent.change(providerType, { target: { value: "anthropic" } });

    expect(providerType.value).toBe("anthropic");
    expect((screen.getByLabelText("档案名称") as HTMLInputElement).value).toBe("Primary Chat Model");
    expect(baseUrl.value).toBe("https://api.primary.example/v1");
    expect(baseUrl.placeholder).toBe("https://api.anthropic.com/v1");
    expect(model.value).toBe("provider/primary-chat");
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

    fireEvent.click(await screen.findByRole("button", { name: "展开学习地图设置" }));
    expect(await screen.findByText("详细程度")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "全部重新生成" })).toBeNull();
    const settingsGenerateButton = screen
      .getAllByRole("button", { name: "生成学习地图" })
      .find((button) => button.closest(".study-settings-panel")) as HTMLButtonElement | undefined;
    expect(settingsGenerateButton).toBeTruthy();
    expect(settingsGenerateButton?.disabled).toBe(true);
  });

  it("can regenerate the full study map from the right-rail settings panel", async () => {
    const item: CourseItem = {
      id: "abc123",
      source_url: "https://www.youtube.com/watch?v=abc123",
      title: "Sample Lesson",
      duration: 42,
      created_at: new Date().toISOString(),
      transcript: [{ start: 0, end: 4, text: "Opening idea corrected." }],
      metadata: null,
      study: {
        one_line: "课程摘要。",
        translated_title: null,
        time_map: [{ start: 0, end: 4, title: "开场", summary: "开场观点。", priority: "focus" }],
        outline: [],
        detailed_notes: "旧解读",
        high_fidelity_text: "旧详解",
        translated_transcript: [],
        prerequisites: [],
        thought_prompts: [],
        review_suggestions: [],
      },
      local_video_path: null,
    };
    vi.mocked(listItems).mockResolvedValue([item]);
    const completedJob: StudyJobStatus = {
      job_id: "study-job-1",
      item_id: "abc123",
      status: "succeeded",
      progress: 100,
      phase: "complete",
      message: "学习材料已生成",
      error: null,
      started_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    vi.mocked(startStudyJob).mockResolvedValue(completedJob);

    render(<App />);

    expect(screen.queryByRole("button", { name: "全部重新生成" })).toBeNull();
    const settingsToggle = await screen.findByRole("button", { name: "展开学习地图设置" });
    expect(settingsToggle.closest(".ai-tab-strip")).toBeTruthy();
    expect(settingsToggle.closest(".ai-tabs")).toBeNull();
    fireEvent.click(settingsToggle);

    const fullRegenerateButton = await screen.findByRole("button", { name: "全部重新生成" });
    expect(fullRegenerateButton.closest(".study-settings-panel")).toBeTruthy();
    expect(fullRegenerateButton.closest(".video-caption-toolbar")).toBeNull();
    expect(fullRegenerateButton.compareDocumentPosition(screen.getByText("详细程度")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    fireEvent.click(fullRegenerateButton);

    await waitFor(() => {
      expect(startStudyJob).toHaveBeenCalledWith("abc123", "zh-CN", "all", "standard");
    });
  });

  it("starts study regeneration when mounted under React StrictMode", async () => {
    const item: CourseItem = {
      id: "strict-study",
      source_url: "https://www.youtube.com/watch?v=strict",
      title: "Strict Study Lesson",
      duration: 42,
      created_at: new Date().toISOString(),
      transcript: [{ start: 0, end: 4, text: "Opening idea." }],
      metadata: null,
      study: {
        one_line: "课程摘要。",
        translated_title: null,
        time_map: [{ start: 0, end: 4, title: "开场", summary: "开场观点。", priority: "focus" }],
        outline: [],
        detailed_notes: "旧解读",
        high_fidelity_text: "旧详解",
        translated_transcript: [],
        prerequisites: [],
        thought_prompts: [],
        review_suggestions: [],
      },
      local_video_path: null,
    };
    vi.mocked(listItems).mockResolvedValue([item]);
    vi.mocked(startStudyJob).mockResolvedValue({
      job_id: "strict-study-job",
      item_id: "strict-study",
      status: "succeeded",
      progress: 100,
      phase: "complete",
      message: "学习材料已生成",
      error: null,
      started_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });

    render(
      <StrictMode>
        <App />
      </StrictMode>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "展开学习地图设置" }));
    fireEvent.click(screen.getByRole("button", { name: "全部重新生成" }));

    await waitFor(() => {
      expect(startStudyJob).toHaveBeenCalledWith("strict-study", "zh-CN", "all", "standard");
    });
  });

  it("starts first study map generation when mounted under React StrictMode", async () => {
    const item: CourseItem = {
      id: "strict-new-study",
      source_url: "https://www.youtube.com/watch?v=strict-new",
      title: "Strict New Study Lesson",
      duration: 42,
      created_at: new Date().toISOString(),
      transcript: [{ start: 0, end: 4, text: "Opening idea." }],
      metadata: null,
      study: null,
      local_video_path: null,
    };
    vi.mocked(listItems).mockResolvedValue([item]);
    vi.mocked(startStudyJob).mockResolvedValue({
      job_id: "strict-new-study-job",
      item_id: "strict-new-study",
      status: "succeeded",
      progress: 100,
      phase: "complete",
      message: "学习材料已生成",
      error: null,
      started_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });

    render(
      <StrictMode>
        <App />
      </StrictMode>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "生成学习地图" }));

    await waitFor(() => {
      expect(startStudyJob).toHaveBeenCalledWith("strict-new-study", "zh-CN", "all", "standard");
    });
  });

  it("labels first study-map generation as generation instead of regeneration", async () => {
    const item: CourseItem = {
      id: "first-study-label",
      source_url: "https://www.youtube.com/watch?v=first-label",
      title: "First Study Label Lesson",
      duration: 42,
      created_at: new Date().toISOString(),
      transcript: [{ start: 0, end: 4, text: "Opening idea." }],
      metadata: null,
      study: null,
      local_video_path: null,
    };
    vi.mocked(listItems).mockResolvedValue([item]);
    vi.mocked(startStudyJob).mockResolvedValue({
      job_id: "first-study-label-job",
      item_id: "first-study-label",
      status: "running",
      progress: 12,
      phase: "guide",
      message: "正在生成学习导览",
      error: null,
    });
    vi.mocked(getStudyJob).mockImplementation(
      () =>
        new Promise<StudyJobStatus>(() => {
          // Keep the job running so the status strip remains visible.
        }),
    );

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "生成学习地图" }));

    expect(await screen.findByText("First Study Label Lesson · 生成学习地图")).toBeTruthy();
    expect(screen.queryByText(/First Study Label Lesson · 全部重新生成/)).toBeNull();
  });

  it("shows beginner and experienced guide suggestions as additional guide modules", async () => {
    const item: CourseItem = {
      id: "abc123",
      source_url: "https://www.youtube.com/watch?v=abc123",
      title: "Sample Lesson",
      duration: 42,
      created_at: new Date().toISOString(),
      transcript: [{ start: 0, end: 4, text: "Opening idea corrected." }],
      metadata: null,
      study: {
        one_line: "这节课帮助学习者判断基础概念和实践应用的学习重点。",
        translated_title: null,
        time_map: [{ start: 0, end: 4, title: "开场", summary: "开场观点。", priority: "focus" }],
        outline: [],
        detailed_notes: "旧解读",
        high_fidelity_text: "旧详解",
        translated_transcript: [],
        prerequisites: ["先了解基本术语。"],
        thought_prompts: ["这个概念能用在哪里？"],
        review_suggestions: ["看完后复盘一次关键判断。"],
        beginner_focus: ["刚接触这个领域的人，建议重点听基础概念。"],
        experienced_guidance: ["有经验的人可以略过定义，复习实践判断。"],
      },
      local_video_path: null,
    };
    vi.mocked(listItems).mockResolvedValue([item]);

    render(<App />);

    expect(await screen.findByText("这节课帮助学习者判断基础概念和实践应用的学习重点。")).toBeTruthy();
    expect(screen.getByText("已整理为 1 个学习块")).toBeTruthy();
    expect(await screen.findByText("初学学习建议")).toBeTruthy();
    expect(screen.getByText("刚接触这个领域的人，建议重点听基础概念。")).toBeTruthy();
    expect(screen.getByText("进阶学习建议")).toBeTruthy();
    expect(screen.getByText("有经验的人可以略过定义，复习实践判断。")).toBeTruthy();
    expect(screen.getByText("预备知识")).toBeTruthy();
    expect(screen.getByText("思考提示")).toBeTruthy();
    expect(screen.getByText("复习建议")).toBeTruthy();
  });

  it("persists the study detail mode and sends high fidelity to study jobs", async () => {
    const item: CourseItem = {
      id: "abc123",
      source_url: "https://www.youtube.com/watch?v=abc123",
      title: "Sample Lesson",
      duration: 42,
      created_at: new Date().toISOString(),
      transcript: [{ start: 0, end: 4, text: "Opening idea." }],
      metadata: null,
      study: {
        one_line: "课程摘要。",
        translated_title: null,
        time_map: [{ start: 0, end: 4, title: "开场", summary: "开场观点。", priority: "focus" }],
        outline: [],
        detailed_notes: "旧解读",
        high_fidelity_text: "旧详解",
        translated_transcript: [],
        prerequisites: [],
        thought_prompts: [],
        review_suggestions: [],
      },
      local_video_path: null,
    };
    vi.mocked(listItems).mockResolvedValue([item]);
    vi.mocked(startStudyJob).mockResolvedValue({
      job_id: "study-job-1",
      item_id: "abc123",
      status: "succeeded",
      progress: 100,
      phase: "complete",
      message: "学习材料已生成",
      error: null,
      started_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "展开学习地图设置" }));
    fireEvent.click(screen.getByRole("button", { name: "高保真" }));
    fireEvent.click(screen.getByRole("button", { name: "全部重新生成" }));

    await waitFor(() => {
      expect(startStudyJob).toHaveBeenCalledWith("abc123", "zh-CN", "all", "faithful");
    });
    expect(window.localStorage.getItem("course-navigator-study-detail-level")).toBe("faithful");
  });

  it("keeps the player action bar visible for Bilibili embed without subtitle timeline controls", async () => {
    const item: CourseItem = {
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
      study: {
        one_line: "课程摘要。",
        translated_title: null,
        time_map: [{ start: 0, end: 2, title: "开场", summary: "开场观点。", priority: "focus" }],
        outline: [],
        detailed_notes: "旧解读",
        high_fidelity_text: "旧详解",
        translated_transcript: [],
        prerequisites: [],
        thought_prompts: [],
        review_suggestions: [],
      },
      local_video_path: null,
    };
    vi.mocked(listItems).mockResolvedValue([item]);
    vi.mocked(startStudyJob).mockResolvedValue({
      job_id: "study-job-1",
      item_id: "bili-lesson",
      status: "succeeded",
      progress: 100,
      phase: "complete",
      message: "学习材料已生成",
      error: null,
      started_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });

    render(<App />);

    expect(await screen.findAllByText("bilibili站外播放不提供字幕时间轴功能，建议缓存后观看。")).not.toHaveLength(0);
    fireEvent.click(await screen.findByRole("button", { name: "展开学习地图设置" }));
    const fullRegenerateButton = await screen.findByRole("button", { name: "全部重新生成" });
    expect(fullRegenerateButton.closest(".study-settings-panel")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "浮动字幕" })).toBeNull();

    fireEvent.click(fullRegenerateButton);

    await waitFor(() => {
      expect(startStudyJob).toHaveBeenCalledWith("bili-lesson", "zh-CN", "all", "standard");
    });
  });

  it("refreshes study material while a study job is still running", async () => {
    const item: CourseItem = {
      id: "abc123",
      source_url: "https://www.youtube.com/watch?v=abc123",
      title: "Sample Lesson",
      duration: 42,
      created_at: new Date().toISOString(),
      transcript: [{ start: 0, end: 4, text: "Opening idea." }],
      metadata: null,
      study: null,
      local_video_path: null,
    };
    const partialItem: CourseItem = {
      ...item,
      study: {
        one_line: "先出的导览。",
        translated_title: null,
        time_map: [],
        outline: [],
        detailed_notes: "",
        high_fidelity_text: "",
        translated_transcript: [],
        prerequisites: ["先出的预备知识"],
        thought_prompts: [],
        review_suggestions: [],
      },
    };
    let resolveSecondStatus: ((value: StudyJobStatus) => void) | undefined;
    vi.mocked(listItems).mockResolvedValue([item]);
    apiMocks.getItem.mockResolvedValue(partialItem);
    vi.mocked(startStudyJob).mockResolvedValue({
      job_id: "study-job-1",
      item_id: "abc123",
      status: "running",
      progress: 12,
      phase: "guide",
      message: "正在生成学习导览",
      error: null,
    });
    vi.mocked(getStudyJob)
      .mockResolvedValueOnce({
        job_id: "study-job-1",
        item_id: "abc123",
        status: "running",
        progress: 18,
        phase: "guide",
        message: "正在生成学习导览",
        error: null,
      })
      .mockImplementationOnce(
        () =>
          new Promise<StudyJobStatus>((resolve) => {
            resolveSecondStatus = resolve;
          }),
      );

    render(<App />);

    const generateButton = await screen.findByRole("button", { name: "生成学习地图" });
    fireEvent.click(generateButton);

    expect(await screen.findByText("先出的预备知识", {}, { timeout: 2500 })).toBeTruthy();
    expect(apiMocks.getItem).toHaveBeenCalledWith("abc123");
    const firstItemRefreshOrder = apiMocks.getItem.mock.invocationCallOrder[0];
    expect(vi.mocked(listItems).mock.invocationCallOrder.some((order) => order > firstItemRefreshOrder)).toBe(false);
    resolveSecondStatus?.({
      job_id: "study-job-1",
      item_id: "abc123",
      status: "succeeded",
      progress: 100,
      phase: "complete",
      message: "学习材料已生成",
      error: null,
    });
    await waitFor(() => expect(getStudyJob).toHaveBeenCalledTimes(2), { timeout: 3500 });
    expect(vi.mocked(listItems).mock.invocationCallOrder.some((order) => order > firstItemRefreshOrder)).toBe(false);
  });

  it("does not steal course selection while a study job refreshes in the background", async () => {
    vi.mocked(listItems).mockReset();
    vi.mocked(startStudyJob).mockReset();
    vi.mocked(getStudyJob).mockReset();
    const existingStudy = {
      one_line: "旧课程导览。",
      translated_title: null,
      time_map: [{ start: 0, end: 4, title: "旧学习块", summary: "旧学习块摘要。", priority: "focus" as const }],
      outline: [],
      detailed_notes: "",
      high_fidelity_text: "",
      translated_transcript: [],
      prerequisites: [],
      thought_prompts: [],
      review_suggestions: [],
    };
    const generatingItem: CourseItem = {
      id: "generating-lesson",
      source_url: "https://www.youtube.com/watch?v=generating",
      title: "Generating Lesson",
      duration: 42,
      created_at: new Date().toISOString(),
      transcript: [{ start: 0, end: 4, text: "Opening idea." }],
      metadata: null,
      study: existingStudy,
      local_video_path: null,
    };
    const otherItem: CourseItem = {
      id: "other-lesson",
      source_url: "https://www.youtube.com/watch?v=other",
      title: "Other Lesson",
      duration: 120,
      created_at: new Date().toISOString(),
      transcript: [{ start: 0, end: 5, text: "Other opening." }],
      metadata: null,
      study: null,
      local_video_path: null,
    };
    const partialGeneratingItem: CourseItem = {
      ...generatingItem,
      study: {
        ...existingStudy,
        one_line: "生成中的课程导览。",
        prerequisites: ["生成中的预备知识"],
      },
    };
    vi.mocked(listItems).mockResolvedValueOnce([generatingItem, otherItem]).mockResolvedValue([partialGeneratingItem, otherItem]);
    vi.mocked(startStudyJob).mockResolvedValue({
      job_id: "study-job-1",
      item_id: "generating-lesson",
      status: "running",
      progress: 12,
      phase: "guide",
      message: "正在生成学习导览",
      error: null,
    });
    vi.mocked(getStudyJob)
      .mockResolvedValueOnce({
        job_id: "study-job-1",
        item_id: "generating-lesson",
        status: "running",
        progress: 18,
        phase: "guide",
        message: "正在生成学习导览",
        error: null,
      })
      .mockResolvedValueOnce({
        job_id: "study-job-1",
        item_id: "generating-lesson",
        status: "succeeded",
        progress: 100,
        phase: "complete",
        message: "学习材料已生成",
        error: null,
      });

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "展开学习地图设置" }));
    fireEvent.click(await screen.findByRole("button", { name: "全部重新生成" }));
    await waitFor(() => expect(startStudyJob).toHaveBeenCalledWith("generating-lesson", "zh-CN", "all", "standard"));
    fireEvent.click(getLibraryCourseButtons("Other Lesson")[0]);

    await waitFor(() => expect(getStudyJob).toHaveBeenCalledTimes(2), { timeout: 3500 });
    expect(screen.getByRole("heading", { name: "Other Lesson" })).toBeTruthy();
  });

  it("lets the user stop the current study map generation job", async () => {
    vi.mocked(listItems).mockReset();
    vi.mocked(startStudyJob).mockReset();
    vi.mocked(getStudyJob).mockReset();
    vi.mocked(cancelStudyJob).mockReset();
    const lesson = studyQueueCourse("lesson-a", "Lesson A");
    vi.mocked(listItems).mockResolvedValue([lesson]);
    vi.mocked(startStudyJob).mockResolvedValue({
      job_id: "lesson-a-all",
      item_id: "lesson-a",
      status: "running",
      progress: 18,
      phase: "learning_blocks",
      message: "正在生成学习块 1/58",
      error: null,
    });
    vi.mocked(cancelStudyJob).mockResolvedValue({
      job_id: "lesson-a-all",
      item_id: "lesson-a",
      status: "cancelled",
      progress: 100,
      phase: "cancelled",
      message: "学习地图生成已取消",
      error: null,
    });
    vi.mocked(getStudyJob).mockResolvedValue({
      job_id: "lesson-a-all",
      item_id: "lesson-a",
      status: "cancelled",
      progress: 100,
      phase: "cancelled",
      message: "学习地图生成已取消",
      error: null,
    });

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "展开学习地图设置" }));
    fireEvent.click(await screen.findByRole("button", { name: "全部重新生成" }));

    const stopButton = await screen.findByRole("button", { name: "停止生成学习地图" });
    fireEvent.click(stopButton);

    await waitFor(() => expect(cancelStudyJob).toHaveBeenCalledWith("lesson-a-all"));
  });

  it("queues study rebuild clicks across courses and sections in click order", async () => {
    vi.mocked(listItems).mockReset();
    vi.mocked(startStudyJob).mockReset();
    vi.mocked(getStudyJob).mockReset();
    const lessonA = studyQueueCourse("lesson-a", "Lesson A");
    const lessonB = studyQueueCourse("lesson-b", "Lesson B");
    const lessonC = studyQueueCourse("lesson-c", "Lesson C");
    vi.mocked(listItems).mockResolvedValue([lessonA, lessonB, lessonC]);
    vi.mocked(startStudyJob).mockImplementation(async (itemId, _outputLanguage, section) => {
      const requestedSection = section ?? "all";
      return {
        job_id: `${itemId}-${requestedSection}`,
        item_id: itemId,
        status: "running",
        progress: 12,
        phase: requestedSection,
        message: "正在生成学习地图",
        error: null,
      };
    });
    vi.mocked(getStudyJob).mockImplementation(async (jobId) => ({
      job_id: jobId,
      item_id: jobId.split("-").slice(0, 2).join("-"),
      status: "succeeded",
      progress: 100,
      phase: "complete",
      message: "学习材料已生成",
      error: null,
    }));

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "大纲" }));
    fireEvent.click(await screen.findByRole("button", { name: "重新生成大纲" }));
    await waitFor(() => expect(startStudyJob).toHaveBeenCalledTimes(1));

    fireEvent.click(getLibraryCourseButtons("Lesson B")[0]);
    fireEvent.click(await screen.findByRole("button", { name: "展开学习地图设置" }));
    fireEvent.click(await screen.findByRole("button", { name: "全部重新生成" }));

    fireEvent.click(getLibraryCourseButtons("Lesson C")[0]);
    fireEvent.click(await screen.findByRole("button", { name: "详解" }));
    fireEvent.click(await screen.findByRole("button", { name: "重新生成详解" }));

    await waitFor(() => expect(startStudyJob).toHaveBeenCalledTimes(3), { timeout: 4200 });
    expect(startStudyJob).toHaveBeenNthCalledWith(1, "lesson-a", "zh-CN", "outline", "standard");
    expect(startStudyJob).toHaveBeenNthCalledWith(2, "lesson-b", "zh-CN", "all", "standard");
    expect(startStudyJob).toHaveBeenNthCalledWith(3, "lesson-c", "zh-CN", "high", "standard");
    await waitFor(() => expect(getStudyJob).toHaveBeenCalledTimes(3), { timeout: 4500 });
    await waitFor(() => expect(screen.queryByLabelText("学习地图生成队列")).toBeNull(), { timeout: 3500 });
    expect(screen.getByRole("heading", { name: "Lesson C" })).toBeTruthy();
  }, 8000);

  it("shows the study map generation queue only when tasks are waiting", async () => {
    vi.mocked(listItems).mockReset();
    vi.mocked(startStudyJob).mockReset();
    vi.mocked(getStudyJob).mockReset();
    const lessonA = studyQueueCourse("lesson-a", "Lesson A");
    const lessonB = studyQueueCourse("lesson-b", "Lesson B");
    const lessonC = studyQueueCourse("lesson-c", "Lesson C");
    vi.mocked(listItems).mockResolvedValue([lessonA, lessonB, lessonC]);
    vi.mocked(startStudyJob).mockImplementation(async (itemId, _outputLanguage, section) => {
      const requestedSection = section ?? "all";
      return {
        job_id: `${itemId}-${requestedSection}`,
        item_id: itemId,
        status: "running",
        progress: 12,
        phase: requestedSection,
        message: "正在生成学习地图",
        error: null,
      };
    });
    const lessonAResolver: { current?: (status: StudyJobStatus) => void } = {};
    vi.mocked(getStudyJob).mockImplementation(
      () =>
        new Promise<StudyJobStatus>((resolve) => {
          lessonAResolver.current = resolve;
        }),
    );

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "大纲" }));
    fireEvent.click(await screen.findByRole("button", { name: "重新生成大纲" }));
    await waitFor(() => expect(startStudyJob).toHaveBeenCalledTimes(1));
    expect(document.querySelector(".study-queue-drawer")).toBeNull();

    fireEvent.click(getLibraryCourseButtons("Lesson B")[0]);
    fireEvent.click(await screen.findByRole("button", { name: "展开学习地图设置" }));
    fireEvent.click(await screen.findByRole("button", { name: "全部重新生成" }));

    fireEvent.click(getLibraryCourseButtons("Lesson C")[0]);
    fireEvent.click(await screen.findByRole("button", { name: "详解" }));
    fireEvent.click(await screen.findByRole("button", { name: "重新生成详解" }));

    const queueButton = await screen.findByRole("button", { name: "学习地图生成队列 2" });
    fireEvent.click(queueButton);
    const drawer = queueButton.closest(".study-queue-drawer") as HTMLElement;
    expect(within(drawer).queryByText("Lesson A")).toBeNull();
    expect(within(drawer).getByText("Lesson B")).toBeTruthy();
    expect(within(drawer).getByText("Lesson C")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "学习地图生成队列 3" })).toBeNull();

    fireEvent.click(within(drawer).getByRole("button", { name: "取消排队任务 Lesson B 全部重新生成" }));
    fireEvent.click(within(drawer).getByRole("button", { name: "取消排队任务 Lesson C 重新生成详解" }));
    await waitFor(() => expect(getStudyJob).toHaveBeenCalledTimes(1), { timeout: 3500 });
    const resolveLessonA = lessonAResolver.current;
    if (!resolveLessonA) {
      throw new Error("Lesson A resolver was not registered.");
    }
    resolveLessonA({
      job_id: "lesson-a-outline",
      item_id: "lesson-a",
      status: "succeeded",
      progress: 100,
      phase: "complete",
      message: "学习材料已生成",
      error: null,
    });
    await waitFor(() => expect(document.querySelector(".study-queue-drawer")).toBeNull(), { timeout: 3500 });
  }, 8000);

  it("cancels queued study rebuild tasks without stopping later queued work", async () => {
    vi.mocked(listItems).mockReset();
    vi.mocked(startStudyJob).mockReset();
    vi.mocked(getStudyJob).mockReset();
    const lessonA = studyQueueCourse("lesson-a", "Lesson A");
    const lessonB = studyQueueCourse("lesson-b", "Lesson B");
    const lessonC = studyQueueCourse("lesson-c", "Lesson C");
    vi.mocked(listItems).mockResolvedValue([lessonA, lessonB, lessonC]);
    vi.mocked(startStudyJob).mockImplementation(async (itemId, _outputLanguage, section) => {
      const requestedSection = section ?? "all";
      return {
        job_id: `${itemId}-${requestedSection}`,
        item_id: itemId,
        status: "running",
        progress: 12,
        phase: requestedSection,
        message: "正在生成学习地图",
        error: null,
      };
    });
    const lessonAResolver: { current?: (status: StudyJobStatus) => void } = {};
    vi.mocked(getStudyJob).mockImplementation((jobId) => {
      if (jobId === "lesson-a-outline") {
        return new Promise<StudyJobStatus>((resolve) => {
          lessonAResolver.current = resolve;
        });
      }
      return Promise.resolve({
        job_id: jobId,
        item_id: "lesson-c",
        status: "succeeded",
        progress: 100,
        phase: "complete",
        message: "学习材料已生成",
        error: null,
      });
    });

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "大纲" }));
    fireEvent.click(await screen.findByRole("button", { name: "重新生成大纲" }));
    await waitFor(() => expect(startStudyJob).toHaveBeenCalledTimes(1));

    fireEvent.click(getLibraryCourseButtons("Lesson B")[0]);
    fireEvent.click(await screen.findByRole("button", { name: "展开学习地图设置" }));
    fireEvent.click(await screen.findByRole("button", { name: "全部重新生成" }));

    fireEvent.click(getLibraryCourseButtons("Lesson C")[0]);
    fireEvent.click(await screen.findByRole("button", { name: "详解" }));
    fireEvent.click(await screen.findByRole("button", { name: "重新生成详解" }));

    const queueButton = await screen.findByRole("button", { name: "学习地图生成队列 2" });
    fireEvent.click(queueButton);
    const drawer = queueButton.closest(".study-queue-drawer") as HTMLElement;

    expect(within(drawer).queryByText("Lesson A")).toBeNull();
    fireEvent.click(within(drawer).getByRole("button", { name: "取消排队任务 Lesson B 全部重新生成" }));

    expect(within(drawer).queryByText("Lesson B")).toBeNull();
    expect(within(drawer).getByText("Lesson C")).toBeTruthy();

    await waitFor(() => expect(getStudyJob).toHaveBeenCalledWith("lesson-a-outline"), { timeout: 3500 });
    const resolveLessonA = lessonAResolver.current;
    if (!resolveLessonA) {
      throw new Error("Lesson A resolver was not registered.");
    }
    resolveLessonA({
      job_id: "lesson-a-outline",
      item_id: "lesson-a",
      status: "succeeded",
      progress: 100,
      phase: "complete",
      message: "学习材料已生成",
      error: null,
    });

    await waitFor(() => expect(startStudyJob).toHaveBeenCalledTimes(2), { timeout: 3500 });
    expect(startStudyJob).toHaveBeenNthCalledWith(2, "lesson-c", "zh-CN", "high", "standard");
    expect(startStudyJob).not.toHaveBeenCalledWith("lesson-b", expect.anything(), expect.anything(), expect.anything());
  }, 8000);

  it("keeps later study rebuild tasks moving after a failure and lets the failed task be retried", async () => {
    vi.mocked(listItems).mockReset();
    vi.mocked(startStudyJob).mockReset();
    vi.mocked(getStudyJob).mockReset();
    const lessonA = studyQueueCourse("lesson-a", "Lesson A");
    const lessonB = studyQueueCourse("lesson-b", "Lesson B");
    vi.mocked(listItems).mockResolvedValue([lessonA, lessonB]);
    let studyStartCall = 0;
    vi.mocked(startStudyJob).mockImplementation(async (itemId, _outputLanguage, section) => {
      studyStartCall += 1;
      const requestedSection = section ?? "all";
      return {
        job_id: `${itemId}-${requestedSection}-${studyStartCall}`,
        item_id: itemId,
        status: "running",
        progress: 12,
        phase: requestedSection,
        message: "正在生成学习地图",
        error: null,
      };
    });
    vi.mocked(getStudyJob).mockImplementation(async (jobId) => {
      if (jobId === "lesson-a-all-1") {
        return {
          job_id: jobId,
          item_id: "lesson-a",
          status: "failed",
          progress: 100,
          phase: "failed",
          message: "学习材料生成失败",
          error: "详解退化成逐句字幕列表",
        };
      }
      return {
        job_id: jobId,
        item_id: jobId.startsWith("lesson-a-") ? "lesson-a" : "lesson-b",
        status: "succeeded",
        progress: 100,
        phase: "complete",
        message: "学习材料已生成",
        error: null,
      };
    });

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "展开学习地图设置" }));
    fireEvent.click(await screen.findByRole("button", { name: "全部重新生成" }));
    await waitFor(() => expect(startStudyJob).toHaveBeenCalledTimes(1));

    fireEvent.click(getLibraryCourseButtons("Lesson B")[0]);
    fireEvent.click(await screen.findByRole("button", { name: "全部重新生成" }));

    await waitFor(() => expect(startStudyJob).toHaveBeenCalledTimes(2), { timeout: 3600 });
    const queueButton = await screen.findByRole("button", { name: "学习地图生成队列" });
    expect(queueButton.closest(".right-rail")).toBeNull();
    expect(queueButton.closest(".study-queue-drawer")).toBeTruthy();
    expect(screen.queryByText(/详解退化成逐句字幕列表/)).toBeNull();

    fireEvent.click(queueButton);
    const rightRail = document.querySelector(".right-rail") as HTMLElement;
    expect(within(rightRail).queryByLabelText("学习地图生成队列")).toBeNull();
    expect((await screen.findAllByText(/学习地图任务失败/)).length).toBeGreaterThan(0);
    expect(screen.getByText(/详解退化成逐句字幕列表/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "重试失败任务 Lesson A 全部重新生成" }));

    await waitFor(() => expect(startStudyJob).toHaveBeenCalledTimes(3), { timeout: 3500 });
    expect(startStudyJob).toHaveBeenNthCalledWith(3, "lesson-a", "zh-CN", "all", "standard");
    await waitFor(() => expect(getStudyJob).toHaveBeenCalledTimes(3), { timeout: 4500 });
  }, 8000);

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

  it("creates and deletes categories from the single library create menu", async () => {
    const promptSpy = vi.spyOn(window, "prompt").mockReturnValue("摄影");
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<App />);

    await waitFor(() => expect(screen.getByText("课程库")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "新建" }));
    expect(screen.getByRole("button", { name: "新建专辑" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "新建分类" }));

    expect(screen.getByRole("button", { name: "收起分类 摄影" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "删除分类 摄影" })).toBeTruthy();
    const emptyCategory = screen.getByText("还没有专辑");
    expect(emptyCategory.className).toContain("library-category-empty");
    expect(emptyCategory.className).toContain("library-node-empty");
    expect(screen.queryByText(/上层专辑/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "删除分类 摄影" }));
    expect(confirmSpy).toHaveBeenCalled();
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "收起分类 摄影" })).toBeNull();
    });

    promptSpy.mockRestore();
    confirmSpy.mockRestore();
  });

  it("uses one compact empty state style for empty collections and categories", async () => {
    const promptSpy = vi.spyOn(window, "prompt")
      .mockReturnValueOnce("空专辑")
      .mockReturnValueOnce("空分类");

    render(<App />);

    await waitFor(() => expect(screen.getByText("课程库")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "新建" }));
    fireEvent.click(screen.getByRole("button", { name: "新建专辑" }));
    fireEvent.click(screen.getByRole("button", { name: "新建" }));
    fireEvent.click(screen.getByRole("button", { name: "新建分类" }));

    expect(screen.getByText("暂无课程").className).toContain("library-node-empty");
    expect(screen.getByText("还没有专辑").className).toContain("library-node-empty");

    promptSpy.mockRestore();
  });

  it("creates a category from the collection editor and assigns the collection to it", async () => {
    const first = {
      id: "photo-lesson-1",
      source_url: "https://example.com/photo-lesson-1",
      title: "Photo Lesson One",
      duration: 60,
      created_at: new Date().toISOString(),
      transcript: [],
      metadata: null,
      study: null,
      local_video_path: null,
      collection_title: "当代经典摄影20讲",
      course_index: 1,
      sort_order: 1,
    };
    const second = {
      ...first,
      id: "photo-lesson-2",
      source_url: "https://example.com/photo-lesson-2",
      title: "Photo Lesson Two",
      collection_title: "摄影审美课",
      course_index: 1,
      sort_order: 1,
    };
    vi.mocked(listItems).mockResolvedValueOnce([first, second]);
    vi.mocked(updateCourseItem).mockImplementation(async (itemId, input) => ({
      ...(itemId === "photo-lesson-1" ? first : second),
      collection_group_title: input.collection_group_title ?? "",
      collection_title: input.collection_title ?? "",
      course_index: input.course_index ?? null,
      sort_order: input.sort_order ?? null,
    }));
    const promptSpy = vi.spyOn(window, "prompt").mockReturnValue("摄影");

    render(<App />);

    await waitFor(() => expect(screen.getByText("当代经典摄影20讲")).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: "编辑专辑 当代经典摄影20讲" }));
    const categorySelect = screen.getByLabelText("分类") as HTMLSelectElement;
    const createCategoryOption = screen.getByRole("option", { name: "新建分类" }) as HTMLOptionElement;
    fireEvent.change(categorySelect, { target: { value: createCategoryOption.value } });
    expect(categorySelect.value).toBe("摄影");
    fireEvent.submit((screen.getByLabelText("专辑名称") as HTMLInputElement).closest("form") as HTMLFormElement);

    await waitFor(() => {
      expect(updateCourseItem).toHaveBeenCalledWith(
        "photo-lesson-1",
        expect.objectContaining({
          collection_group_title: "摄影",
          collection_title: "当代经典摄影20讲",
        }),
      );
    });
    const category = screen.getByRole("button", { name: "收起分类 摄影" }).closest(".library-collection-group");
    expect(category).toBeTruthy();
    expect(within(category as HTMLElement).getByText("当代经典摄影20讲")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "收起分类 摄影" }));
    expect(screen.queryByRole("button", { name: "收起专辑 当代经典摄影20讲" })).toBeNull();
    expect(screen.queryByText(/上层专辑/)).toBeNull();

    promptSpy.mockRestore();
  });

  it("keeps categories together and lets category rows move", async () => {
    const product = {
      id: "product-lesson",
      source_url: "https://example.com/product",
      title: "Product Lesson",
      duration: 60,
      created_at: new Date().toISOString(),
      transcript: [],
      metadata: null,
      study: null,
      local_video_path: null,
      collection_group_title: "产品",
      collection_title: "三节课 产品经理",
      course_index: 1,
      sort_order: 1,
    };
    const productSibling = {
      ...product,
      id: "product-lesson-2",
      source_url: "https://example.com/product-2",
      title: "Product Lesson Two",
      course_index: 2,
      sort_order: 2,
    };
    const photo = {
      ...product,
      id: "photo-lesson",
      source_url: "https://example.com/photo",
      title: "Photo Lesson",
      collection_group_title: "摄影",
      collection_title: "当代经典摄影20讲",
    };
    const ungrouped = {
      ...product,
      id: "ai-lesson",
      source_url: "https://example.com/ai",
      title: "AI Lesson",
      collection_group_title: "",
      collection_title: "AI Prompting",
    };
    vi.mocked(listItems).mockResolvedValueOnce([product, productSibling, photo, ungrouped]);

    render(<App />);

    await waitFor(() => expect(screen.getByRole("button", { name: "收起分类 产品" })).toBeTruthy());
    const productCategory = screen.getByRole("button", { name: "收起分类 产品" }).closest(".library-collection-group") as HTMLElement;
    expect(productCategory.querySelector(".library-collection-group-actions")).toBeTruthy();
    const productCount = productCategory.querySelector(".library-collection-group-count");
    expect(productCount).toBeTruthy();
    expect(productCount?.textContent).toBe("1");
    expect(getTopLevelLibraryEntryNames().slice(0, 3)).toEqual(["产品", "摄影", "AI Prompting"]);

    fireEvent.click(screen.getByRole("button", { name: "下移分类 产品" }));

    expect(getTopLevelLibraryEntryNames().slice(0, 3)).toEqual(["摄影", "产品", "AI Prompting"]);
  });

  it("moves collections only within their current category", async () => {
    const productA = {
      id: "product-a",
      source_url: "https://example.com/product-a",
      title: "Product A Lesson",
      duration: 60,
      created_at: new Date().toISOString(),
      transcript: [],
      metadata: null,
      study: null,
      local_video_path: null,
      collection_group_title: "产品",
      collection_title: "产品入门 A",
      course_index: 1,
      sort_order: 1,
    };
    const productB = {
      ...productA,
      id: "product-b",
      source_url: "https://example.com/product-b",
      title: "Product B Lesson",
      collection_title: "产品入门 B",
    };
    const photo = {
      ...productA,
      id: "photo-a",
      source_url: "https://example.com/photo-a",
      title: "Photo Lesson",
      collection_group_title: "摄影",
      collection_title: "摄影入门",
    };
    vi.mocked(listItems).mockResolvedValueOnce([productA, productB, photo]);

    render(<App />);

    await waitFor(() => expect(screen.getByRole("button", { name: "收起分类 产品" })).toBeTruthy());
    const productCategory = screen.getByRole("button", { name: "收起分类 产品" }).closest(".library-collection-group") as HTMLElement;
    expect(getCollectionNamesInCategory(productCategory)).toEqual(["产品入门 A", "产品入门 B"]);
    expect(within(productCategory).queryByRole("button", { name: "下移专辑 产品入门 B" })).toBeNull();

    fireEvent.click(within(productCategory).getByRole("button", { name: "下移专辑 产品入门 A" }));

    expect(getCollectionNamesInCategory(productCategory)).toEqual(["产品入门 B", "产品入门 A"]);
    expect(getTopLevelLibraryEntryNames().slice(0, 2)).toEqual(["产品", "摄影"]);
  });

  it("loads collection categories from persisted library state", async () => {
    const photo = {
      id: "photo-lesson",
      source_url: "https://example.com/photo",
      title: "Photo Lesson",
      duration: 60,
      created_at: new Date().toISOString(),
      transcript: [],
      metadata: null,
      study: null,
      local_video_path: null,
      collection_group_title: "",
      collection_title: "当代经典摄影20讲",
      course_index: 1,
      sort_order: 1,
    };
    vi.mocked(getLibraryState).mockResolvedValueOnce({
      manual_collections: [],
      manual_collection_groups: ["摄影"],
      collection_order: [],
      collection_group_order: ["collection-group:摄影"],
      collection_group_assignments: {
        "collection:当代经典摄影20讲": "摄影",
      },
    });
    vi.mocked(listItems).mockResolvedValueOnce([photo]);

    render(<App />);

    await waitFor(() => expect(screen.getByRole("button", { name: "收起分类 摄影" })).toBeTruthy());
    const photoCategory = screen.getByRole("button", { name: "收起分类 摄影" }).closest(".library-collection-group") as HTMLElement;
    expect(getCollectionNamesInCategory(photoCategory)).toEqual(["当代经典摄影20讲"]);
  });

  it("migrates legacy local category state to the backend when remote state is empty", async () => {
    window.localStorage.setItem("course-navigator-manual-collection-groups", JSON.stringify(["摄影"]));
    window.localStorage.setItem(
      "course-navigator-collection-group-assignments",
      JSON.stringify({ "collection:当代经典摄影20讲": "摄影" }),
    );
    const photo = {
      id: "photo-lesson",
      source_url: "https://example.com/photo",
      title: "Photo Lesson",
      duration: 60,
      created_at: new Date().toISOString(),
      transcript: [],
      metadata: null,
      study: null,
      local_video_path: null,
      collection_group_title: "",
      collection_title: "当代经典摄影20讲",
      course_index: 1,
      sort_order: 1,
    };
    vi.mocked(listItems).mockResolvedValueOnce([photo]);

    render(<App />);

    await waitFor(() => {
      expect(saveLibraryState).toHaveBeenCalledWith(
        expect.objectContaining({
          manual_collection_groups: ["摄影"],
          collection_group_assignments: { "collection:当代经典摄影20讲": "摄影" },
        }),
      );
    });
    expect(screen.getByRole("button", { name: "收起分类 摄影" })).toBeTruthy();
  });

  it("serializes library state saves so a stale request cannot overwrite the latest category state", async () => {
    let resolveFirstSave: ((value: LibraryState | PromiseLike<LibraryState>) => void) | null = null;
    vi.mocked(saveLibraryState).mockImplementationOnce(
      (state) => new Promise((resolve) => {
        resolveFirstSave = resolve;
      }),
    );
    vi.mocked(saveLibraryState).mockImplementation(async (state) => state);
    const promptSpy = vi
      .spyOn(window, "prompt")
      .mockReturnValueOnce("产品")
      .mockReturnValueOnce("摄影");

    render(<App />);

    await waitFor(() => expect(saveLibraryState).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "新建" }));
    fireEvent.click(screen.getByRole("button", { name: "新建分类" }));
    fireEvent.click(screen.getByRole("button", { name: "新建" }));
    fireEvent.click(screen.getByRole("button", { name: "新建分类" }));

    expect(screen.getByRole("button", { name: "收起分类 产品" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "收起分类 摄影" })).toBeTruthy();
    expect(saveLibraryState).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveFirstSave?.({
        manual_collections: [],
        manual_collection_groups: [],
        collection_order: [],
        collection_group_order: [],
        collection_group_assignments: {},
      });
    });

    await waitFor(() => expect(saveLibraryState).toHaveBeenCalledTimes(2));
    expect(saveLibraryState).toHaveBeenLastCalledWith(
      expect.objectContaining({
        manual_collection_groups: ["产品", "摄影"],
        collection_group_order: ["collection-group:产品", "collection-group:摄影"],
      }),
    );

    promptSpy.mockRestore();
  });

  it("creates a collection from the course editor and assigns the course to it", async () => {
    const item = {
      id: "single-lesson",
      source_url: "https://example.com/single-lesson",
      title: "Single Lesson",
      duration: 60,
      created_at: new Date().toISOString(),
      transcript: [],
      metadata: null,
      study: null,
      local_video_path: null,
      collection_title: "",
      course_index: null,
      sort_order: null,
    };
    vi.mocked(listItems).mockResolvedValueOnce([item]);
    vi.mocked(updateCourseItem).mockImplementation(async (_itemId, input) => ({
      ...item,
      title: input.title ?? item.title,
      translated_title: input.translated_title ?? null,
      collection_title: input.collection_title ?? "",
      course_index: input.course_index ?? null,
      sort_order: input.sort_order ?? null,
    }));
    const promptSpy = vi.spyOn(window, "prompt").mockReturnValue("新专辑");

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "编辑标题 Single Lesson" }));
    const collectionSelect = screen.getByLabelText("所属专辑") as HTMLSelectElement;
    const createCollectionOption = screen.getByRole("option", { name: "新建专辑" }) as HTMLOptionElement;
    fireEvent.change(collectionSelect, { target: { value: createCollectionOption.value } });
    expect(collectionSelect.value).toBe("新专辑");
    fireEvent.submit((screen.getByLabelText("课程标题") as HTMLInputElement).closest("form") as HTMLFormElement);

    await waitFor(() => {
      expect(updateCourseItem).toHaveBeenCalledWith(
        "single-lesson",
        expect.objectContaining({
          collection_title: "新专辑",
        }),
      );
    });

    promptSpy.mockRestore();
  });

  it("deletes a collection without deleting its courses", async () => {
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
      collection_title: input.collection_title ?? "",
      course_index: input.course_index ?? null,
      sort_order: input.sort_order ?? null,
    }));
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<App />);

    await waitFor(() => expect(getLibraryCourseButtons("Lesson One").length).toBeGreaterThan(0));
    fireEvent.click(screen.getByRole("button", { name: "删除专辑 AI Prompting" }));

    await waitFor(() => {
      expect(updateCourseItem).toHaveBeenCalledWith(
        "lesson-1",
        expect.objectContaining({ collection_title: null, course_index: null, sort_order: null }),
      );
      expect(updateCourseItem).toHaveBeenCalledWith(
        "lesson-2",
        expect.objectContaining({ collection_title: null, course_index: null, sort_order: null }),
      );
    });
    expect(screen.queryByText("AI Prompting")).toBeNull();
    expect(getLibraryCourseButtons("Lesson One").length).toBeGreaterThan(0);
    expect(getLibraryCourseButtons("Lesson Two").length).toBeGreaterThan(0);
    confirmSpy.mockRestore();
  });

  it("opens the course package export dialog with collections collapsed by default", async () => {
    vi.mocked(listItems).mockResolvedValueOnce([
      {
        id: "lesson-1",
        source_url: "https://example.com/lesson-1",
        title: "Lesson One",
        duration: 60,
        created_at: new Date().toISOString(),
        transcript: [{ start: 0, end: 2, text: "Opening." }],
        metadata: null,
        study: null,
        local_video_path: null,
        collection_title: "AI Prompting",
        course_index: 1,
        sort_order: 1,
      },
      {
        id: "lesson-2",
        source_url: "https://example.com/lesson-2",
        title: "Lesson Two",
        duration: 60,
        created_at: new Date().toISOString(),
        transcript: [{ start: 0, end: 2, text: "Opening." }],
        metadata: null,
        study: null,
        local_video_path: null,
        collection_title: "AI Prompting",
        course_index: 2,
        sort_order: 2,
      },
    ]);

    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "导出课程" }));
    const dialog = await screen.findByRole("dialog", { name: "导出课程包" });
    const modal = within(dialog);

    expect(modal.getByText("AI Prompting")).toBeTruthy();
    expect(modal.queryByText("1. Lesson One")).toBeNull();

    fireEvent.click(modal.getByRole("button", { name: "展开导出专辑 AI Prompting" }));
    expect(modal.getByText("1. Lesson One")).toBeTruthy();
    expect(modal.getByText("2. Lesson Two")).toBeTruthy();

    fireEvent.click(modal.getByRole("button", { name: "收起导出专辑 AI Prompting" }));
    expect(modal.queryByText("1. Lesson One")).toBeNull();
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
  const existingLocalStorage = window.localStorage;
  if (
    existingLocalStorage &&
    typeof existingLocalStorage.getItem === "function" &&
    typeof existingLocalStorage.setItem === "function" &&
    typeof existingLocalStorage.removeItem === "function"
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

function readBlobText(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(blob);
  });
}

function getLibraryCourseButtons(title: string): HTMLElement[] {
  return screen
    .queryAllByText(title)
    .map((node) => node.closest("button.library-item"))
    .filter((button): button is HTMLElement => button instanceof HTMLElement);
}

function getTopLevelLibraryEntryNames(): string[] {
  const list = document.querySelector(".library-list");
  return Array.from(list?.children ?? []).flatMap((child) => {
    if (!(child instanceof HTMLElement)) return [];
    if (child.classList.contains("library-collection-group")) {
      const label = child.querySelector(".library-collection-group-toggle span:last-child")?.textContent?.trim();
      return label ? [label] : [];
    }
    if (child.classList.contains("library-collection")) {
      const label = child.querySelector(".library-collection-toggle span:last-child")?.textContent?.trim();
      return label ? [label] : [];
    }
    return [];
  });
}

function getCollectionNamesInCategory(category: HTMLElement): string[] {
  const body = category.querySelector(".library-collection-group-body");
  return Array.from(body?.children ?? []).flatMap((child) => {
    if (!(child instanceof HTMLElement) || !child.classList.contains("library-collection")) return [];
    const label = child.querySelector(".library-collection-toggle span:last-child")?.textContent?.trim();
    return label ? [label] : [];
  });
}

function studyQueueCourse(id: string, title: string): CourseItem {
  return {
    id,
    source_url: `https://example.com/${id}`,
    title,
    duration: 60,
    created_at: new Date().toISOString(),
    transcript: [{ start: 0, end: 5, text: `${title} opening.` }],
    metadata: null,
    study: {
      one_line: `${title} guide.`,
      translated_title: null,
      context_summary: `${title} context.`,
      time_map: [{ start: 0, end: 5, title: `${title} block`, summary: `${title} summary.`, priority: "focus" }],
      outline: [
        {
          id: `${id}-outline`,
          start: 0,
          end: 5,
          title: `${title} outline`,
          summary: `${title} outline summary.`,
          children: [],
        },
      ],
      detailed_notes: `${title} interpretation.`,
      high_fidelity_text: `${title} detailed.`,
      translated_transcript: [],
      prerequisites: [],
      thought_prompts: [],
      review_suggestions: [],
    },
    local_video_path: null,
  };
}
