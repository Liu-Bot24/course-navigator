import { invoke } from "@tauri-apps/api/core";

import type {
  DependencyStatus,
  LauncherConfig,
  LauncherStatus,
  ModelConfig,
  ModelConfigInput,
  WorkspaceMigrationPlan,
} from "./types";

export async function getConfig(): Promise<LauncherConfig> {
  return invoke<LauncherConfig>("get_config");
}

export async function saveConfig(config: LauncherConfig): Promise<LauncherConfig> {
  return invoke<LauncherConfig>("save_config", { config });
}

export async function getStatus(): Promise<LauncherStatus> {
  return invoke<LauncherStatus>("get_status");
}

export async function checkDependencies(): Promise<DependencyStatus[]> {
  return invoke<DependencyStatus[]>("check_dependencies");
}

export async function getModelConfig(): Promise<ModelConfig> {
  return invoke<ModelConfig>("get_model_config");
}

export async function saveModelConfig(input: ModelConfigInput): Promise<ModelConfig> {
  return invoke<ModelConfig>("save_model_config", { input });
}

export async function startServices(): Promise<LauncherStatus> {
  return invoke<LauncherStatus>("start_services");
}

export async function stopServices(): Promise<LauncherStatus> {
  return invoke<LauncherStatus>("stop_services");
}

export async function showMainPanel(): Promise<void> {
  return invoke<void>("show_main_panel");
}

export async function openWebPage(): Promise<void> {
  return invoke<void>("open_web_page");
}

export async function chooseWorkspaceDirectory(): Promise<string | null> {
  return invoke<string | null>("choose_workspace_directory");
}

export async function planWorkspaceMigration(source: string, target: string): Promise<WorkspaceMigrationPlan> {
  return invoke<WorkspaceMigrationPlan>("plan_workspace_migration", { source, target });
}

export async function setWorkspaceDirectory(target: string, migrateExisting: boolean): Promise<LauncherConfig> {
  return invoke<LauncherConfig>("set_workspace_directory", { target, migrateExisting });
}
