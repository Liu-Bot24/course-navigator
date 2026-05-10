# Mac Launcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first usable Mac Launcher for Course Navigator: a Tauri desktop app that starts/stops the existing local web app, configures ports and Workspace, opens the default browser, and sets up a clean path toward a future managed runtime.

**Architecture:** Add a separate `launcher/` Tauri app instead of mixing launcher UI into the existing Course Navigator web client. The launcher has a React/Vite UI and a Rust command layer that owns config persistence, dependency checks, project-runtime service management, port health checks, `.env` updates, and Workspace migration. The first runtime provider uses the current project directory and installed tools; future managed runtime support can replace that provider without rewriting the launcher shell.

**Tech Stack:** Tauri v2, Rust, React 19, TypeScript, Vite, Vitest, existing FastAPI backend, existing Vite Course Navigator frontend.

---

## References

- Design spec: `docs/superpowers/specs/2026-05-09-mac-launcher-design.md`
- Tauri v2 create/add-to-existing-project docs: https://v2.tauri.app/start/create-project/
- Tauri v2 sidecar/external binary direction for future runtime work: https://tauri.app/develop/sidecar/

## File Structure

- Create `launcher/package.json`: package scripts and Tauri dependencies for the launcher app.
- Create `launcher/index.html`: Vite HTML entry for launcher UI.
- Create `launcher/tsconfig.json`: TypeScript config for the launcher frontend.
- Create `launcher/vite.config.ts`: Vite config for launcher UI and tests.
- Create `launcher/src/main.tsx`: React entry point.
- Create `launcher/src/App.tsx`: Launcher UI shell.
- Create `launcher/src/api.ts`: typed wrapper around Tauri `invoke`.
- Create `launcher/src/types.ts`: shared frontend types for config/status/log records.
- Create `launcher/src/App.test.tsx`: UI behavior tests.
- Create `launcher/src-tauri/Cargo.toml`: Rust package and Tauri dependencies.
- Create `launcher/src-tauri/build.rs`: Tauri build hook.
- Create `launcher/src-tauri/tauri.conf.json`: Tauri app metadata and capabilities.
- Create `launcher/src-tauri/capabilities/default.json`: command permissions.
- Create `launcher/src-tauri/src/main.rs`: command registration and app lifecycle cleanup.
- Create `launcher/src-tauri/src/config.rs`: launcher config and `.env` update logic.
- Create `launcher/src-tauri/src/runtime.rs`: dependency checks, command construction, process lifecycle.
- Create `launcher/src-tauri/src/workspace.rs`: Workspace validation and migration.
- Create `launcher/src-tauri/src/health.rs`: HTTP health checks.
- Create `launcher/src-tauri/src/models.rs`: Rust DTOs shared by commands.
- Create `launcher/src-tauri/src/tests.rs`: Rust unit tests for config/workspace/runtime helpers.
- Modify `package.json`: add root scripts for launcher development and testing.
- Modify `vite.config.ts`: read `COURSE_NAVIGATOR_API_HOST` and `COURSE_NAVIGATOR_API_PORT` for dynamic proxy support.
- Modify `backend/course_navigator/config.py`: add web host/port settings used by CORS.
- Modify `backend/course_navigator/app.py`: make allowed CORS origins dynamic.
- Modify `backend/tests/test_app.py`: test dynamic CORS behavior.
- Modify `.gitignore`: ignore launcher build artifacts if needed.

## Task 1: Dynamic Web/API Port Support In Existing App

**Files:**
- Modify: `vite.config.ts`
- Modify: `backend/course_navigator/config.py`
- Modify: `backend/course_navigator/app.py`
- Modify: `backend/tests/test_app.py`

- [ ] **Step 1: Write failing backend CORS test**

Add this test near the existing backend settings tests in `backend/tests/test_app.py`:

```python
def test_create_app_allows_configured_web_origin(tmp_path):
    client = make_client(
        tmp_path,
        settings=Settings(
            data_dir=tmp_path,
            web_host="127.0.0.1",
            web_port=61234,
        ),
    )

    response = client.options(
        "/api/items",
        headers={
            "Origin": "http://127.0.0.1:61234",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:61234"
```

- [ ] **Step 2: Run the failing backend test**

Run:

```bash
npm run test:backend -- backend/tests/test_app.py::test_create_app_allows_configured_web_origin
```

Expected: FAIL because `Settings` does not yet accept `web_host` and `web_port`.

- [ ] **Step 3: Add host/port settings**

Update `backend/course_navigator/config.py`:

