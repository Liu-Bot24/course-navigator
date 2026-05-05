import type { TranscriptSegment } from "./types";

type PartialSegment = {
  start: number;
  end: number | null;
  text: string;
};

const TIMECODE_SOURCE = String.raw`(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[,.]\d{1,3})?`;
const TIMECODE_RANGE_RE = new RegExp(
  String.raw`^[\[(（【]?\s*(${TIMECODE_SOURCE})\s*(?:-->|-|–|—|~|至|到)\s*(${TIMECODE_SOURCE})\s*[\])）】]?\s*(.*)$`,
);
const TIMECODE_LEADING_RE = new RegExp(String.raw`^[\[(（【]?\s*(${TIMECODE_SOURCE})\s*[\])）】]?\s*[:：]?\s+(.+)$`);

export function parseUploadedSubtitleText(raw: string, filename: string, durationSeconds?: number | null): TranscriptSegment[] {
  const cleaned = raw.replace(/^\uFEFF/, "").replace(/\r\n?/g, "\n").trim();
  if (!cleaned) return [];

  const timedBlocks = parseCueBlocks(cleaned);
  if (timedBlocks.length) {
    return normalizeSegments(timedBlocks, durationSeconds);
  }

  const timedLines = parseTimedLines(cleaned);
  if (timedLines.length) {
    return normalizeSegments(timedLines, durationSeconds);
  }

  return buildPlainTextTranscript(cleaned, filename, durationSeconds);
}

function parseCueBlocks(raw: string): PartialSegment[] {
  if (!raw.includes("-->")) return [];
  const blocks = raw.split(/\n{2,}/);
  const segments: PartialSegment[] = [];

  for (const block of blocks) {
    const lines = block
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    const timeLineIndex = lines.findIndex((line) => line.includes("-->"));
    if (timeLineIndex < 0) continue;

    const [startPart, endPart = ""] = lines[timeLineIndex].split(/\s+-->\s+/);
    const start = parseTimecode(startPart);
    const end = parseTimecode(endPart.split(/\s+/)[0] ?? "");
    if (start === null || end === null) continue;

    const text = lines
      .slice(timeLineIndex + 1)
      .map(normalizeSubtitleLine)
      .filter(Boolean)
      .join(" ");
    if (!text) continue;
    segments.push({ start, end, text });
  }

  return segments;
}

function parseTimedLines(raw: string): PartialSegment[] {
  const segments: PartialSegment[] = [];
  for (const sourceLine of raw.split("\n")) {
    const line = sourceLine.trim();
    if (!line || isSubtitleHeaderLine(line)) continue;

    const assSegment = parseAssDialogueLine(line);
    if (assSegment) {
      segments.push(assSegment);
      continue;
    }

    const rangeMatch = line.match(TIMECODE_RANGE_RE);
    if (rangeMatch) {
      const start = parseTimecode(rangeMatch[1] ?? "");
      const end = parseTimecode(rangeMatch[2] ?? "");
      const text = normalizeSubtitleLine(rangeMatch[3] ?? "");
      if (start !== null && end !== null && text) {
        segments.push({ start, end, text });
        continue;
      }
    }

    const leadingMatch = line.match(TIMECODE_LEADING_RE);
    if (leadingMatch) {
      const start = parseTimecode(leadingMatch[1] ?? "");
      const text = normalizeSubtitleLine(leadingMatch[2] ?? "");
      if (start !== null && text) {
        segments.push({ start, end: null, text });
      }
    }
  }

  return segments;
}

function buildPlainTextTranscript(raw: string, filename: string, durationSeconds?: number | null): TranscriptSegment[] {
  const lines = raw
    .split("\n")
    .map(normalizeSubtitleLine)
    .filter((line) => line && !isSubtitleHeaderLine(line));
  if (!lines.length) return [];

  const duration = typeof durationSeconds === "number" && durationSeconds > 0 ? durationSeconds : null;
  const step = duration ? duration / lines.length : 3;
  return lines.map((text, index) => {
    const start = roundSeconds(index * step);
    const end = duration && index === lines.length - 1 ? duration : roundSeconds((index + 1) * step);
    return {
      start,
      end: Math.max(end, roundSeconds(start + 0.8)),
      text: stripImportedFilenamePrefix(text, filename),
    };
  });
}

function normalizeSegments(segments: PartialSegment[], durationSeconds?: number | null): TranscriptSegment[] {
  const sorted = segments
    .filter((segment) => segment.text.trim())
    .sort((a, b) => a.start - b.start)
    .map((segment) => ({ ...segment, text: segment.text.trim() }));
  const duration = typeof durationSeconds === "number" && durationSeconds > 0 ? durationSeconds : null;
  const fallbackStep = duration ? Math.max(1, duration / Math.max(sorted.length, 1)) : 3;

  return sorted.map((segment, index) => {
    const nextStart = sorted[index + 1]?.start;
    const candidateEnd =
      segment.end && segment.end > segment.start
        ? segment.end
        : typeof nextStart === "number" && nextStart > segment.start
          ? nextStart
          : duration && duration > segment.start
            ? Math.min(duration, segment.start + fallbackStep)
            : segment.start + fallbackStep;
    return {
      start: roundSeconds(segment.start),
      end: roundSeconds(Math.max(candidateEnd, segment.start + 0.8)),
      text: segment.text,
    };
  });
}

function parseTimecode(value: string): number | null {
  const parts = value.trim().replace(",", ".").split(":");
  if (parts.length < 2 || parts.length > 3) return null;
  const numbers = parts.map(Number);
  if (numbers.some((part) => Number.isNaN(part))) return null;
  if (numbers.length === 2) {
    const [minutes, seconds] = numbers;
    return minutes * 60 + seconds;
  }
  const [hours, minutes, seconds] = numbers;
  return hours * 3600 + minutes * 60 + seconds;
}

function parseAssDialogueLine(line: string): PartialSegment | null {
  if (!line.toLowerCase().startsWith("dialogue:")) return null;
  const payload = line.slice(line.indexOf(":") + 1).trim();
  const parts = payload.split(",");
  if (parts.length < 10) return null;
  const start = parseTimecode(parts[1] ?? "");
  const end = parseTimecode(parts[2] ?? "");
  const text = normalizeSubtitleLine(parts.slice(9).join(","));
  if (start === null || end === null || !text) return null;
  return { start, end, text };
}

function normalizeSubtitleLine(line: string): string {
  return line
    .replace(/\{[^}]*\}/g, "")
    .replace(/\\[Nn]/g, " ")
    .replace(/<[^>]+>/g, "")
    .replace(/^#{1,6}\s+/, "")
    .replace(/^>\s+/, "")
    .replace(/^[-*+]\s+/, "")
    .replace(/^\d+[.)]\s+/, "")
    .trim();
}

function isSubtitleHeaderLine(line: string): boolean {
  return /^(WEBVTT|NOTE|STYLE|REGION)$/i.test(line.trim());
}

function stripImportedFilenamePrefix(text: string, filename: string): string {
  const basename = filename.replace(/\.[^.]+$/, "").trim();
  return basename && text.startsWith(`${basename}:`) ? text.slice(basename.length + 1).trim() : text;
}

function roundSeconds(value: number): number {
  return Math.max(0, Math.round(value * 1000) / 1000);
}
