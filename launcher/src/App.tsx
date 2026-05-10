import {
  Activity,
  CheckCircle2,
  FolderOpen,
  KeyRound,
  MonitorUp,
  Play,
  Plus,
  Radio,
  Save,
  SlidersHorizontal,
  Square,
  X,
  XCircle,
} from "lucide-react";
import { listen } from "@tauri-apps/api/event";
import { useEffect, useState, type ReactNode } from "react";

import {
  checkDependencies,
  chooseWorkspaceDirectory,
  getConfig,
  getModelConfig,
  getStatus,
  planWorkspaceMigration,
  saveConfig,
  saveModelConfig,
  setWorkspaceDirectory,
  startServices,
  stopServices,
} from "./api";
import type {
  DependencyStatus,
  LauncherConfig,
  LauncherStatus,
  ModelConfig,
  ModelConfigInput,
  ModelProviderType,
  OnlineAsrProvider,
  WorkspaceMigrationPlan,
} from "./types";
import "./styles.css";

const fallbackStatus: LauncherStatus = {
  state: "stopped",
  apiUrl: "http://127.0.0.1:8000",
  webUrl: "http://127.0.0.1:5173",
  message: "尚未启动",
};

type ModelRoleField = "translationModelId" | "learningModelId" | "globalModelId" | "asrModelId";
type EditableOnlineAsrProvider = Exclude<OnlineAsrProvider, "none">;
type LlmProfileDraft = Omit<ModelConfig["profiles"][number], "hasApiKey"> & {
  apiKey: string;
};
type LlmArchiveDraft = {
  profiles: LlmProfileDraft[];
  activeProfileId: string;
};
type OnlineAsrDraft = {
  provider: OnlineAsrProvider;
  openaiApiKey: string;
  groqApiKey: string;
  xaiApiKey: string;
  xaiModel: string;
  customBaseUrl: string;
  customModel: string;
  customApiKey: string;
};

const MODEL_ROLE_OPTIONS: { field: ModelRoleField; label: string; hint: string }[] = [
  { field: "translationModelId", label: "字幕模型", hint: "字幕翻译和标题翻译" },
  { field: "learningModelId", label: "详解模型", hint: "解读、详解和高保真文本" },
  { field: "globalModelId", label: "结构模型", hint: "上下文、分块、导览和大纲" },
  { field: "asrModelId", label: "ASR 校正模型", hint: "ASR 字幕校正建议" },
];

const ONLINE_ASR_OPTIONS: { value: OnlineAsrProvider; label: string }[] = [
  { value: "none", label: "不启用在线 ASR" },
  { value: "openai", label: "OpenAI Whisper" },
  { value: "groq", label: "Groq Whisper" },
  { value: "xai", label: "xAI Voice" },
  { value: "custom", label: "自定义在线 ASR" },
];

function isServiceBusy(state: LauncherStatus["state"]) {
  return state === "running" || state === "starting" || state === "stopping";
}

function getErrorMessage(error: unknown) {
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  return "未知错误";
}