```python
class Settings(BaseModel):
    data_dir: Path = Path(".course-navigator")
    workspace_dir: Path | None = None
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    web_host: str = "127.0.0.1"
    web_port: int = 5173
    llm_base_url: str | None = None
```

Update `load_settings()` in the same file:

```python
return Settings(
    data_dir=Path(os.getenv("COURSE_NAVIGATOR_DATA_DIR", ".course-navigator")),
    workspace_dir=Path(os.getenv("COURSE_NAVIGATOR_WORKSPACE_DIR", "course-navigator-workspace")),
    api_host=os.getenv("COURSE_NAVIGATOR_API_HOST", "127.0.0.1"),
    api_port=_env_int("COURSE_NAVIGATOR_API_PORT", 8000, minimum=1, maximum=65535),
    web_host=os.getenv("COURSE_NAVIGATOR_WEB_HOST", "127.0.0.1"),
    web_port=_env_int("COURSE_NAVIGATOR_WEB_PORT", 5173, minimum=1, maximum=65535),
    llm_base_url=os.getenv("COURSE_NAVIGATOR_LLM_BASE_URL"),
    llm_api_key=os.getenv("COURSE_NAVIGATOR_LLM_API_KEY"),
    llm_model=legacy_model,
    model_profiles=profiles,
    translation_model_id=os.getenv("COURSE_NAVIGATOR_TRANSLATION_MODEL_ID", "default"),
    learning_model_id=os.getenv("COURSE_NAVIGATOR_LEARNING_MODEL_ID", "default"),
    global_model_id=os.getenv("COURSE_NAVIGATOR_GLOBAL_MODEL_ID", "default"),
    asr_model_id=os.getenv("COURSE_NAVIGATOR_ASR_MODEL_ID", "default"),
    asr_search=_load_asr_search_settings(),
    online_asr=_load_online_asr_settings(),
    study_detail_level=os.getenv("COURSE_NAVIGATOR_STUDY_DETAIL_LEVEL", "faithful"),  # type: ignore[arg-type]
    task_parameters=_load_task_parameters(os.getenv("COURSE_NAVIGATOR_TASK_PARAMETERS")),
)
```

- [ ] **Step 4: Make CORS dynamic**

Update `create_app()` in `backend/course_navigator/app.py`:

```python
    allowed_origins = _web_origins(active_settings.web_host, active_settings.web_port)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
```

Add helper near the lower helper section:

```python
def _web_origins(host: str, port: int) -> list[str]:
    hosts = {host}
    if host == "127.0.0.1":
        hosts.add("localhost")
    if host == "localhost":
        hosts.add("127.0.0.1")
    return [f"http://{candidate}:{port}" for candidate in sorted(hosts)]
```

- [ ] **Step 5: Make Vite proxy dynamic**

Update `vite.config.ts`:

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiHost = process.env.COURSE_NAVIGATOR_API_HOST ?? "127.0.0.1";
const apiPort = process.env.COURSE_NAVIGATOR_API_PORT ?? "8000";

export default defineConfig({
  root: "frontend",
  plugins: [react()],
  server: {
    port: Number(process.env.COURSE_NAVIGATOR_WEB_PORT ?? 5173),
    proxy: {
      "/api": `http://${apiHost}:${apiPort}`,
    },
  },
  build: {
    outDir: "dist",
  },
  test: {
    environment: "jsdom",
    globals: true,
  },
});
```

- [ ] **Step 6: Run backend test**

Run:

```bash
npm run test:backend -- backend/tests/test_app.py::test_create_app_allows_configured_web_origin
```

Expected: PASS.

- [ ] **Step 7: Run existing build**

Run:

```bash
npm run build
```

Expected: PASS with the existing Vite chunk-size warning allowed.

- [ ] **Step 8: Commit**

```bash
git add vite.config.ts backend/course_navigator/config.py backend/course_navigator/app.py backend/tests/test_app.py
git commit -m "feat: support dynamic local app ports"
```

## Task 2: Scaffold Tauri Launcher App

**Files:**
- Create: `launcher/package.json`
- Create: `launcher/index.html`
- Create: `launcher/tsconfig.json`
- Create: `launcher/vite.config.ts`
- Create: `launcher/src/main.tsx`
- Create: `launcher/src/types.ts`
- Create: `launcher/src/api.ts`
- Create: `launcher/src/App.tsx`
- Create: `launcher/src/App.test.tsx`
- Create: `launcher/src-tauri/Cargo.toml`
- Create: `launcher/src-tauri/build.rs`
- Create: `launcher/src-tauri/tauri.conf.json`
- Create: `launcher/src-tauri/capabilities/default.json`
- Create: `launcher/src-tauri/src/main.rs`
- Modify: `package.json`

- [ ] **Step 1: Add launcher package metadata**

Create `launcher/package.json`:

```json
{
  "name": "course-navigator-launcher",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "test": "vitest run",
    "tauri": "tauri",
    "tauri:dev": "tauri dev",
    "tauri:build": "tauri build"
  },
  "dependencies": {
    "@tauri-apps/api": "^2.0.0",
    "lucide-react": "^0.561.0",
    "react": "^19.2.0",
    "react-dom": "^19.2.0"
  },
  "devDependencies": {
    "@tauri-apps/cli": "^2.0.0",
    "@testing-library/react": "^16.3.0",
    "@types/react": "^19.2.7",
    "@types/react-dom": "^19.2.3",
    "@vitejs/plugin-react": "^5.1.1",
    "jsdom": "^27.3.0",
    "typescript": "^5.9.3",
    "vite": "^7.2.7",
    "vitest": "^4.0.15"
  }
}
```

- [ ] **Step 2: Add launcher frontend shell files**

Create `launcher/index.html`:

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Course Navigator Launcher</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

Create `launcher/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "allowJs": false,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "forceConsistentCasingInFileNames": true,
    "module": "ESNext",
    "moduleResolution": "Node",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "types": ["vitest/globals"]
  },
  "include": ["src"]
}
```

Create `launcher/vite.config.ts`:

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 1420,
    strictPort: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
  },
});
```

