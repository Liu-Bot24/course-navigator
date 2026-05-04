import { describe, expect, it } from "vitest";

import { buildWebVttTrack, formatTime, getBilibiliVideoId, getYouTubeVideoId } from "./utils";

describe("formatTime", () => {
  it("formats seconds as mm:ss", () => {
    expect(formatTime(75)).toBe("01:15");
  });

  it("formats long durations as hh:mm:ss", () => {
    expect(formatTime(3670)).toBe("01:01:10");
  });
});

describe("getYouTubeVideoId", () => {
  it("extracts id from watch url", () => {
    expect(getYouTubeVideoId("https://www.youtube.com/watch?v=JPcx9qHzzgk&t=13s")).toBe(
      "JPcx9qHzzgk",
    );
  });

  it("extracts id from short url", () => {
    expect(getYouTubeVideoId("https://youtu.be/JPcx9qHzzgk")).toBe("JPcx9qHzzgk");
  });
});

describe("getBilibiliVideoId", () => {
  it("extracts bvid from a Bilibili video url", () => {
    expect(
      getBilibiliVideoId(
        "https://www.bilibili.com/video/BV1iVoVBgERD/?spm_id_from=333.337.search-card.all.click",
      ),
    ).toBe("BV1iVoVBgERD");
  });
});

describe("buildWebVttTrack", () => {
  it("builds a native subtitle track from transcript segments", () => {
    expect(
      buildWebVttTrack([
        { start: 1.2, end: 3.4, text: "Hello\nworld" },
        { start: 3661, end: 3664.5, text: "Long line" },
      ]),
    ).toContain("00:00:01.200 --> 00:00:03.400\nHello world");
    expect(
      buildWebVttTrack([
        { start: 1.2, end: 3.4, text: "Hello\nworld" },
        { start: 3661, end: 3664.5, text: "Long line" },
      ]),
    ).toContain("01:01:01.000 --> 01:01:04.500\nLong line");
  });

  it("keeps cue end after the cue start even when source end is missing", () => {
    expect(buildWebVttTrack([{ start: 5, end: 5, text: "Short" }])).toContain(
      "00:00:05.000 --> 00:00:05.800",
    );
  });
});