export function App() {
  const [config, setConfig] = useState<LauncherConfig | null>(null);
  const [status, setStatus] = useState<LauncherStatus>(fallbackStatus);
  const [dependencies, setDependencies] = useState<DependencyStatus[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [modelConfig, setModelConfig] = useState<ModelConfig | null>(null);
  const [modelBusy, setModelBusy] = useState(false);
  const [modelMessage, setModelMessage] = useState<string | null>(null);
  const [pendingWorkspacePlan, setPendingWorkspacePlan] = useState<WorkspaceMigrationPlan | null>(null);
  const [workspaceBusy, setWorkspaceBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void Promise.all([getConfig(), getStatus(), checkDependencies()])
      .then(([loadedConfig, loadedStatus, loadedDependencies]) => {
        if (cancelled) return;
        setConfig(loadedConfig);
        setStatus(loadedStatus);
        setDependencies(loadedDependencies);
      })
      .catch(() => {
        if (cancelled) return;
        setStatus({ ...fallbackStatus, state: "failed", message: "无法读取启动器状态" });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    let unlisten: (() => void) | null = null;
    const refreshModelConfig = () => {
      void getModelConfig()
        .then((loadedModelConfig) => {
          if (cancelled) return;
          setModelConfig(loadedModelConfig);
        })
        .catch((error) => {
          if (cancelled) return;
          setModelMessage(`模型配置读取失败：${getErrorMessage(error)}`);
        });
    };
    refreshModelConfig();
    void listen("model-config-changed", refreshModelConfig).then((cleanup) => {
      unlisten = cleanup;
    });
    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, []);

  async function handleStart() {
    setNotice(null);
    setStatus((current) => ({ ...current, state: "starting", message: "正在启动或复用本地服务..." }));
    const nextStatus = await startServices();
    setStatus(nextStatus);
  }

  async function handleStop() {
    setNotice(null);
    setStatus((current) => ({ ...current, state: "stopping", message: "正在停止本地服务..." }));
    const nextStatus = await stopServices();
    setStatus(nextStatus);
  }

  async function handleSavePorts(webPort: number, apiPort: number): Promise<boolean> {
    if (!config) return false;
    if (isServiceBusy(status.state)) {
      setNotice("请先停止服务，再修改端口。");
      return false;
    }
    if (webPort === apiPort && config.webHost === config.apiHost) {
      setNotice("网页端口和 API 端口不能相同。");
      return false;
    }
    const nextConfig = await saveConfig({ ...config, webPort, apiPort });
    setConfig(nextConfig);
    setStatus((current) => ({
      ...current,
      apiUrl: `http://${nextConfig.apiHost}:${nextConfig.apiPort}`,
      webUrl: `http://${nextConfig.webHost}:${nextConfig.webPort}`,
      message: "端口已保存，下一次启动服务时生效。",
    }));
    setNotice("端口已保存，下一次启动服务时生效。");
    return true;
  }

  async function handleSaveModelConfig(input: ModelConfigInput, successMessage: string): Promise<boolean> {
    setModelBusy(true);
    setModelMessage(null);
    try {
      const next = await saveModelConfig(input);
      setModelConfig(next);
      setModelMessage(successMessage);
      return true;
    } catch (error) {
      setModelMessage(`模型配置保存失败：${getErrorMessage(error)}`);
      return false;
    } finally {
      setModelBusy(false);
    }
  }

  async function handleChangeWorkspace() {
    if (!config || workspaceBusy) return;
    if (isServiceBusy(status.state)) {
      setNotice("请先停止服务，再切换 Workspace。");
      return;
    }
    setPendingWorkspacePlan(null);
    setNotice("请选择新的 Workspace 目录。");

    try {
      const target = await chooseWorkspaceDirectory();
      if (!target) {
        setNotice(null);
        return;
      }

      setWorkspaceBusy(true);
      setNotice("正在检查 Workspace...");
      const plan = await planWorkspaceMigration(config.workspaceDir, target);

      if (plan.requiresMigration) {
        setPendingWorkspacePlan(plan);
        setNotice(null);
        return;
      }

      const nextConfig = await setWorkspaceDirectory(plan.target, false);
      setConfig(nextConfig);
      setNotice("Workspace 已切换。");
    } catch (error) {
      setPendingWorkspacePlan(null);
      setNotice(`Workspace 切换失败：${getErrorMessage(error)}`);
    } finally {
      setWorkspaceBusy(false);
    }
  }

  async function handleConfirmWorkspaceMigration() {
    if (!pendingWorkspacePlan || workspaceBusy) return;
    setWorkspaceBusy(true);
    setNotice("正在迁移 Workspace...");

    try {
      const nextConfig = await setWorkspaceDirectory(pendingWorkspacePlan.target, true);
      setConfig(nextConfig);
      setPendingWorkspacePlan(null);
      setNotice("Workspace 已迁移并切换。");
    } catch (error) {
      setNotice(`Workspace 切换失败：${getErrorMessage(error)}`);
    } finally {
      setWorkspaceBusy(false);
    }
  }

  function handleCancelWorkspaceMigration() {
    setPendingWorkspacePlan(null);
    setNotice("已取消 Workspace 切换。");
  }

  return (
    <MainLauncher
      config={config}
      status={status}
      dependencies={dependencies}
      notice={notice}
      modelConfig={modelConfig}
      modelBusy={modelBusy}
      modelMessage={modelMessage}
      onSaveModelConfig={handleSaveModelConfig}
      onStart={handleStart}
      onStop={handleStop}
      onSavePorts={handleSavePorts}
      onChangeWorkspace={handleChangeWorkspace}
      pendingWorkspacePlan={pendingWorkspacePlan}
      workspaceBusy={workspaceBusy}
      onConfirmWorkspaceMigration={handleConfirmWorkspaceMigration}
      onCancelWorkspaceMigration={handleCancelWorkspaceMigration}
    />
  );
}

type SharedLauncherProps = {
  config: LauncherConfig | null;
  status: LauncherStatus;
  dependencies: DependencyStatus[];
  notice: string | null;
  modelConfig: ModelConfig | null;
  modelBusy: boolean;
  modelMessage: string | null;
  onSaveModelConfig: (input: ModelConfigInput, successMessage: string) => Promise<boolean>;
  onStart: () => Promise<void>;
  onStop: () => Promise<void>;
  onSavePorts: (webPort: number, apiPort: number) => Promise<boolean>;
  onChangeWorkspace: () => Promise<void>;
  pendingWorkspacePlan: WorkspaceMigrationPlan | null;
  workspaceBusy: boolean;
  onConfirmWorkspaceMigration: () => Promise<void>;
  onCancelWorkspaceMigration: () => void;
};

function MainLauncher({
  config,
  status,
  dependencies,
  notice,
  modelConfig,
  modelBusy,
  modelMessage,
  onSaveModelConfig,
  onStart,
  onStop,
  onSavePorts,
  onChangeWorkspace,
  pendingWorkspacePlan,
  workspaceBusy,
  onConfirmWorkspaceMigration,
  onCancelWorkspaceMigration,
}: SharedLauncherProps) {
  const [portsEditing, setPortsEditing] = useState(false);
  const [modelArchiveOpen, setModelArchiveOpen] = useState(false);

  return (
    <main className="launcher-shell" aria-label="Course Navigator">
      <section className="hero-panel">
        <div className="hero-content">
          <p className="brand-line">Course Navigator</p>
          <h1>视频学习工作台</h1>
          <p className="hero-copy">用菜单栏启动本地服务，打开课程库、缓存并管理学习内容。</p>
          <div className="hero-actions" aria-label="服务操作">
            <button type="button" onClick={() => void onStart()}>
              <Play size={20} />
              启动
            </button>
            <button type="button" onClick={() => void onStop()}>
              <Square size={20} />
              停止
            </button>
            {notice ? <p>{notice}</p> : null}
          </div>
        </div>
        <div className={`status-orb status-orb-${status.state}`} aria-label={`当前状态 ${status.state}`}>
          <Activity size={36} />
          <span>{status.state}</span>
        </div>
      </section>

      <div className="settings-grid">
        <section className="config-panel" aria-label="路径配置">
          <ConfigRow title="项目目录" value={config?.projectRoot ?? "读取中"} hint="由启动器自动识别" />
          <ConfigRow
            title="工作区"
            value={config?.workspaceDir ?? "读取中"}
            titleAction={
              <button
                type="button"
                className="chip-action"
                aria-label="修改工作区"
                onClick={() => void onChangeWorkspace()}
                disabled={!config}
              >
                修改
              </button>
            }
          />
          {pendingWorkspacePlan ? (
            <section className="workspace-confirm" role="dialog" aria-label="确认 Workspace 迁移">
              <div>
                <span>需要迁移 Workspace</span>
                <p>检测到当前 Workspace 已有数据。确认后会复制到新位置，验证通过后再清理旧 Workspace。</p>
                <small>{pendingWorkspacePlan.target}</small>
              </div>
              <div className="workspace-confirm-actions">
                <button type="button" onClick={() => void onConfirmWorkspaceMigration()} disabled={workspaceBusy}>
                  <CheckCircle2 size={16} />
                  迁移并切换
                </button>
                <button type="button" className="ghost-button" onClick={onCancelWorkspaceMigration} disabled={workspaceBusy}>
                  <X size={16} />
                  取消
                </button>
              </div>
            </section>
          ) : null}
        </section>

        <PortSettings
          config={config}
          status={status}
          editing={portsEditing}
          onEditingChange={setPortsEditing}
          onSavePorts={onSavePorts}
        />
      </div>

      <ModelConfigPanel
        modelConfig={modelConfig}
        busy={modelBusy}
        message={modelMessage}
        onSaveModelConfig={onSaveModelConfig}
        onOpenArchive={() => setModelArchiveOpen(true)}
      />

      <section className="dependency-panel" aria-label="依赖检查">
        <span>依赖检查</span>
        <div className="dependency-list">
          {dependencies.map((dependency) => (
            <div className={`dependency-row ${dependency.available ? "" : "dependency-row-failed"}`} key={dependency.name}>
              {dependency.available ? <CheckCircle2 size={17} /> : <XCircle size={17} />}
              <strong>{dependency.name}</strong>
              <p>{dependency.purpose}</p>
            </div>
          ))}
        </div>
      </section>

      {modelArchiveOpen && modelConfig ? (
        <ModelArchiveDialog
          modelConfig={modelConfig}
          busy={modelBusy}
          onClose={() => setModelArchiveOpen(false)}
          onSaveModelConfig={onSaveModelConfig}
        />
      ) : null}
    </main>
  );
}

function ModelConfigPanel({
  modelConfig,
  busy,
  message,
  onSaveModelConfig,
  onOpenArchive,
}: {
  modelConfig: ModelConfig | null;
  busy: boolean;
  message: string | null;
  onSaveModelConfig: (input: ModelConfigInput, successMessage: string) => Promise<boolean>;
  onOpenArchive: () => void;
}) {
  const profiles = modelConfig?.profiles ?? [];

  async function updateRole(field: ModelRoleField, profileId: string) {
    if (!modelConfig) return;
    const role = MODEL_ROLE_OPTIONS.find((option) => option.field === field);
    await onSaveModelConfig({ ...modelConfigToInput(modelConfig), [field]: profileId }, `${role?.label ?? "模型"}已切换。`);
  }

  async function updateOnlineAsr(provider: OnlineAsrProvider) {
    if (!modelConfig) return;
    const input = modelConfigToInput(modelConfig);
    input.onlineAsr.provider = provider;
    await onSaveModelConfig(input, "在线 ASR 模型已切换。");
  }

  return (
    <section className="model-panel" aria-label="模型配置">
      <div className="panel-title-row">
        <span className="section-title">模型配置</span>
        <button type="button" className="chip-action" onClick={onOpenArchive} disabled={!modelConfig || busy}>
          <SlidersHorizontal size={14} />
          模型档案
        </button>
      </div>

      {modelConfig ? (
        <div className="model-select-grid">
          {MODEL_ROLE_OPTIONS.map((role) => (
            <ModelRoleSelect
              key={role.field}
              label={role.label}
              hint={role.hint}
              value={modelConfig[role.field]}
              profiles={profiles}
              disabled={busy}
              onChange={(profileId) => void updateRole(role.field, profileId)}
            />
          ))}
          <label className="model-select-card">
            <span>在线 ASR 模型</span>
            <select
              aria-label="在线 ASR 模型"
              value={modelConfig.onlineAsr.provider}
              disabled={busy}
              onChange={(event) => void updateOnlineAsr(event.target.value as OnlineAsrProvider)}
            >
              {ONLINE_ASR_OPTIONS.map((option) => (
                <option value={option.value} key={option.value}>
                  {onlineAsrOptionLabel(modelConfig, option.value)}
                </option>
              ))}
            </select>
            <small>{onlineAsrStatusText(modelConfig)}</small>
          </label>
        </div>
      ) : (
        <p className="model-empty">正在读取模型配置...</p>
      )}
      {message ? <p className="model-message">{message}</p> : null}
    </section>
  );
}

function ModelRoleSelect({
  label,
  hint,
  value,
  profiles,
  disabled,
  onChange,
}: {
  label: string;
  hint: string;
  value: string;
  profiles: ModelConfig["profiles"];
  disabled: boolean;
  onChange: (profileId: string) => void;
}) {
  return (
    <label className="model-select-card">
      <span>{label}</span>
      <select
        aria-label={label}
        value={value}
        disabled={disabled || !profiles.length}
        onChange={(event) => onChange(event.target.value)}
      >
        {profiles.map((profile) => (
          <option value={profile.id} key={profile.id}>
            {profileLabel(profile)}
          </option>
        ))}
      </select>
      <small>{hint}</small>
    </label>
  );
}

function ModelArchiveDialog({
  modelConfig,
  busy,
  onClose,
  onSaveModelConfig,
}: {
  modelConfig: ModelConfig;
  busy: boolean;
  onClose: () => void;
  onSaveModelConfig: (input: ModelConfigInput, successMessage: string) => Promise<boolean>;
}) {
  const [archiveMode, setArchiveMode] = useState<"llm" | "onlineAsr">("llm");
  const [llmDraft, setLlmDraft] = useState(() => llmArchiveDraftFromConfig(modelConfig));
  const [onlineDraft, setOnlineDraft] = useState(() => onlineDraftFromConfig(modelConfig));
  const [onlineEditingProvider, setOnlineEditingProvider] = useState<EditableOnlineAsrProvider>(() =>
    modelConfig.onlineAsr.provider === "none" ? "openai" : modelConfig.onlineAsr.provider,
  );
  const [localError, setLocalError] = useState<string | null>(null);
  const selectedProfile =
    llmDraft.profiles.find((profile) => profile.id === llmDraft.activeProfileId) ?? llmDraft.profiles[0];

  useEffect(() => {
    setLlmDraft((current) => llmArchiveDraftFromConfig(modelConfig, current.activeProfileId));
    setOnlineDraft(onlineDraftFromConfig(modelConfig));
    setOnlineEditingProvider(modelConfig.onlineAsr.provider === "none" ? "openai" : modelConfig.onlineAsr.provider);
  }, [modelConfig]);

  function updateSelectedProfile(patch: Partial<LlmProfileDraft>) {
    if (!selectedProfile) return;
    setLlmDraft((current) => ({
      ...current,
      profiles: current.profiles.map((profile) => (profile.id === selectedProfile.id ? { ...profile, ...patch } : profile)),
    }));
  }

  function addProfile() {
    setLocalError(null);
    const id = `profile-${Date.now()}`;
    setLlmDraft((current) => ({
      ...current,
      activeProfileId: id,
      profiles: [
        ...current.profiles,
        {
          id,
          name: "",
          providerType: "openai",
          baseUrl: "",
          model: "",
          contextWindow: null,
          maxTokens: null,
          apiKey: "",
          apiKeyPreview: null,
        },
      ],
    }));
  }

  async function saveLlmArchive() {
    setLocalError(null);
    if (!llmDraft.profiles.length) {
      setLocalError("至少需要一个 LLM 模型档案。");
      return;
    }
    if (llmDraft.profiles.some((profile) => !profile.baseUrl.trim() || !profile.model.trim())) {
      setLocalError("LLM 档案需要接口地址和模型名称。");
      return;
    }
    const input = modelConfigToInput(modelConfig);
    input.profiles = llmDraft.profiles.map((profile) => ({
      id: profile.id,
      name: profile.name.trim() || modelLabelFromName(profile.model),
      providerType: profile.providerType,
      baseUrl: profile.baseUrl.trim(),
      model: profile.model.trim(),
      contextWindow: null,
      maxTokens: null,
      ...apiKeyInput(profile.apiKey, profile.apiKeyPreview),
    }));
    const profileIds = new Set(input.profiles.map((profile) => profile.id));
    const firstId = input.profiles[0]?.id ?? "default";
    if (!profileIds.has(input.translationModelId)) input.translationModelId = firstId;
    if (!profileIds.has(input.learningModelId)) input.learningModelId = firstId;
    if (!profileIds.has(input.globalModelId)) input.globalModelId = firstId;
    if (!profileIds.has(input.asrModelId)) input.asrModelId = firstId;
    await onSaveModelConfig(input, "档案已保存。");
  }

  async function saveOnlineAsrArchive() {
    setLocalError(null);
    const input = modelConfigToInput(modelConfig);
    input.onlineAsr = {
      provider: modelConfig.onlineAsr.provider,
      openai: {
        model: modelConfig.onlineAsr.openai.model,
        ...apiKeyInput(onlineDraft.openaiApiKey, modelConfig.onlineAsr.openai.apiKeyPreview),
      },
      groq: {
        model: modelConfig.onlineAsr.groq.model,
        ...apiKeyInput(onlineDraft.groqApiKey, modelConfig.onlineAsr.groq.apiKeyPreview),
      },
      xai: {
        model: onlineDraft.xaiModel.trim() || "grok-2-voice-1212",
        ...apiKeyInput(onlineDraft.xaiApiKey, modelConfig.onlineAsr.xai.apiKeyPreview),
      },
      custom: {
        baseUrl: onlineDraft.customBaseUrl.trim() || null,
        model: onlineDraft.customModel.trim() || null,
        ...apiKeyInput(onlineDraft.customApiKey, modelConfig.onlineAsr.custom.apiKeyPreview),
      },
    };
    await onSaveModelConfig(input, "ASR 档案已保存。");
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="model-modal" role="dialog" aria-modal="true" aria-labelledby="model-archive-title">
        <div className="model-modal-head">
          <div>
            <span>Course Navigator</span>
            <h2 id="model-archive-title">模型档案</h2>
          </div>
          <button type="button" className="icon-button" aria-label="关闭模型档案" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        <div className="archive-mode-tabs" role="tablist" aria-label="模型档案类型">
          <button
            type="button"
            className={archiveMode === "llm" ? "active" : ""}
            onClick={() => setArchiveMode("llm")}
          >
            <KeyRound size={15} />
            LLM 模型档案
          </button>
          <button
            type="button"
            className={archiveMode === "onlineAsr" ? "active" : ""}
            onClick={() => setArchiveMode("onlineAsr")}
          >
            <Radio size={15} />
            在线 ASR 档案
          </button>
        </div>

        {archiveMode === "llm" ? (
          <section className="archive-section">
            <div className="archive-section-title">
              <KeyRound size={16} />
              <span>模型档案</span>
              <button type="button" className="secondary-action" onClick={addProfile}>
                <Plus size={14} />
                新增档案
              </button>
            </div>

            <div className="archive-form">
              <label>
                正在编辑
                <select
                  value={selectedProfile?.id ?? ""}
                  onChange={(event) => setLlmDraft((current) => ({ ...current, activeProfileId: event.target.value }))}
                >
                  {llmDraft.profiles.map((profile) => (
                    <option value={profile.id} key={profile.id}>
                      {profileLabel(profile)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                接口格式
                <select
                  value={selectedProfile?.providerType ?? "openai"}
                  onChange={(event) => updateSelectedProfile({ providerType: event.target.value as ModelProviderType })}
                >
                  <option value="openai">OpenAI 格式</option>
                  <option value="anthropic">Anthropic 格式</option>
                </select>
              </label>
              <label>
                档案名称
                <input
                  value={selectedProfile?.name ?? ""}
                  onChange={(event) => updateSelectedProfile({ name: event.target.value })}
                />
              </label>
              <label>
                接口地址
                <input
                  value={selectedProfile?.baseUrl ?? ""}
                  onChange={(event) => updateSelectedProfile({ baseUrl: event.target.value })}
                  placeholder={providerBaseUrlPlaceholder(selectedProfile?.providerType ?? "openai")}
                />
              </label>
              <label>
                API Key
                <input
                  autoComplete="off"
                  value={selectedProfile?.apiKey ?? ""}
                  onChange={(event) => updateSelectedProfile({ apiKey: event.target.value })}
                />
              </label>
              <label>
                模型
                <input
                  value={selectedProfile?.model ?? ""}
                  onChange={(event) => updateSelectedProfile({ model: event.target.value })}
                />
              </label>
            </div>

            <div className="modal-actions">
              {localError ? <span className="model-message error">{localError}</span> : <span />}
              <div className="modal-action-buttons">
                <button type="button" className="ghost-button" onClick={onClose} disabled={busy}>
                  取消
                </button>
                <button type="button" onClick={() => void saveLlmArchive()} disabled={busy}>
                  <Save size={16} />
                  保存档案
                </button>
              </div>
            </div>
          </section>
        ) : (
          <section className="archive-section">
            <div className="archive-section-title">
              <Radio size={16} />
              <span>在线 ASR 档案</span>
            </div>
            <div className="archive-form">
              <label>
                正在配置
                <select
                  value={onlineEditingProvider}
                  onChange={(event) => setOnlineEditingProvider(event.target.value as EditableOnlineAsrProvider)}
                >
                  {ONLINE_ASR_OPTIONS.filter((option) => option.value !== "none").map((option) => (
                    <option value={option.value} key={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>

              {onlineEditingProvider === "custom" ? (
                <>
                  <label>
                    自定义接口地址
                    <input
                      value={onlineDraft.customBaseUrl}
                      onChange={(event) => setOnlineDraft((current) => ({ ...current, customBaseUrl: event.target.value }))}
                      placeholder="https://api.example.com/v1/audio/transcriptions"
                    />
                  </label>
                  <label>
                    自定义模型名称
                    <input
                      value={onlineDraft.customModel}
                      onChange={(event) => setOnlineDraft((current) => ({ ...current, customModel: event.target.value }))}
                    />
                  </label>
                </>
              ) : null}

              {onlineEditingProvider === "xai" ? (
                <label>
                  xAI 模型
                  <input
                    value={onlineDraft.xaiModel}
                    onChange={(event) => setOnlineDraft((current) => ({ ...current, xaiModel: event.target.value }))}
                    placeholder="grok-2-voice-1212"
                  />
                </label>
              ) : null}

              <label>
                在线 ASR API Key
                <input
                  aria-label="在线 ASR API Key"
                  autoComplete="off"
                  value={onlineAsrApiKeyValue(onlineDraft, onlineEditingProvider)}
                  onChange={(event) =>
                    setOnlineDraft((current) => onlineAsrDraftWithKey(current, onlineEditingProvider, event.target.value))
                  }
                />
                <small>
                  {onlineEditingProvider === "custom"
                    ? "需兼容 OpenAI audio transcriptions；可填完整 /audio/transcriptions 或 /v1 Base URL，纯文本不能生成可对齐字幕。"
                    : "选择在线 ASR 作为字幕来源时，会自动抽取音频、压缩并分块转写。"}
                </small>
              </label>
            </div>

            <div className="modal-actions">
              {localError ? <span className="model-message error">{localError}</span> : <span />}
              <div className="modal-action-buttons">
                <button type="button" className="ghost-button" onClick={onClose} disabled={busy}>
                  取消
                </button>
                <button type="button" onClick={() => void saveOnlineAsrArchive()} disabled={busy}>
                  <Save size={16} />
                  保存在线 ASR 档案
                </button>
              </div>
            </div>
          </section>
        )}
      </section>
    </div>
  );
}

function PortSettings({
  config,
  status,
  editing,
  onEditingChange,
  onSavePorts,
}: {
  config: LauncherConfig | null;
  status: LauncherStatus;
  editing: boolean;
  onEditingChange: (editing: boolean) => void;
  onSavePorts: (webPort: number, apiPort: number) => Promise<boolean>;
}) {
  const [webPort, setWebPort] = useState("");
  const [apiPort, setApiPort] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!editing) return;
    setWebPort(String(config?.webPort ?? 5173));
    setApiPort(String(config?.apiPort ?? 8000));
    setError(null);
  }, [config, editing]);

  function parsePort(value: string): number | null {
    const port = Number(value);
    return Number.isInteger(port) && port >= 1 && port <= 65535 ? port : null;
  }

  async function savePorts() {
    const nextWebPort = parsePort(webPort);
    const nextApiPort = parsePort(apiPort);
    if (!nextWebPort || !nextApiPort) {
      setError("端口必须是 1-65535 之间的整数。");
      return;
    }
    const saved = await onSavePorts(nextWebPort, nextApiPort);
    if (saved) {
      onEditingChange(false);
      setError(null);
    }
  }

  return (
    <section className="port-panel" aria-label="端口配置">
      <div className="panel-title-row">
        <div className="panel-title">
          <Activity size={18} />
          <span>端口配置</span>
        </div>
        <button
          type="button"
          className="chip-action"
          aria-label="修改端口"
          onClick={() => onEditingChange(true)}
          disabled={!config || editing}
        >
          修改
        </button>
      </div>

      {editing ? (
        <div className="port-editor">
          <label>
            网页端口
            <input inputMode="numeric" value={webPort} onChange={(event) => setWebPort(event.target.value)} />
          </label>
          <label>
            API 端口
            <input inputMode="numeric" value={apiPort} onChange={(event) => setApiPort(event.target.value)} />
          </label>
          <button type="button" onClick={() => void savePorts()}>
            <Save size={16} />
            保存端口
          </button>
          <button type="button" className="ghost-button" onClick={() => onEditingChange(false)}>
            <X size={16} />
            取消
          </button>
          {error ? <p>{error}</p> : null}
        </div>
      ) : (
        <div className="port-list">
          <PortLine icon={<MonitorUp size={18} />} label="网页" value={status.webUrl} />
          <PortLine icon={<Activity size={18} />} label="API" value={status.apiUrl} />
        </div>
      )}
    </section>
  );
}

function PortLine({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="port-line">
      {icon}
      <div>
        <span>{label}</span>
        <p>{value}</p>
      </div>
    </div>
  );
}

function ConfigRow({
  title,
  value,
  hint,
  titleAction,
}: {
  title: string;
  value: string;
  hint?: string;
  titleAction?: ReactNode;
}) {
  return (
    <div className="config-row">
      <FolderOpen size={18} />
      <div>
        <div className="config-row-heading">
          <span>{title}</span>
          {titleAction}
        </div>
        <p>{value}</p>
        {hint ? <small>{hint}</small> : null}
      </div>
    </div>
  );
}

function modelConfigToInput(config: ModelConfig): ModelConfigInput {
  return {
    profiles: config.profiles.map((profile) => ({
      id: profile.id,
      name: profile.name,
      providerType: profile.providerType,
      baseUrl: profile.baseUrl,
      model: profile.model,
      contextWindow: profile.contextWindow ?? null,
      maxTokens: profile.maxTokens ?? null,
    })),
    translationModelId: config.translationModelId,
    learningModelId: config.learningModelId,
    globalModelId: config.globalModelId,
    asrModelId: config.asrModelId,
    studyDetailLevel: config.studyDetailLevel,
    taskParameters: config.taskParameters,
    onlineAsr: {
      provider: config.onlineAsr.provider,
      openai: {
        baseUrl: config.onlineAsr.openai.baseUrl ?? null,
        model: config.onlineAsr.openai.model ?? null,
      },
      groq: {
        baseUrl: config.onlineAsr.groq.baseUrl ?? null,
        model: config.onlineAsr.groq.model ?? null,
      },
      xai: {
        baseUrl: config.onlineAsr.xai.baseUrl ?? null,
        model: config.onlineAsr.xai.model ?? null,
      },
      custom: {
        baseUrl: config.onlineAsr.custom.baseUrl ?? null,
        model: config.onlineAsr.custom.model ?? null,
      },
    },
  };
}

function llmArchiveDraftFromConfig(config: ModelConfig, preferredActiveProfileId?: string): LlmArchiveDraft {
  const profiles = config.profiles.map((profile) => ({
    id: profile.id,
    name: profile.name,
    providerType: profile.providerType,
    baseUrl: profile.baseUrl,
    model: profile.model,
    contextWindow: profile.contextWindow ?? null,
    maxTokens: profile.maxTokens ?? null,
    apiKeyPreview: profile.apiKeyPreview ?? null,
    apiKey: maskedSecretValue(profile.apiKeyPreview),
  }));
  if (!profiles.length) {
    profiles.push({
      id: "default",
      name: "",
      providerType: "openai",
      baseUrl: "",
      model: "",
      contextWindow: null,
      maxTokens: null,
      apiKeyPreview: null,
      apiKey: "",
    });
  }
  const activeProfileId =
    profiles.find((profile) => profile.id === preferredActiveProfileId)?.id ??
    profiles.find((profile) => profile.id === config.translationModelId)?.id ??
    profiles[0].id;
  return { profiles, activeProfileId };
}

function profileLabel(profile: Pick<ModelConfig["profiles"][number], "name" | "model">) {
  return profile.name.trim() || (profile.model.trim() ? modelLabelFromName(profile.model) : "未命名档案");
}

function modelLabelFromName(model: string) {
  return model.split("/").pop()?.replace(/[-_]/g, " ").trim() || "未命名模型";
}

function onlineAsrOptionLabel(config: ModelConfig, provider: OnlineAsrProvider) {
  if (provider === "none") return "不启用在线 ASR";
  if (provider === "openai") return `OpenAI Whisper · ${config.onlineAsr.openai.model ?? "whisper-1"}`;
  if (provider === "groq") return `Groq Whisper · ${config.onlineAsr.groq.model ?? "whisper-large-v3-turbo"}`;
  if (provider === "xai") return `xAI · ${config.onlineAsr.xai.model ?? "grok-2-voice-1212"}`;
  return `自定义 · ${config.onlineAsr.custom.model ?? "未设置模型"}`;
}

function onlineAsrStatusText(config: ModelConfig) {
  const provider = config.onlineAsr.provider;
  if (provider === "none") return "本地 ASR 或平台字幕优先";
  const service = config.onlineAsr[provider];
  return service.hasApiKey ? "Key 已配置" : "需要在模型档案中补充 Key";
}

function maskedSecretValue(preview: string | null | undefined): string {
  return preview ?? "";
}

function secretInputValue(value: string | null | undefined, preview: string | null | undefined): string | undefined {
  const trimmed = (value ?? "").trim();
  if (!trimmed) return undefined;
  return preview && trimmed === preview.trim() ? undefined : trimmed;
}

function apiKeyInput(value: string | null | undefined, preview: string | null | undefined): { apiKey: string } | Record<string, never> {
  const apiKey = secretInputValue(value, preview);
  return apiKey ? { apiKey } : {};
}

function onlineDraftFromConfig(config: ModelConfig): OnlineAsrDraft {
  return {
    provider: config.onlineAsr.provider,
    openaiApiKey: maskedSecretValue(config.onlineAsr.openai.apiKeyPreview),
    groqApiKey: maskedSecretValue(config.onlineAsr.groq.apiKeyPreview),
    xaiApiKey: maskedSecretValue(config.onlineAsr.xai.apiKeyPreview),
    xaiModel: config.onlineAsr.xai.model ?? "grok-2-voice-1212",
    customBaseUrl: config.onlineAsr.custom.baseUrl ?? "",
    customModel: config.onlineAsr.custom.model ?? "",
    customApiKey: maskedSecretValue(config.onlineAsr.custom.apiKeyPreview),
  };
}

function onlineAsrApiKeyValue(draft: OnlineAsrDraft, provider: EditableOnlineAsrProvider): string {
  return {
    openai: draft.openaiApiKey,
    groq: draft.groqApiKey,
    xai: draft.xaiApiKey,
    custom: draft.customApiKey,
  }[provider];
}

function onlineAsrDraftWithKey(
  draft: OnlineAsrDraft,
  provider: EditableOnlineAsrProvider,
  value: string,
): OnlineAsrDraft {
  return {
    openai: { ...draft, openaiApiKey: value },
    groq: { ...draft, groqApiKey: value },
    xai: { ...draft, xaiApiKey: value },
    custom: { ...draft, customApiKey: value },
  }[provider];
}

function providerBaseUrlPlaceholder(providerType: ModelProviderType) {
  return providerType === "anthropic" ? "https://api.anthropic.com" : "https://api.openai.com/v1";
}