- [ ] **Step 3: Add root launcher scripts**

Modify root `package.json`:

```json
"launcher:dev": "npm --prefix launcher run tauri:dev",
"launcher:build": "npm --prefix launcher run tauri:build",
"launcher:test": "npm --prefix launcher run test",
"launcher:web": "npm --prefix launcher run dev",
"launcher:build:web": "npm --prefix launcher run build"
```

- [ ] **Step 4: Add minimal launcher UI and tests**

Create `launcher/src/types.ts`:

```ts
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
```

Create `launcher/src/api.ts`:

```ts
import { invoke } from "@tauri-apps/api/core";
import type { LauncherConfig, LauncherStatus } from "./types";

export async function getConfig(): Promise<LauncherConfig> {
  return invoke<LauncherConfig>("get_config");
}

export async function saveConfig(config: LauncherConfig): Promise<LauncherConfig> {
  return invoke<LauncherConfig>("save_config", { config });
}

export async function getStatus(): Promise<LauncherStatus> {
  return invoke<LauncherStatus>("get_status");
}
```

Create `launcher/src/App.tsx`:

```tsx
import { useEffect, useState } from "react";
import { getConfig, getStatus } from "./api";
import type { LauncherConfig, LauncherStatus } from "./types";

const fallbackStatus: LauncherStatus = {
  state: "stopped",
  apiUrl: "http://127.0.0.1:8000",
  webUrl: "http://127.0.0.1:5173",
  message: "尚未启动",
};

export function App() {
  const [config, setConfig] = useState<LauncherConfig | null>(null);
  const [status, setStatus] = useState<LauncherStatus>(fallbackStatus);

  useEffect(() => {
    let cancelled = false;
    void Promise.all([getConfig(), getStatus()])
      .then(([loadedConfig, loadedStatus]) => {
        if (cancelled) return;
        setConfig(loadedConfig);
        setStatus(loadedStatus);
      })
      .catch(() => {
        if (cancelled) return;
        setStatus({ ...fallbackStatus, state: "failed", message: "无法读取启动器状态" });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main aria-label="Course Navigator Launcher">
      <header>
        <p>Course Navigator</p>
        <h1>本地学习工作台启动器</h1>
      </header>
      <section aria-label="运行状态">
        <p>状态：{status.state}</p>
        <p>{status.message}</p>
        <p>网页：{status.webUrl}</p>
        <p>API：{status.apiUrl}</p>
      </section>
      <section aria-label="配置">
        <p>项目目录：{config?.projectRoot ?? "读取中"}</p>
        <p>Workspace：{config?.workspaceDir ?? "读取中"}</p>
      </section>
    </main>
  );
}
```

Create `launcher/src/main.tsx`:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

Create `launcher/src/App.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { App } from "./App";

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
}));

describe("App", () => {
  it("renders launcher status and configured paths", async () => {
    render(<App />);

    expect(await screen.findByText("状态：stopped")).toBeTruthy();
    expect(screen.getByText("项目目录：/tmp/course-navigator")).toBeTruthy();
    expect(screen.getByText("Workspace：/tmp/course-navigator/course-navigator-workspace")).toBeTruthy();
  });
});
```

