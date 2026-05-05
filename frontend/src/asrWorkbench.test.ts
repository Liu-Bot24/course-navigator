import { describe, expect, test } from "vitest";

import {
  applyAsrSuggestion,
  asrEditorHighlightRanges,
  asrSuggestionContext,
  editorTextToTranscript,
  filterAsrSuggestionsByConfidence,
  previewTextToEditorText,
  reconcilePreviewEditedSuggestions,
  sortAsrReviewSuggestions,
  transcriptToEditorText,
} from "./asrWorkbench";
import type { AsrCorrectionSuggestion, TranscriptSegment } from "./types";

const transcript: TranscriptSegment[] = [
  { start: 0, end: 4, text: "Opening idea." },
  { start: 4, end: 8, text: "Important detail." },
];

describe("ASR workbench transcript editor helpers", () => {
  test("serializes and parses editable timestamped transcript lines", () => {
    const text = transcriptToEditorText(transcript);

    expect(text).toContain("[00:00.000-00:04.000] Opening idea.");
    expect(editorTextToTranscript(text)).toEqual(transcript);
  });

  test("keeps timing while allowing edited source text to be parsed back", () => {
    const edited = "[00:00.000-00:04.000] Opening idea corrected.\n[00:04.000-00:08.000] Important detail.";

    expect(editorTextToTranscript(edited)).toEqual([
      { start: 0, end: 4, text: "Opening idea corrected." },
      { start: 4, end: 8, text: "Important detail." },
    ]);
  });

  test("applies an accepted suggestion to the matching segment only once", () => {
    const suggestion: AsrCorrectionSuggestion = {
      id: "patch-1",
      segment_index: 1,
      start: 4,
      end: 8,
      original_text: "Important",
      corrected_text: "Crucial",
      confidence: 0.92,
      reason: "The surrounding lesson uses Crucial as the named term.",
      evidence: "Model context",
      status: "pending",
      source: "model",
    };

    const next = applyAsrSuggestion(transcript, suggestion);

    expect(next[0].text).toBe("Opening idea.");
    expect(next[1].text).toBe("Crucial detail.");
  });

  test("projects a short ASR patch back into the full subtitle line", () => {
    const suggestion: AsrCorrectionSuggestion = {
      id: "patch-2",
      segment_index: 1,
      start: 4,
      end: 8,
      original_text: "Important",
      corrected_text: "Crucial",
      confidence: 0.92,
      reason: "术语应为 Crucial。",
      evidence: "相邻字幕使用同一术语。",
      status: "pending",
      source: "model",
    };

    expect(asrSuggestionContext(transcript, suggestion)).toEqual({
      originalLine: "Important detail.",
      correctedLine: "Crucial detail.",
      originalMatched: true,
      correctedMatched: true,
    });
  });

  test("builds highlight ranges inside the editable source transcript", () => {
    const suggestion: AsrCorrectionSuggestion = {
      id: "patch-3",
      segment_index: 1,
      start: 4,
      end: 8,
      original_text: "Important",
      corrected_text: "Crucial",
      confidence: 0.92,
      reason: "术语应为 Crucial。",
      evidence: "相邻字幕使用同一术语。",
      status: "pending",
      source: "model",
    };
    const editorText = transcriptToEditorText(transcript);
    const [range] = asrEditorHighlightRanges(editorText, [suggestion]);

    expect(editorText.slice(range.start, range.end)).toBe("Important");
    expect(range.variant).toBe("original");
  });

  test("maps an unchanged editable preview back to the source transcript", () => {
    const suggestion: AsrCorrectionSuggestion = {
      id: "patch-4",
      segment_index: 1,
      start: 4,
      end: 8,
      original_text: "Important",
      corrected_text: "Crucial",
      confidence: 0.92,
      reason: "术语应为 Crucial。",
      evidence: "相邻字幕使用同一术语。",
      status: "pending",
      source: "model",
    };

    const previewText = transcriptToEditorText([
      transcript[0],
      { ...transcript[1], text: "Crucial detail." },
    ]);

    expect(previewTextToEditorText(previewText, [suggestion])).toBe(transcriptToEditorText(transcript));
  });

  test("treats manual edits in the preview as resolving that suggestion", () => {
    const suggestion: AsrCorrectionSuggestion = {
      id: "patch-5",
      segment_index: 1,
      start: 4,
      end: 8,
      original_text: "Important",
      corrected_text: "Crucial",
      confidence: 0.92,
      reason: "术语应为 Crucial。",
      evidence: "相邻字幕使用同一术语。",
      status: "pending",
      source: "model",
    };
    const previewText = transcriptToEditorText([
      transcript[0],
      { ...transcript[1], text: "Useful detail." },
    ]);

    expect(editorTextToTranscript(previewTextToEditorText(previewText, [suggestion]))[1].text).toBe("Useful detail.");
    expect(reconcilePreviewEditedSuggestions(previewText, [suggestion])[0].status).toBe("rejected");
  });

  test("sorts review suggestions by confidence only when requested", () => {
    const suggestions: AsrCorrectionSuggestion[] = [
      asrSuggestion("low", 0.72),
      asrSuggestion("high", 0.98),
      asrSuggestion("middle", 0.95),
    ];

    expect(sortAsrReviewSuggestions(suggestions, false).map((suggestion) => suggestion.id)).toEqual([
      "low",
      "high",
      "middle",
    ]);
    expect(sortAsrReviewSuggestions(suggestions, true).map((suggestion) => suggestion.id)).toEqual([
      "high",
      "middle",
      "low",
    ]);
  });

  test("filters suggestions at or above a confidence percentage", () => {
    const suggestions: AsrCorrectionSuggestion[] = [
      asrSuggestion("below", 0.949),
      asrSuggestion("exact", 0.95),
      asrSuggestion("above", 0.981),
    ];

    expect(filterAsrSuggestionsByConfidence(suggestions, 95).map((suggestion) => suggestion.id)).toEqual([
      "exact",
      "above",
    ]);
  });
});

function asrSuggestion(id: string, confidence: number): AsrCorrectionSuggestion {
  return {
    id,
    segment_index: 0,
    start: 0,
    end: 4,
    original_text: "Opening",
    corrected_text: "Beginning",
    confidence,
    reason: "test",
    evidence: "test",
    status: "pending",
    source: "model",
  };
}
