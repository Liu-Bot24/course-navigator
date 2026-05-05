import type { AsrCorrectionSuggestion, TranscriptSegment } from "./types";

const EDITOR_LINE_RE = /^\[(?<start>[0-9:.]+)-(?<end>[0-9:.]+)\]\s*(?<text>.*)$/;

export function transcriptToEditorText(transcript: TranscriptSegment[]): string {
  return transcript
    .map((segment) => `[${formatEditorTime(segment.start)}-${formatEditorTime(segment.end)}] ${segment.text}`)
    .join("\n");
}

export function editorTextToTranscript(value: string): TranscriptSegment[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, index) => {
      const match = EDITOR_LINE_RE.exec(line);
      if (!match?.groups) {
        throw new Error(`第 ${index + 1} 行缺少时间戳`);
      }
      const start = editorTimeToSeconds(match.groups.start);
      const end = editorTimeToSeconds(match.groups.end);
      const text = match.groups.text.trim();
      if (!text) {
        throw new Error(`第 ${index + 1} 行字幕不能为空`);
      }
      if (end < start) {
        throw new Error(`第 ${index + 1} 行结束时间不能早于开始时间`);
      }
      return { start, end, text };
    });
}

export function applyAsrSuggestion(
  transcript: TranscriptSegment[],
  suggestion: AsrCorrectionSuggestion,
): TranscriptSegment[] {
  return transcript.map((segment, index) => {
    if (index !== suggestion.segment_index) return segment;
    return {
      ...segment,
      text: segment.text.replace(suggestion.original_text, suggestion.corrected_text),
    };
  });
}

export type AsrSuggestionContext = {
  originalLine: string;
  correctedLine: string;
  originalMatched: boolean;
  correctedMatched: boolean;
};

export type AsrEditorHighlightRange = {
  id: string;
  start: number;
  end: number;
  status: AsrCorrectionSuggestion["status"];
  variant: "original" | "corrected";
};

export function asrSuggestionContext(
  transcript: TranscriptSegment[],
  suggestion: AsrCorrectionSuggestion,
): AsrSuggestionContext {
  const segmentText = transcript[suggestion.segment_index]?.text || suggestion.original_text;
  const originalIndex = segmentText.indexOf(suggestion.original_text);
  const correctedLine =
    originalIndex >= 0
      ? `${segmentText.slice(0, originalIndex)}${suggestion.corrected_text}${segmentText.slice(
          originalIndex + suggestion.original_text.length,
        )}`
      : suggestion.corrected_text;
  return {
    originalLine: segmentText,
    correctedLine,
    originalMatched: originalIndex >= 0,
    correctedMatched: correctedLine.includes(suggestion.corrected_text),
  };
}

export function asrEditorHighlightRanges(
  editorText: string,
  suggestions: AsrCorrectionSuggestion[],
  variant: "original" | "corrected" = "original",
): AsrEditorHighlightRange[] {
  const bySegment = new Map<number, AsrCorrectionSuggestion[]>();
  for (const suggestion of suggestions) {
    if (suggestion.status !== "pending") continue;
    const current = bySegment.get(suggestion.segment_index) ?? [];
    current.push(suggestion);
    bySegment.set(suggestion.segment_index, current);
  }

  const ranges: AsrEditorHighlightRange[] = [];
  const parts = editorText.split(/(\r?\n)/);
  let offset = 0;
  let segmentIndex = 0;
  for (let index = 0; index < parts.length; index += 2) {
    const line = parts[index] ?? "";
    const separator = parts[index + 1] ?? "";
    if (line.trim()) {
      const lineTextStart = transcriptLineTextStart(line);
      if (lineTextStart >= 0) {
        for (const suggestion of bySegment.get(segmentIndex) ?? []) {
          const needle = variant === "original" ? suggestion.original_text : suggestion.corrected_text;
          const localStart = line.indexOf(needle, lineTextStart);
          if (localStart >= 0) {
            ranges.push({
              id: suggestion.id,
              start: offset + localStart,
              end: offset + localStart + needle.length,
              status: suggestion.status,
              variant,
            });
          }
        }
      }
      segmentIndex += 1;
    }
    offset += line.length + separator.length;
  }

  return ranges
    .sort((left, right) => left.start - right.start || left.end - right.end)
    .filter((range, index, sorted) => index === 0 || range.start >= sorted[index - 1].end);
}