- [ ] **Step 5: Add minimal Tauri Rust app**

Create `launcher/src-tauri/Cargo.toml`:

```toml
[package]
name = "course-navigator-launcher"
version = "0.1.0"
description = "Course Navigator Mac Launcher"
authors = ["Course Navigator"]
edition = "2021"

[lib]
name = "course_navigator_launcher_lib"
crate-type = ["staticlib", "cdylib", "rlib"]

[build-dependencies]
tauri-build = { version = "2", features = [] }

[dependencies]
serde = { version = "1", features = ["derive"] }
serde_json = "1"
tauri = { version = "2", features = [] }
thiserror = "2"
```

Create `launcher/src-tauri/build.rs`:

```rust
fn main() {
    tauri_build::build()
}
```

Create `launcher/src-tauri/tauri.conf.json`:

```json
{
  "$schema": "https://schema.tauri.app/config/2",
  "productName": "Course Navigator Launcher",
  "version": "0.1.0",
  "identifier": "com.course-navigator.launcher",
  "build": {
    "beforeDevCommand": "npm run dev",
    "devUrl": "http://127.0.0.1:1420",
    "beforeBuildCommand": "npm run build",
    "frontendDist": "../dist"
  },
  "app": {
    "windows": [
      {
        "title": "Course Navigator Launcher",
        "width": 760,
        "height": 640,
        "resizable": true
      }
    ]
  },
  "bundle": {
    "active": true,
    "targets": "app",
    "icon": []
  }
}
```

Create `launcher/src-tauri/capabilities/default.json`:

```json
{
  "$schema": "../gen/schemas/desktop-schema.json",
  "identifier": "default",
  "description": "Default launcher permissions",
  "windows": ["main"],
  "permissions": ["core:default"]
}
```

Create `launcher/src-tauri/src/main.rs`:

```rust
use serde::Serialize;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct LauncherConfig {
    project_root: String,
    api_host: String,
    api_port: u16,
    web_host: String,
    web_port: u16,
    workspace_dir: String,
    open_browser_on_start: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct LauncherStatus {
    state: String,
    api_url: String,
    web_url: String,
    message: String,
}

#[tauri::command]
fn get_config() -> LauncherConfig {
    let project_root = std::env::current_dir()
        .unwrap_or_else(|_| std::path::PathBuf::from("."))
        .display()
        .to_string();
    LauncherConfig {
        workspace_dir: format!("{project_root}/course-navigator-workspace"),
        project_root,
        api_host: "127.0.0.1".to_string(),
        api_port: 8000,
        web_host: "127.0.0.1".to_string(),
        web_port: 5173,
        open_browser_on_start: true,
    }
}

#[tauri::command]
fn save_config(config: LauncherConfig) -> LauncherConfig {
    config
}

#[tauri::command]
fn get_status() -> LauncherStatus {
    LauncherStatus {
        state: "stopped".to_string(),
        api_url: "http://127.0.0.1:8000".to_string(),
        web_url: "http://127.0.0.1:5173".to_string(),
        message: "尚未启动".to_string(),
    }
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![get_config, save_config, get_status])
        .run(tauri::generate_context!())
        .expect("failed to run Course Navigator Launcher");
}
```

- [ ] **Step 6: Install launcher dependencies**

Run:

```bash
npm install --prefix launcher
```

Expected: `launcher/package-lock.json` is created and dependencies install successfully.

- [ ] **Step 7: Run launcher frontend test**

Run:

```bash
npm run launcher:test
```

Expected: PASS.

- [ ] **Step 8: Run launcher web build**

Run:

```bash
npm run launcher:build:web
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add package.json launcher
git commit -m "feat: scaffold mac launcher"
```

## Task 3: Launcher Config And Env Writer

**Files:**
- Create: `launcher/src-tauri/src/models.rs`
- Create: `launcher/src-tauri/src/config.rs`
- Modify: `launcher/src-tauri/src/main.rs`
- Test: Rust unit tests in `launcher/src-tauri/src/config.rs`

- [ ] **Step 1: Write config tests**

