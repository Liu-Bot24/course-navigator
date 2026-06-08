/// <reference types="vite/client" />

import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import rawConfig from "../src-tauri/tauri.conf.json";

type TauriWindowConfig = {
  label: string;
  width: number;
  height: number;
  minWidth: number;
  minHeight: number;
};

type TauriConfig = {
  productName: string;
  app: {
    windows: TauriWindowConfig[];
  };
  bundle: {
    targets?: string | string[];
    category?: string;
    icon: string[];
    resources?: Record<string, string>;
    windows?: {
      nsis?: {
        installerIcon?: string;
        uninstallerIcon?: string;
        installerHooks?: string;
        languages?: string[];
        displayLanguageSelector?: boolean;
      };
    };
  };
};

const config = rawConfig as TauriConfig;
const testDir = dirname(fileURLToPath(import.meta.url));

describe("Tauri app shell", () => {
  it("uses the native menu bar tray instead of a custom tray WebView window", () => {
    expect(config.app.windows.map((windowConfig) => windowConfig.label)).toEqual(["main"]);
  });

  it("ships as Course Navigator with the product icon assets", () => {
    expect(config.productName).toBe("Course Navigator");
    expect(config.bundle.category).toBe("Education");
    expect(config.bundle.icon).toEqual(["icons/icon.icns", "icons/icon.png", "icons/icon.ico"]);
    expect(config.bundle.windows?.nsis?.installerIcon).toBe("icons/icon.ico");
    expect(config.bundle.windows?.nsis?.uninstallerIcon).toBe("icons/icon.ico");
    expect(config.bundle.windows?.nsis?.installerHooks).toBe("windows/installer-hooks.nsh");
  });

  it("always shows the Windows installer language selector for Chinese or English", async () => {
    const hooks = await readFile(resolve(testDir, "../src-tauri/windows/installer-hooks.nsh"), "utf-8");

    expect(config.bundle.windows?.nsis?.languages).toEqual(["English", "SimpChinese", "TradChinese"]);
    expect(config.bundle.windows?.nsis?.displayLanguageSelector).toBe(true);
    expect(hooks).toContain("MUI_LANGDLL_ALWAYSSHOW");
  });

  it("uses the macOS template tray icon only on macOS and the product icon elsewhere", async () => {
    const libSource = await import("../src-tauri/src/lib.rs?raw").then((module) => module.default as string);

    expect(libSource).toContain("platform_tray_icon()");
    expect(libSource).toContain('icon_as_template(cfg!(target_os = "macos"))');
    expect(libSource).toContain('#[cfg(target_os = "macos")]');
    expect(libSource).toContain('include_bytes!("../icons/tray-book.png")');
    expect(libSource).toContain("#[cfg(not(target_os = \"macos\"))]");
    expect(libSource).toContain('include_bytes!("../icons/icon.png")');
  });

  it("stops only Course Navigator-owned Windows processes before overwriting bundled tools", async () => {
    const hooks = await readFile(resolve(testDir, "../src-tauri/windows/installer-hooks.nsh"), "utf-8");

    expect(hooks).toContain("NSIS_HOOK_PREINSTALL");
    expect(hooks).toContain("$INSTDIR");
    expect(hooks).toContain("LOCALAPPDATA");
    expect(hooks).toContain("APPDATA");
    expect(hooks).toContain("Course Navigator");
    expect(hooks).toContain("Win32_Process");
    expect(hooks).toContain("Stop-Process");
    expect(hooks).not.toContain("/IM node.exe");
    expect(hooks).not.toContain("/IM python.exe");
  });

  it("bundles the runtime source and Windows portable tools needed by direct distribution", () => {
    expect(config.bundle.resources).toEqual({
      "resources/runtime-source": "runtime-source",
      "resources/runtime-tools": "runtime-tools",
    });
  });

  it("declares the local Whisper runtime dependency used by local ASR", async () => {
    const pyproject = await readFile(resolve(testDir, "../../pyproject.toml"), "utf-8");

    expect(pyproject).toMatch(/"openai-whisper[>=<~!0-9., ]*"/);
  });

  it("uses a cross-platform runtime source preparation script for app bundles", async () => {
    const packageJson = JSON.parse(await readFile(resolve(testDir, "../package.json"), "utf-8"));

    expect(packageJson.scripts["prepare:runtime"]).toBe("node ../scripts/prepare-runtime-source.mjs");
    expect(packageJson.scripts["tauri:build:windows"]).toContain("tauri build --bundles nsis");
  });

  it("does not keep the deprecated mac-only runtime preparation entry point", async () => {
    await expect(readFile(resolve(testDir, "../../scripts/prepare-mac-runtime-source.sh"), "utf-8")).rejects.toMatchObject({
      code: "ENOENT",
    });
  });

  it("keeps Windows releases and spawned runtime commands from opening console windows", async () => {
    const mainSource = await import("../src-tauri/src/main.rs?raw").then((module) => module.default as string);
    const runtimeSource = await import("../src-tauri/src/runtime.rs?raw").then((module) => module.default as string);

    expect(mainSource).toContain('windows_subsystem = "windows"');
    expect(runtimeSource).toContain("CREATE_NO_WINDOW");
    expect(runtimeSource).toContain("creation_flags(CREATE_NO_WINDOW)");
    expect(runtimeSource).toContain("hidden_command(&command.program)");
  });

  it("bundles Windows runtime tools without a standalone yt-dlp executable", async () => {
    const prepareScript = await readFile(resolve(testDir, "../../scripts/prepare-runtime-source.mjs"), "utf-8");
    const runtimeSource = await import("../src-tauri/src/runtime.rs?raw").then((module) => module.default as string);

    expect(prepareScript).toContain("runtime-tools");
    expect(prepareScript).toContain("nodejs.org/dist");
    expect(prepareScript).toContain("uv-x86_64-pc-windows-msvc");
    expect(prepareScript).not.toContain("yt-dlp.exe");
    expect(prepareScript).toContain("ffmpeg-release-essentials");
    expect(prepareScript).toContain("COURSE_NAVIGATOR_WINDOWS_FFMPEG_ARCHIVE");
    expect(prepareScript).toContain("ffprobe.exe");
    expect(prepareScript).not.toContain("Expand-Archive");
    expect(runtimeSource).toContain("bundled_tool_program");
    expect(runtimeSource).toContain("runtime-tools");
    expect(runtimeSource).toContain("prepend_bundled_tool_paths");
    expect(runtimeSource).not.toContain('"ytdlp"');
    expect(runtimeSource).toContain('"ffmpeg"');
  });

  it("passes bundled runtime tool paths to spawned backend processes", async () => {
    const runtimeSource = await import("../src-tauri/src/runtime.rs?raw").then((module) => module.default as string);

    expect(runtimeSource).toContain('const RUNTIME_TOOL_PATHS_ENV: &str = "COURSE_NAVIGATOR_RUNTIME_TOOL_PATHS"');
    expect(runtimeSource).toContain("runtime_tool_paths_env_value()");
    expect(runtimeSource).toContain("command.env(RUNTIME_TOOL_PATHS_ENV, tool_paths)");
  });

  it("bundles macOS runtime tools for direct DMG installs", async () => {
    const prepareScript = await readFile(resolve(testDir, "../../scripts/prepare-runtime-source.mjs"), "utf-8");
    const runtimeSource = await import("../src-tauri/src/runtime.rs?raw").then((module) => module.default as string);

    expect(prepareScript).toContain("prepareMacRuntimeTools");
    expect(prepareScript).toContain("pruneMacNodeRuntime");
    expect(prepareScript).toContain("writeMacNodeCliWrappers");
    expect(prepareScript).toContain("node-${nodeVersion}-darwin-${arch}.tar.gz");
    expect(prepareScript).toContain("uv-aarch64-apple-darwin.tar.gz");
    expect(prepareScript).toContain("ffmpeg-ffprobe-static");
    const wrapperFunction = prepareScript.slice(
      prepareScript.indexOf("async function writeMacNodeCliWrappers"),
      prepareScript.indexOf("async function copyExecutable"),
    );
    expect(wrapperFunction).toContain("await fs.rm(target, { force: true });");
    expect(wrapperFunction.indexOf("await fs.rm(target")).toBeLessThan(wrapperFunction.indexOf("await fs.writeFile(target"));
    expect(runtimeSource).toContain("darwin-arm64");
    expect(runtimeSource).toContain("Contents");
    expect(runtimeSource).toContain("Resources");
  });

  it("pins portable runtime tool versions instead of resolving moving latest releases", async () => {
    const prepareScript = await readFile(resolve(testDir, "../../scripts/prepare-runtime-source.mjs"), "utf-8");

    expect(prepareScript).toContain('const DEFAULT_NODE_VERSION = "v24.16.0"');
    expect(prepareScript).toContain('const DEFAULT_UV_VERSION = "0.11.19"');
    expect(prepareScript).toContain("COURSE_NAVIGATOR_WINDOWS_NODE_VERSION || DEFAULT_NODE_VERSION");
    expect(prepareScript).toContain("COURSE_NAVIGATOR_MAC_NODE_VERSION || DEFAULT_NODE_VERSION");
    expect(prepareScript).toContain("releases/download/${uvVersion}");
    expect(prepareScript).not.toContain("releases/latest/download");
    expect(prepareScript).not.toContain("latestNodeLtsVersion");
  });

  it("sizes the macOS DMG from the built app instead of a fixed capacity", async () => {
    const dmgScript = await readFile(resolve(testDir, "../../scripts/build-mac-dmg.sh"), "utf-8");

    expect(dmgScript).toContain('du -sk "$APP_PATH"');
    expect(dmgScript).toContain("DMG_SIZE_MB");
    expect(dmgScript).toContain('-size "${DMG_SIZE_MB}m"');
    expect(dmgScript).not.toContain("-size 160m");
  });

  it("removes local packaging metadata before signing the macOS app", async () => {
    const dmgScript = await readFile(resolve(testDir, "../../scripts/build-mac-dmg.sh"), "utf-8");
    const cleanupIndex = dmgScript.indexOf('remove_packaging_junk "$APP_PATH/Contents/Resources"');
    const codesignIndex = dmgScript.indexOf("codesign --force --deep --sign");

    expect(dmgScript).toContain("remove_packaging_junk()");
    expect(dmgScript).toContain('-name ".DS_Store"');
    expect(dmgScript).toContain('-name "._*"');
    expect(dmgScript).toContain('-name "*.swp"');
    expect(cleanupIndex).toBeGreaterThanOrEqual(0);
    expect(codesignIndex).toBeGreaterThan(cleanupIndex);
  });

  it("does not force Homebrew formula dependencies for the self-contained macOS app", async () => {
    const cask = await readFile(resolve(testDir, "../../Casks/course-navigator.rb"), "utf-8");

    expect(cask).toContain("depends_on arch: :arm64");
    expect(cask).not.toContain('depends_on formula: "node"');
    expect(cask).not.toContain('depends_on formula: "python@3.11"');
    expect(cask).not.toContain('depends_on formula: "uv"');
    expect(cask).not.toContain('depends_on formula: "ffmpeg"');
  });

  it("keeps local collaboration notes out of packaged runtime source", async () => {
    const prepareScript = await readFile(resolve(testDir, "../../scripts/prepare-runtime-source.mjs"), "utf-8");

    expect(prepareScript).toContain('"DEVELOPMENT_LOG.md"');
    expect(prepareScript).toContain('".internal-docs"');
    expect(prepareScript).toContain('"output"');
    expect(prepareScript).toContain("isLocalPackagingJunk");
    expect(prepareScript).toContain('name === ".DS_Store"');
    expect(prepareScript).toContain('name.startsWith("._")');
    expect(prepareScript).toContain('name.endsWith(".swp")');
    expect(prepareScript).toContain("purgeLocalPackagingJunk(resourceDir)");
  });

  it("uses a compact default main window that can fit the full launcher", () => {
    expect(config.app.windows[0]).toMatchObject({
      label: "main",
      width: 1000,
      height: 800,
      minWidth: 900,
      minHeight: 740,
    });
  });

  it("forces the initial main window size so stale restored dimensions do not keep scrollbars", async () => {
    const libSource = await import("../src-tauri/src/lib.rs?raw").then((module) => module.default as string);

    expect(libSource).toContain("configure_main_window(app.handle())");
    expect(libSource).toContain("MAIN_WINDOW_HEIGHT: f64 = 800.0");
    expect(libSource).toContain("window.set_size");
  });

  it("keeps the menu bar entry concise", async () => {
    const libSource = await import("../src-tauri/src/lib.rs?raw").then((module) => module.default as string);

    expect(libSource).toContain('"打开网页"');
    expect(libSource).not.toContain('"打开工作台"');
    expect(libSource).not.toContain('MenuItem::with_id(app, "workspace"');
  });

  it("does not open the browser from the tray when service startup fails", async () => {
    const libSource = await import("../src-tauri/src/lib.rs?raw").then((module) => module.default as string);

    const startHelperStart = libSource.indexOf("fn start_services_from_app");
    const startHelperEnd = libSource.indexOf("#[tauri::command]", startHelperStart);
    const startHelper = libSource.slice(startHelperStart, startHelperEnd);
    expect(startHelper).toContain("match runtime::start_project_services");
    expect(startHelper).toContain("Ok(()) =>");
    expect(startHelper).toContain("if config.open_browser_on_start");
    expect(libSource).not.toContain("let _ = runtime::start_project_services(state.inner(), &config);");
  });

  it("does not swallow tray stop results", async () => {
    const libSource = await import("../src-tauri/src/lib.rs?raw").then((module) => module.default as string);
    const stopHandlerStart = libSource.indexOf('"stop" => {');
    const stopHandlerEnd = libSource.indexOf('"quit" => {', stopHandlerStart);
    const stopHandler = libSource.slice(stopHandlerStart, stopHandlerEnd);

    expect(stopHandler).toContain("stop_services_from_app(app, state.inner())");
    expect(stopHandler).toContain("emit_launcher_status");
    expect(stopHandler).not.toContain("let _ = runtime::stop_configured_services");
  });

  it("keeps ASR correction under LLM models and online ASR as a direct ASR menu", async () => {
    const libSource = await import("../src-tauri/src/lib.rs?raw").then((module) => module.default as string);
    const llmMenuIndex = libSource.indexOf('let llm = Submenu::with_id(app, "models_llm"');
    const asrCorrectionIndex = libSource.indexOf('"ASR 校正模型"');
    const asrMenuIndex = libSource.indexOf('let asr = Submenu::with_id(app, "models_asr"');

    expect(llmMenuIndex).toBeGreaterThanOrEqual(0);
    expect(asrCorrectionIndex).toBeGreaterThan(llmMenuIndex);
    expect(asrCorrectionIndex).toBeLessThan(asrMenuIndex);
    expect(libSource).not.toContain("models_online_asr");
    expect(libSource).not.toContain('"在线 ASR 模型"');
  });

  it("keeps the launcher as a regular Dock app while reopening hidden windows from the Dock", async () => {
    const libSource = await import("../src-tauri/src/lib.rs?raw").then((module) => module.default as string);

    expect(libSource).toContain("ActivationPolicy::Regular");
    expect(libSource).not.toContain("ActivationPolicy::Accessory");
    expect(libSource).toContain("RunEvent::Reopen");
    expect(libSource).toContain("show_main_window(app)");
  });
});
