import { describe, expect, it } from "vitest";

import { apiPath, itemVideoPath } from "./api";

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
