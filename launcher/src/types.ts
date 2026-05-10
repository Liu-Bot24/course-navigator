export type ServiceState = "stopped" | "starting" | "running" | "stopping" | "failed";

export type LauncherConfig = {
  projectRoot: string;
  apiHost: string;
  apiPort: number;
  webHost: string;
  webPort: number;
  workspaceDir: string;
  openBrowserOnStart: boolean;
};

export type LauncherStatus = {
  state: ServiceState;
  apiUrl: string;
  webUrl: string;
  message: string;
};

export type DependencyStatus = {
  name: string;
  available: boolean;
  purpose: string;
};

export type WorkspaceMigrationPlan = {
  source: string;
  target: string;
  requiresMigration: boolean;
  message: string;
};

export type ModelProviderType = "openai" | "anthropic";

export type OnlineAsrProvider = "none" | "openai" | "groq" | "xai" | "custom";

export type ModelProfile = {
  id: string;
  name: string;
  providerType: ModelProviderType;
  baseUrl: string;
  model: string;
  contextWindow?: number | null;
  maxTokens?: number | null;
  hasApiKey: boolean;
  apiKeyPreview?: string | null;
};

export type ModelProfileInput = {
  id: string;
  name: string;
  providerType: ModelProviderType;
  baseUrl: string;
  model: string;
  contextWindow?: number | null;
  maxTokens?: number | null;
  apiKey?: string;
};

export type OnlineAsrService = {
  baseUrl?: string | null;
  model?: string | null;
  hasApiKey: boolean;
  apiKeyPreview?: string | null;
};

export type OnlineAsrServiceInput = {
  baseUrl?: string | null;
  model?: string | null;
  apiKey?: string;
};

export type OnlineAsrConfig = {
  provider: OnlineAsrProvider;
  openai: OnlineAsrService;
  groq: OnlineAsrService;
  xai: OnlineAsrService;
  custom: OnlineAsrService;
};

export type OnlineAsrConfigInput = {
  provider: OnlineAsrProvider;
  openai: OnlineAsrServiceInput;
  groq: OnlineAsrServiceInput;
  xai: OnlineAsrServiceInput;
  custom: OnlineAsrServiceInput;
};

export type ModelConfig = {
  profiles: ModelProfile[];
  translationModelId: string;
  learningModelId: string;
  globalModelId: string;
  asrModelId: string;
  studyDetailLevel: string;
  taskParameters: Record<string, unknown>;
  onlineAsr: OnlineAsrConfig;
};

export type ModelConfigInput = {
  profiles: ModelProfileInput[];
  translationModelId: string;
  learningModelId: string;
  globalModelId: string;
  asrModelId: string;
  studyDetailLevel: string;
  taskParameters: Record<string, unknown>;
  onlineAsr: OnlineAsrConfigInput;
};
