import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

const apiMocks = vi.hoisted(() => ({
  saveConfig: vi.fn(async (config) => config),
  saveModelConfig: vi.fn(async (input) => ({
    profiles: input.profiles.map((profile: any) => ({
      ...profile,
      hasApiKey: Boolean(profile.apiKey),
      apiKeyPreview: profile.apiKey ? "sk-t********test" : null,
    })),
    translationModelId: input.translationModelId,
    learningModelId: input.learningModelId,
    globalModelId: input.globalModelId,
    asrModelId: input.asrModelId,
    studyDetailLevel: input.studyDetailLevel,
    taskParameters: input.taskParameters,
    onlineAsr: {
      provider: input.onlineAsr.provider,
      openai: { baseUrl: "https://api.openai.com/v1", model: "whisper-1", hasApiKey: Boolean(input.onlineAsr.openai.apiKey), apiKeyPreview: null },
      groq: { baseUrl: "https://api.groq.com/openai/v1", model: "whisper-large-v3-turbo", hasApiKey: false, apiKeyPreview: null },
      xai: { baseUrl: "https://api.x.ai/v1", model: input.onlineAsr.xai.model ?? "grok-2-voice-1212", hasApiKey: false, apiKeyPreview: null },
      custom: { baseUrl: input.onlineAsr.custom.baseUrl, model: input.onlineAsr.custom.model, hasApiKey: false, apiKeyPreview: null },
    },
  })),
  chooseWorkspaceDirectory: vi.fn(async () => "/Volumes/Learning/Course Workspace"),
  planWorkspaceMigration: vi.fn(async (source: string, target: string) => ({
    source,
    target,
    requiresMigration: true,
    message: "将迁移现有 Workspace 数据",
  })),
  setWorkspaceDirectory: vi.fn(async (_target: string) => ({
    projectRoot: "/tmp/course-navigator",
    apiHost: "127.0.0.1",
    apiPort: 8000,
    webHost: "127.0.0.1",
    webPort: 5173,
    workspaceDir: "/Volumes/Learning/Course Workspace",
    openBrowserOnStart: true,
  })),
}));

vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn(async () => () => undefined),
}));

vi.mock("./api", () => ({
  getConfig: async () => ({
    projectRoot: "/tmp/course-navigator",
    apiHost: "127.0.0.1",
    apiPort: 8000,
    webHost: "127.0.0.1",
    webPort: 5173,
    workspaceDir: "/tmp/course-navigator/course-navigator-workspace",
    openBrowserOnStart: true,
  }),
  getStatus: async () => ({
    state: "stopped",
    apiUrl: "http://127.0.0.1:8000",
    webUrl: "http://127.0.0.1:5173",
    message: "尚未启动",
  }),
  checkDependencies: async () => [
    {
      name: "uv",
      available: true,
      purpose: "安装和启动 Python 后端",
    },
  ],
  getModelConfig: async () => ({
    profiles: [
      {
        id: "default",
        name: "DeepSeek V3.2",
        providerType: "openai",
        baseUrl: "https://api.example.com/v1",
        model: "deepseek-ai/DeepSeek-V3.2",
        contextWindow: null,
        maxTokens: null,
        hasApiKey: true,
        apiKeyPreview: "sk-t********test",
      },
      {
        id: "fast",
        name: "Fast Model",
        providerType: "openai",
        baseUrl: "https://api.example.com/v1",
        model: "fast-model",
        contextWindow: null,
        maxTokens: null,
        hasApiKey: true,
        apiKeyPreview: "sk-f********test",
      },
    ],
    translationModelId: "default",
    learningModelId: "default",
    globalModelId: "default",
    asrModelId: "default",
    studyDetailLevel: "faithful",
    taskParameters: {},
    onlineAsr: {
      provider: "openai",
      openai: { baseUrl: "https://api.openai.com/v1", model: "whisper-1", hasApiKey: true, apiKeyPreview: "sk-o********test" },
      groq: { baseUrl: "https://api.groq.com/openai/v1", model: "whisper-large-v3-turbo", hasApiKey: false, apiKeyPreview: null },
      xai: { baseUrl: "https://api.x.ai/v1", model: "grok-2-voice-1212", hasApiKey: false, apiKeyPreview: null },
      custom: { baseUrl: null, model: null, hasApiKey: false, apiKeyPreview: null },
    },
  }),
  saveModelConfig: apiMocks.saveModelConfig,
  startServices: async () => ({
    state: "starting",
    apiUrl: "http://127.0.0.1:8000",
    webUrl: "http://127.0.0.1:5173",
    message: "启动命令已准备，进程管理将在下一步启用",
  }),
  stopServices: async () => ({
    state: "stopped",
    apiUrl: "http://127.0.0.1:8000",
    webUrl: "http://127.0.0.1:5173",
    message: "服务已停止",
  }),
  saveConfig: apiMocks.saveConfig,
  chooseWorkspaceDirectory: apiMocks.chooseWorkspaceDirectory,
  showMainPanel: async () => undefined,
  openWebPage: async () => undefined,
  planWorkspaceMigration: apiMocks.planWorkspaceMigration,
  setWorkspaceDirectory: apiMocks.setWorkspaceDirectory,
}));

