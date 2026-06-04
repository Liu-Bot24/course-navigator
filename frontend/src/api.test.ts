import { afterEach, describe, expect, it, vi } from "vitest";

import {
  apiPath,
  bindVideoSource,
  bindVideoSourceFromPicker,
  importLocalVideosFromPicker,
  importWorkspaceVideoFromPicker,
  itemVideoPath,
} from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("apiPath", () => {
  it("prefixes backend API routes", () => {
    expect(apiPath("/items")).toBe("/api/items");
  });

  it("does not double-prefix an API route", () => {
    expect(apiPath("/api/items")).toBe("/api/items");
  });
});

describe("itemVideoPath", () => {
  it("returns the local video API route", () => {
    expect(itemVideoPath("abc123")).toBe("/api/items/abc123/video");
  });
});

describe("importLocalVideosFromPicker", () => {
  it("posts the Finder picker import mode", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [],
    });
    vi.stubGlobal("fetch", fetchMock);

    await importLocalVideosFromPicker("external");

    expect(fetchMock).toHaveBeenCalledWith("/api/local-video-file-picker", {
      headers: { "Content-Type": "application/json" },
      method: "POST",
      body: JSON.stringify({ mode: "external" }),
    });
  });
});

describe("bindVideoSource", () => {
  it("posts a remote video source binding", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "abc123" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await bindVideoSource("abc123", { source_type: "remote", url: "https://example.com/video" });

    expect(fetchMock).toHaveBeenCalledWith("/api/items/abc123/video-source", {
      headers: { "Content-Type": "application/json" },
      method: "POST",
      body: JSON.stringify({ source_type: "remote", url: "https://example.com/video" }),
    });
  });
});

describe("bindVideoSourceFromPicker", () => {
  it("posts the current item Finder binding request", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "abc123" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await bindVideoSourceFromPicker("abc123");

    expect(fetchMock).toHaveBeenCalledWith("/api/items/abc123/video-source-picker", {
      headers: { "Content-Type": "application/json" },
      method: "POST",
    });
  });
});

describe("importWorkspaceVideoFromPicker", () => {
  it("posts the current item Workspace import picker request", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "abc123" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await importWorkspaceVideoFromPicker("abc123");

    expect(fetchMock).toHaveBeenCalledWith("/api/items/abc123/workspace-video-picker", {
      headers: { "Content-Type": "application/json" },
      method: "POST",
    });
  });
});