Create `launcher/src-tauri/src/config.rs` with tests first:

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn env_update_preserves_secret_values_and_unknown_keys() {
        let input = "COURSE_NAVIGATOR_LLM_API_KEY=secret\nCUSTOM_FLAG=yes\nCOURSE_NAVIGATOR_WEB_PORT=5173\n";
        let config = LauncherConfig {
            project_root: "/app".into(),
            api_host: "127.0.0.1".into(),
            api_port: 8100,
            web_host: "127.0.0.1".into(),
            web_port: 5188,
            workspace_dir: "/Volumes/Learning/CourseWorkspace".into(),
            open_browser_on_start: true,
        };

        let updated = update_env_text(input, &config);

        assert!(updated.contains("COURSE_NAVIGATOR_LLM_API_KEY=secret\n"));
        assert!(updated.contains("CUSTOM_FLAG=yes\n"));
        assert!(updated.contains("COURSE_NAVIGATOR_API_PORT=8100\n"));
        assert!(updated.contains("COURSE_NAVIGATOR_WEB_PORT=5188\n"));
        assert!(updated.contains("COURSE_NAVIGATOR_WORKSPACE_DIR=/Volumes/Learning/CourseWorkspace\n"));
    }
}
```

- [ ] **Step 2: Run failing Rust test**

Run:

```bash
cd launcher/src-tauri && cargo test env_update_preserves_secret_values_and_unknown_keys
```

Expected: FAIL because `LauncherConfig` and `update_env_text` are not implemented.

- [ ] **Step 3: Move DTOs into models**

Create `launcher/src-tauri/src/models.rs`:

```rust
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LauncherConfig {
    pub project_root: String,
    pub api_host: String,
    pub api_port: u16,
    pub web_host: String,
    pub web_port: u16,
    pub workspace_dir: String,
    pub open_browser_on_start: bool,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LauncherStatus {
    pub state: String,
    pub api_url: String,
    pub web_url: String,
    pub message: String,
}
```

- [ ] **Step 4: Implement env text update**

Replace `launcher/src-tauri/src/config.rs` with:

```rust
use std::collections::BTreeMap;

use crate::models::LauncherConfig;

const MANAGED_KEYS: &[&str] = &[
    "COURSE_NAVIGATOR_API_HOST",
    "COURSE_NAVIGATOR_API_PORT",
    "COURSE_NAVIGATOR_WEB_HOST",
    "COURSE_NAVIGATOR_WEB_PORT",
    "COURSE_NAVIGATOR_WORKSPACE_DIR",
];

pub fn update_env_text(input: &str, config: &LauncherConfig) -> String {
    let updates = managed_values(config);
    let mut seen = BTreeMap::new();
    let mut lines = Vec::new();

    for line in input.lines() {
        let Some((key, _)) = line.split_once('=') else {
            lines.push(line.to_string());
            continue;
        };
        if let Some(value) = updates.get(key) {
            lines.push(format!("{key}={value}"));
            seen.insert(key.to_string(), true);
        } else {
            lines.push(line.to_string());
        }
    }

    for key in MANAGED_KEYS {
        if !seen.contains_key(*key) {
            if let Some(value) = updates.get(*key) {
                lines.push(format!("{key}={value}"));
            }
        }
    }

    format!("{}\n", lines.join("\n"))
}

fn managed_values(config: &LauncherConfig) -> BTreeMap<&'static str, String> {
    BTreeMap::from([
        ("COURSE_NAVIGATOR_API_HOST", config.api_host.clone()),
        ("COURSE_NAVIGATOR_API_PORT", config.api_port.to_string()),
        ("COURSE_NAVIGATOR_WEB_HOST", config.web_host.clone()),
        ("COURSE_NAVIGATOR_WEB_PORT", config.web_port.to_string()),
        ("COURSE_NAVIGATOR_WORKSPACE_DIR", config.workspace_dir.clone()),
    ])
}
```

- [ ] **Step 5: Wire modules in main**

Update `launcher/src-tauri/src/main.rs` imports and command types:

```rust
mod config;
mod models;

