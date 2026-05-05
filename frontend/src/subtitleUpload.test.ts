import { describe, expect, it } from "vitest";

import { parseUploadedSubtitleText } from "./subtitleUpload";

describe("parseUploadedSubtitleText", () => {
  it("parses SRT cues", () => {
    const transcript = parseUploadedSubtitleText(
      "1\n00:00:01,000 --> 00:00:03,500\nHello world\n\n2\n00:00:04,000 --> 00:00:05,250\nSecond line",
      "lesson.srt",
      10,
    );

    expect(transcript).toEqual([
      { start: 1, end: 3.5, text: "Hello world" },
      { start: 4, end: 5.25, text: "Second line" },
    ]);
  });

  it("parses bracketed time ranges", () => {
    const transcript = parseUploadedSubtitleText("[00:01.000-00:03.000] Hello\n[00:04.000 - 00:06.000] World", "lesson.txt");

    expect(transcript).toEqual([
      { start: 1, end: 3, text: "Hello" },
      { start: 4, end: 6, text: "World" },
    ]);
  });

  it("fills missing end times from the next timestamp", () => {
    const transcript = parseUploadedSubtitleText("[00:01.00] first\n[00:04.00] second", "lesson.lrc", 8);

    expect(transcript[0]).toEqual({ start: 1, end: 4, text: "first" });
    expect(transcript[1]?.start).toBe(4);
    expect(transcript[1]?.end).toBeGreaterThan(4);
    expect(transcript[1]?.text).toBe("second");
  });

  it("turns plain TXT or Markdown lines into evenly timed subtitles", () => {
    const transcript = parseUploadedSubtitleText("# Title\n\n- First idea\nSecond idea", "lesson.md", 30);

    expect(transcript).toEqual([
      { start: 0, end: 10, text: "Title" },
      { start: 10, end: 20, text: "First idea" },
      { start: 20, end: 30, text: "Second idea" },
    ]);
  });

  it("supports common leading timestamp lines", () => {
    const transcript = parseUploadedSubtitleText("00:01 Hello\n00:03 - 00:05 explicit", "lesson.txt");

    expect(transcript).toEqual([
      { start: 1, end: 3, text: "Hello" },
      { start: 3, end: 5, text: "explicit" },
    ]);
  });

  it("parses ASS dialogue lines", () => {
    const transcript = parseUploadedSubtitleText(
      "Dialogue: 0,0:00:01.23,0:00:04.56,Default,,0,0,0,,Hello\\Nworld",
      "lesson.ass",
    );

    expect(transcript).toEqual([{ start: 1.23, end: 4.56, text: "Hello world" }]);
  });
});
