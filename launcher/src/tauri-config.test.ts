/// <reference types="vite/client" />

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
    icon: string[];
  };
};

const config = rawConfig as TauriConfig;

describe("Tauri app shell", () => {
  it("uses the native menu bar tray instead of a custom tray WebView window", () => {
    expect(config.app.windows.map((windowConfig) => windowConfig.label)).toEqual(["main"]);
  });

  it("ships as Course Navigator with the product icon assets", () => {
    expect(config.productName).toBe("Course Navigator");
    expect(config.bundle.icon).toEqual(["icons/icon.icns", "icons/icon.png"]);
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