export function previewTextToEditorText(
  previewText: string,
  suggestions: AsrCorrectionSuggestion[],
): string {
  const transcript = editorTextToTranscript(previewText);
  for (const suggestion of suggestions) {
    if (suggestion.status !== "pending") continue;
    const segment = transcript[suggestion.segment_index];
    if (!segment) continue;
    if (!segment.text.includes(suggestion.corrected_text)) continue;
    segment.text = segment.text.replace(suggestion.corrected_text, suggestion.original_text);
  }
  return transcriptToEditorText(transcript);
}

export function reconcilePreviewEditedSuggestions(
  previewText: string,
  suggestions: AsrCorrectionSuggestion[],
): AsrCorrectionSuggestion[] {
  const transcript = editorTextToTranscript(previewText);
  return suggestions.map((suggestion) => {
    if (suggestion.status !== "pending") return suggestion;
    const segmentText = transcript[suggestion.segment_index]?.text ?? "";
    if (segmentText.includes(suggestion.corrected_text)) return suggestion;
    return { ...suggestion, status: "rejected" };
  });
}

export function sortAsrReviewSuggestions(
  suggestions: AsrCorrectionSuggestion[],
  sortByConfidence: boolean,
): AsrCorrectionSuggestion[] {
  const indexed = suggestions.map((suggestion, index) => ({ suggestion, index }));
  if (sortByConfidence) {
    indexed.sort(
      (left, right) =>
        right.suggestion.confidence - left.suggestion.confidence ||
        left.index - right.index,
    );
  }
  return indexed.map((entry) => entry.suggestion);
}

export function filterAsrSuggestionsByConfidence(
  suggestions: AsrCorrectionSuggestion[],
  thresholdPercent: number,
): AsrCorrectionSuggestion[] {
  const normalizedThreshold = Number.isFinite(thresholdPercent)
    ? Math.min(100, Math.max(0, thresholdPercent))
    : 95;
  const threshold = normalizedThreshold / 100;
  return suggestions.filter((suggestion) => suggestion.confidence >= threshold);
}

export function formatEditorTime(seconds: number): string {
  const totalMs = Math.max(0, Math.round(seconds * 1000));
  const totalSeconds = Math.floor(totalMs / 1000);
  const milliseconds = totalMs % 1000;
  const minutes = Math.floor(totalSeconds / 60);
  const second = totalSeconds % 60;
  const hours = Math.floor(minutes / 60);
  const minute = minutes % 60;
  if (hours) {
    return `${pad(hours)}:${pad(minute)}:${pad(second)}.${padMs(milliseconds)}`;
  }
  return `${pad(minute)}:${pad(second)}.${padMs(milliseconds)}`;
}

function transcriptLineTextStart(line: string): number {
  const bracketEnd = line.indexOf("]");
  if (bracketEnd < 0) return -1;
  let index = bracketEnd + 1;
  while (index < line.length && /\s/.test(line[index])) {
    index += 1;
  }
  return index;
}

function editorTimeToSeconds(value: string): number {
  const parts = value.split(":");
  const secondsPart = parts.pop() ?? "0";
  const seconds = Number(secondsPart);
  const minutes = Number(parts.pop() ?? "0");
  const hours = Number(parts.pop() ?? "0");
  if ([seconds, minutes, hours].some((part) => Number.isNaN(part))) {
    throw new Error(`无法解析时间戳 ${value}`);
  }
  return hours * 3600 + minutes * 60 + seconds;
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

function padMs(value: number): string {
  return String(value).padStart(3, "0");
}