use models::{LauncherConfig, LauncherStatus};
```

Remove the local struct definitions from `main.rs`.

- [ ] **Step 6: Run Rust config test**

Run:

```bash
cd launcher/src-tauri && cargo test env_update_preserves_secret_values_and_unknown_keys
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add launcher/src-tauri/src
git commit -m "feat: add launcher config writer"
```

## Task 4: Project Runtime Service Manager

**Files:**
- Create: `launcher/src-tauri/src/runtime.rs`
- Create: `launcher/src-tauri/src/health.rs`
- Modify: `launcher/src-tauri/src/main.rs`
- Modify: `launcher/src/types.ts`
- Modify: `launcher/src/api.ts`
- Modify: `launcher/src/App.tsx`
- Modify: `launcher/src/App.test.tsx`

- [ ] **Step 1: Write runtime command construction tests**

Create `launcher/src-tauri/src/runtime.rs`:

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::LauncherConfig;

    fn config() -> LauncherConfig {
        LauncherConfig {
            project_root: "/repo".into(),
            api_host: "127.0.0.1".into(),
            api_port: 8100,
            web_host: "127.0.0.1".into(),
            web_port: 5188,
            workspace_dir: "/repo/course-navigator-workspace".into(),
            open_browser_on_start: true,
        }
    }

    #[test]
    fn api_command_uses_configured_port() {
        let command = api_command(&config());
        assert_eq!(command.program, "uv");
        assert!(command.args.contains(&"8100".to_string()));
    }

    #[test]
    fn web_command_uses_configured_port() {
        let command = web_command(&config());
        assert_eq!(command.program, "npm");
        assert!(command.args.contains(&"5188".to_string()));
    }
}
```

- [ ] **Step 2: Run failing runtime tests**

Run:

```bash
cd launcher/src-tauri && cargo test command_uses_configured_port
```

Expected: FAIL because command helpers are not implemented.

- [ ] **Step 3: Implement command helpers and dependency check**

Replace `launcher/src-tauri/src/runtime.rs` with:

```rust
use std::process::Command;

use serde::Serialize;

use crate::models::LauncherConfig;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RuntimeCommand {
    pub program: String,
    pub args: Vec<String>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DependencyStatus {
    pub name: String,
    pub available: bool,
    pub purpose: String,
}

pub fn api_command(config: &LauncherConfig) -> RuntimeCommand {
    RuntimeCommand {
        program: "uv".into(),
        args: vec![
            "run".into(),
            "uvicorn".into(),
            "course_navigator.app:app".into(),
            "--app-dir".into(),
            "backend".into(),
            "--host".into(),
            config.api_host.clone(),
            "--port".into(),
            config.api_port.to_string(),
        ],
    }
}

pub fn web_command(config: &LauncherConfig) -> RuntimeCommand {
    RuntimeCommand {
        program: "npm".into(),
        args: vec![
            "run".into(),
            "dev".into(),
            "--".into(),
            "--host".into(),
            config.web_host.clone(),
            "--port".into(),
            config.web_port.to_string(),
        ],
    }
}

pub fn check_dependencies() -> Vec<DependencyStatus> {
    [
        ("node", "运行前端开发服务"),
        ("npm", "安装和启动前端依赖"),
        ("uv", "安装和启动 Python 后端"),
        ("ffmpeg", "本地视频缓存、音频提取和媒体转换"),
        ("yt-dlp", "在线课程字幕提取和视频缓存"),
    ]
    .into_iter()
    .map(|(name, purpose)| DependencyStatus {
        name: name.into(),
        available: command_exists(name),
        purpose: purpose.into(),
    })
    .collect()
}

fn command_exists(name: &str) -> bool {
    Command::new("sh")
        .arg("-lc")
        .arg(format!("command -v {name} >/dev/null 2>&1"))
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
}
```

- [ ] **Step 4: Add temporary start/stop command responses**

Wire Tauri commands in `main.rs` first with safe temporary responses:

```rust
#[tauri::command]
fn check_dependencies() -> Vec<runtime::DependencyStatus> {
    runtime::check_dependencies()
}

#[tauri::command]
fn start_services() -> LauncherStatus {
    LauncherStatus {
        state: "starting".to_string(),
        api_url: "http://127.0.0.1:8000".to_string(),
        web_url: "http://127.0.0.1:5173".to_string(),
        message: "启动命令已准备，进程管理将在下一步启用".to_string(),
    }
}

#[tauri::command]
fn stop_services() -> LauncherStatus {
    LauncherStatus {
        state: "stopped".to_string(),
        api_url: "http://127.0.0.1:8000".to_string(),
        web_url: "http://127.0.0.1:5173".to_string(),
        message: "服务已停止".to_string(),
    }
}
```

Register them in `generate_handler!`.

- [ ] **Step 5: Update frontend API and UI buttons**

Add to `launcher/src/api.ts`:

```ts
export async function startServices(): Promise<LauncherStatus> {
  return invoke<LauncherStatus>("start_services");
}

export async function stopServices(): Promise<LauncherStatus> {
  return invoke<LauncherStatus>("stop_services");
}
```

Add buttons in `launcher/src/App.tsx`:

```tsx
<section aria-label="服务操作">
  <button type="button" onClick={() => void startServices().then(setStatus)}>
    启动
  </button>
  <button type="button" onClick={() => void stopServices().then(setStatus)}>
    停止
  </button>
</section>
```