describe("App", () => {
  beforeEach(() => {
    window.history.pushState({}, "", "/");
    apiMocks.saveConfig.mockClear();
    apiMocks.saveModelConfig.mockClear();
    apiMocks.chooseWorkspaceDirectory.mockClear();
    apiMocks.planWorkspaceMigration.mockClear();
    apiMocks.setWorkspaceDirectory.mockClear();
  });

  it("renders launcher status and configured paths", async () => {
    render(<App />);

    expect(await screen.findByText("stopped")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "视频学习工作台" })).toBeTruthy();
    expect(screen.getByText("/tmp/course-navigator")).toBeTruthy();
    expect(screen.getByText("/tmp/course-navigator/course-navigator-workspace")).toBeTruthy();
    expect(screen.getByText("工作区")).toBeTruthy();
    expect(screen.getByRole("region", { name: "路径配置" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "端口配置" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "模型配置" })).toBeTruthy();
    expect(await screen.findByLabelText("字幕模型")).toBeTruthy();
    expect(screen.getByLabelText("在线 ASR 模型")).toBeTruthy();
    expect(screen.getByText("uv")).toBeTruthy();
    expect(screen.queryByText("Workspace 迁移")).toBeNull();
    expect(screen.queryByText("缓存视频仍属于 Workspace；迁移前会先做路径检查，旧 Workspace 默认保留。")).toBeNull();
    expect(screen.queryByLabelText("状态消息")).toBeNull();
  });

  it("saves model role selections from the launcher panel", async () => {
    render(<App />);

    fireEvent.change(await screen.findByLabelText("字幕模型"), { target: { value: "fast" } });

    await waitFor(() => expect(apiMocks.saveModelConfig).toHaveBeenCalledTimes(1));
    expect(apiMocks.saveModelConfig).toHaveBeenCalledWith(
      expect.objectContaining({
        translationModelId: "fast",
        learningModelId: "default",
        globalModelId: "default",
        asrModelId: "default",
      }),
    );
  });

  it("opens model archive and adds a new LLM profile", async () => {
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "模型档案" }));
    expect(screen.getByRole("dialog", { name: "模型档案" })).toBeTruthy();
    expect((screen.getByLabelText("API Key") as HTMLInputElement).value).toBe("sk-t********test");
    fireEvent.click(screen.getByRole("button", { name: "新增档案" }));
    expect(screen.getByLabelText("模型").getAttribute("placeholder")).toBeNull();
    expect(screen.getByLabelText("API Key").getAttribute("placeholder")).toBeNull();
    fireEvent.change(screen.getByLabelText("接口格式"), { target: { value: "anthropic" } });
    expect(screen.getByLabelText("模型").getAttribute("placeholder")).toBeNull();
    fireEvent.change(screen.getByLabelText("接口格式"), { target: { value: "openai" } });
    fireEvent.change(screen.getByLabelText("档案名称"), { target: { value: "New Profile" } });
    fireEvent.change(screen.getByLabelText("接口地址"), { target: { value: "https://api.new.test/v1" } });
    fireEvent.change(screen.getByLabelText("模型"), { target: { value: "new/model" } });
    fireEvent.change(screen.getByLabelText("API Key"), { target: { value: "sk-new" } });
    fireEvent.click(screen.getByRole("button", { name: "保存档案" }));

    await waitFor(() => expect(apiMocks.saveModelConfig).toHaveBeenCalledTimes(1));
    expect(apiMocks.saveModelConfig.mock.calls[0][0].profiles).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          name: "New Profile",
          baseUrl: "https://api.new.test/v1",
          model: "new/model",
          apiKey: "sk-new",
        }),
      ]),
    );
  });

  it("edits only the selected online ASR provider in the archive", async () => {
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "模型档案" }));
    fireEvent.click(screen.getByRole("button", { name: "在线 ASR 档案" }));

    expect((screen.getByLabelText("在线 ASR API Key") as HTMLInputElement).value).toBe("sk-o********test");
    expect(screen.getByLabelText("在线 ASR API Key").getAttribute("placeholder")).toBeNull();
    expect(screen.queryByText("Groq Whisper Key")).toBeNull();
    fireEvent.change(screen.getByLabelText("正在配置"), { target: { value: "custom" } });
    expect(screen.getByLabelText("在线 ASR API Key").getAttribute("placeholder")).toBeNull();
    expect(screen.getByLabelText("自定义接口地址").getAttribute("placeholder")).toBe("https://api.example.com/v1/audio/transcriptions");
    expect(screen.getByLabelText("自定义模型名称").getAttribute("placeholder")).toBeNull();
    fireEvent.change(screen.getByLabelText("自定义接口地址"), {
      target: { value: "https://asr.example.com/v1/audio/transcriptions" },
    });
    fireEvent.change(screen.getByLabelText("自定义模型名称"), { target: { value: "whisper-large-v3" } });
    fireEvent.change(screen.getByLabelText("在线 ASR API Key"), { target: { value: "asr-secret" } });
    fireEvent.click(screen.getByRole("button", { name: "保存在线 ASR 档案" }));

    await waitFor(() => expect(apiMocks.saveModelConfig).toHaveBeenCalledTimes(1));
    expect(apiMocks.saveModelConfig.mock.calls[0][0].onlineAsr).toEqual(
      expect.objectContaining({
        provider: "openai",
        custom: expect.objectContaining({
          baseUrl: "https://asr.example.com/v1/audio/transcriptions",
          model: "whisper-large-v3",
          apiKey: "asr-secret",
        }),
      }),
    );
    expect(apiMocks.saveModelConfig.mock.calls[0][0].onlineAsr.openai).not.toHaveProperty("apiKey");
  });

  it("does not send masked API Key previews as new secrets", async () => {
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "模型档案" }));
    fireEvent.click(screen.getByRole("button", { name: "保存档案" }));

    await waitFor(() => expect(apiMocks.saveModelConfig).toHaveBeenCalledTimes(1));
    expect(apiMocks.saveModelConfig.mock.calls[0][0].profiles[0]).not.toHaveProperty("apiKey");
  });

  it("closes the model archive with Cancel without saving", async () => {
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "模型档案" }));
    fireEvent.click(screen.getByRole("button", { name: "取消" }));

    expect(screen.queryByRole("dialog", { name: "模型档案" })).toBeNull();
    expect(apiMocks.saveModelConfig).not.toHaveBeenCalled();
  });

  it("lets users edit web and API ports while services are stopped", async () => {
    render(<App />);

    const portPanel = await screen.findByRole("region", { name: "端口配置" });
    expect(within(portPanel).getByRole("button", { name: "修改端口" })).toBeTruthy();
    fireEvent.click(within(portPanel).getByRole("button", { name: "修改端口" }));
    fireEvent.change(screen.getByLabelText("网页端口"), { target: { value: "5188" } });
    fireEvent.change(screen.getByLabelText("API 端口"), { target: { value: "8100" } });
    fireEvent.click(screen.getByRole("button", { name: "保存端口" }));

    await waitFor(() => expect(apiMocks.saveConfig).toHaveBeenCalledTimes(1));
    expect(apiMocks.saveConfig).toHaveBeenCalledWith(
      expect.objectContaining({
        webPort: 5188,
        apiPort: 8100,
      }),
    );
  });

  it("opens a native directory picker before changing Workspace", async () => {
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "修改工作区" }));

    await waitFor(() => expect(apiMocks.chooseWorkspaceDirectory).toHaveBeenCalledTimes(1));
    expect(apiMocks.planWorkspaceMigration).toHaveBeenCalledWith(
      "/tmp/course-navigator/course-navigator-workspace",
      "/Volumes/Learning/Course Workspace",
    );
    expect(screen.getByRole("dialog", { name: "确认 Workspace 迁移" })).toBeTruthy();
    expect(apiMocks.setWorkspaceDirectory).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "迁移并切换" }));

    expect(apiMocks.setWorkspaceDirectory).toHaveBeenCalledWith("/Volumes/Learning/Course Workspace", true);
  });

  it("shows Workspace change errors instead of failing silently", async () => {
    apiMocks.planWorkspaceMigration.mockRejectedValueOnce("新 Workspace 位置和当前位置相同");
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "修改工作区" }));

    expect(await screen.findByText("Workspace 切换失败：新 Workspace 位置和当前位置相同")).toBeTruthy();
    expect(apiMocks.setWorkspaceDirectory).not.toHaveBeenCalled();
  });
});