- [ ] **Step 6: Update frontend test**

Extend `launcher/src/App.test.tsx` mock:

```tsx
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
```

- [ ] **Step 7: Run tests**

Run:

```bash
cd launcher/src-tauri && cargo test command_uses_configured_port
npm run launcher:test
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add launcher
git commit -m "feat: add launcher runtime commands"
```

## Task 5: Real Process Lifecycle And Browser Open

**Files:**
- Modify: `launcher/src-tauri/src/runtime.rs`
- Modify: `launcher/src-tauri/src/main.rs`
- Modify: `launcher/src-tauri/Cargo.toml`

- [ ] **Step 1: Add shared app state**

Update `runtime.rs` with:

```rust
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

pub struct ServiceState {
    api: Mutex<Option<Child>>,
    web: Mutex<Option<Child>>,
}

impl ServiceState {
    pub fn new() -> Self {
        Self {
            api: Mutex::new(None),
            web: Mutex::new(None),
        }
    }
}
```

- [ ] **Step 2: Implement start and stop**

Add to `runtime.rs`:

```rust
pub fn start_project_services(state: &ServiceState, config: &LauncherConfig) -> Result<(), String> {
    let api = api_command(config);
    let web = web_command(config);
    let project_root = std::path::Path::new(&config.project_root);

    let api_child = Command::new(&api.program)
        .args(&api.args)
        .current_dir(project_root)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|error| format!("API 启动失败: {error}"))?;

    let web_child = Command::new(&web.program)
        .args(&web.args)
        .current_dir(project_root)
        .env("COURSE_NAVIGATOR_API_HOST", &config.api_host)
        .env("COURSE_NAVIGATOR_API_PORT", config.api_port.to_string())
        .env("COURSE_NAVIGATOR_WEB_HOST", &config.web_host)
        .env("COURSE_NAVIGATOR_WEB_PORT", config.web_port.to_string())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|error| {
            let _ = stop_child(api_child);
            format!("Web 启动失败: {error}")
        })?;

    *state.api.lock().map_err(|_| "API 状态锁失效".to_string())? = Some(api_child);
    *state.web.lock().map_err(|_| "Web 状态锁失效".to_string())? = Some(web_child);
    Ok(())
}

pub fn stop_project_services(state: &ServiceState) -> Result<(), String> {
    if let Some(child) = state.api.lock().map_err(|_| "API 状态锁失效".to_string())?.take() {
        stop_child(child)?;
    }
    if let Some(child) = state.web.lock().map_err(|_| "Web 状态锁失效".to_string())?.take() {
        stop_child(child)?;
    }
    Ok(())
}

fn stop_child(mut child: Child) -> Result<(), String> {
    child.kill().map_err(|error| format!("停止服务失败: {error}"))?;
    let _ = child.wait();
    Ok(())
}
```

- [ ] **Step 3: Add opener dependency**

Update `launcher/src-tauri/Cargo.toml`:

```toml
open = "5"
```

- [ ] **Step 4: Wire real commands**

Update `main.rs` to manage `runtime::ServiceState`:

```rust
.manage(runtime::ServiceState::new())
```

Update commands:

```rust
#[tauri::command]
fn start_services(state: tauri::State<'_, runtime::ServiceState>) -> LauncherStatus {
    let config = get_config();
    match runtime::start_project_services(&state, &config) {
        Ok(()) => {
            let web_url = format!("http://{}:{}", config.web_host, config.web_port);
            if config.open_browser_on_start {
                let _ = open::that(&web_url);
            }
            LauncherStatus {
                state: "running".to_string(),
                api_url: format!("http://{}:{}", config.api_host, config.api_port),
                web_url,
                message: "服务已启动".to_string(),
            }
        }
        Err(error) => LauncherStatus {
            state: "failed".to_string(),
            api_url: format!("http://{}:{}", config.api_host, config.api_port),
            web_url: format!("http://{}:{}", config.web_host, config.web_port),
            message: error,
        },
    }
}
```

Update `stop_services` to call `runtime::stop_project_services`.

- [ ] **Step 5: Ensure cleanup on app exit**

Add a close event handler in `main.rs`:

```rust
.on_window_event(|window, event| {
    if let tauri::WindowEvent::CloseRequested { .. } = event {
        if let Some(state) = window.try_state::<runtime::ServiceState>() {
            let _ = runtime::stop_project_services(&state);
        }
    }
})
```

- [ ] **Step 6: Run launcher checks**

Run:

```bash
cd launcher/src-tauri && cargo test
npm run launcher:test
```

Expected: PASS.

- [ ] **Step 7: Manual smoke test**

Run:

```bash
npm run launcher:dev
```

Expected: The launcher opens, clicking 启动 starts the project services and opens `http://127.0.0.1:5173`; clicking 停止 releases both services.

- [ ] **Step 8: Commit**

```bash
git add launcher
git commit -m "feat: manage launcher service lifecycle"
```

## Task 6: Workspace Selection And Migration Foundation

**Files:**
- Create: `launcher/src-tauri/src/workspace.rs`
- Modify: `launcher/src-tauri/src/main.rs`
- Modify: `launcher/src/App.tsx`
- Modify: `launcher/src/api.ts`
- Modify: `launcher/src/types.ts`

- [ ] **Step 1: Write workspace plan test**

Create `launcher/src-tauri/src/workspace.rs`:

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn migration_plan_rejects_same_path() {
        let result = migration_plan("/tmp/workspace", "/tmp/workspace");
        assert!(result.is_err());
    }
}
```

- [ ] **Step 2: Run failing workspace test**

Run:

```bash
cd launcher/src-tauri && cargo test migration_plan_rejects_same_path
```

Expected: FAIL because `migration_plan` is not implemented.

- [ ] **Step 3: Implement migration plan helper**

Replace `workspace.rs` with:

```rust
use serde::Serialize;

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WorkspaceMigrationPlan {
    pub source: String,
    pub target: String,
    pub message: String,
}

pub fn migration_plan(source: &str, target: &str) -> Result<WorkspaceMigrationPlan, String> {
    let source_path = std::path::Path::new(source);
    let target_path = std::path::Path::new(target);
    if source_path == target_path {
        return Err("新 Workspace 位置和当前位置相同".into());
    }
    if !source_path.exists() {
        return Err("当前 Workspace 不存在，无法迁移".into());
    }
    Ok(WorkspaceMigrationPlan {
        source: source.into(),
        target: target.into(),
        message: "迁移前请先停止服务；旧 Workspace 会默认保留".into(),
    })
}
```

- [ ] **Step 4: Add Tauri command**

In `main.rs`:

```rust
mod workspace;

#[tauri::command]
fn plan_workspace_migration(source: String, target: String) -> Result<workspace::WorkspaceMigrationPlan, String> {
    workspace::migration_plan(&source, &target)
}
```

Register it in `generate_handler!`.

- [ ] **Step 5: Add frontend API**

Add to `launcher/src/types.ts`:

```ts
export type WorkspaceMigrationPlan = {
  source: string;
  target: string;
  message: string;
};
```

Add to `launcher/src/api.ts`:

```ts
export async function planWorkspaceMigration(source: string, target: string): Promise<WorkspaceMigrationPlan> {
  return invoke<WorkspaceMigrationPlan>("plan_workspace_migration", { source, target });
}
```

- [ ] **Step 6: Add basic UI for migration planning**

Add a Workspace section in `App.tsx` with a target path input and “检查迁移” button. The handler calls `planWorkspaceMigration(config.workspaceDir, target)` and renders the returned message.

- [ ] **Step 7: Run tests**

Run:

```bash
cd launcher/src-tauri && cargo test migration_plan_rejects_same_path
npm run launcher:test
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add launcher
git commit -m "feat: add workspace migration planning"
```

## Task 7: Full Verification

**Files:**
- No new files unless fixes are needed.

- [ ] **Step 1: Run backend tests touched by this work**

Run:

```bash
npm run test:backend -- backend/tests/test_app.py::test_create_app_allows_configured_web_origin
```

Expected: PASS.

- [ ] **Step 2: Run frontend app build**

Run:

```bash
npm run build
```

Expected: PASS with existing chunk-size warning allowed.

- [ ] **Step 3: Run launcher web tests**

Run:

```bash
npm run launcher:test
```

Expected: PASS.

- [ ] **Step 4: Run launcher Rust tests**

Run:

```bash
cd launcher/src-tauri && cargo test
```

Expected: PASS.

- [ ] **Step 5: Run whitespace check**

Run:

```bash
git diff --check
```

Expected: PASS.

- [ ] **Step 6: Manual launcher smoke test**

Run:

```bash
npm run launcher:dev
```

Expected: Launcher opens; start opens browser; stop releases services; closing launcher stops services it started.

- [ ] **Step 7: Final commit if verification required fixes**

```bash
git add <changed-files>
git commit -m "fix: stabilize mac launcher"
```
