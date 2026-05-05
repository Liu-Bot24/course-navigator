import type {
  AsrCorrectionResult,
  AsrCorrectionSearchConfig,
  AsrSearchSettings,
  AsrSearchSettingsInput,
  CourseImportResponse,
  CourseItem,
  CourseSharePackage,
  ExtractMode,
  ModelSettings,
  ModelSettingsInput,
  ModelProviderType,
  OnlineAsrSettings,
  OnlineAsrSettingsInput,
  OutputLanguage,
  StudySection,
  StudyJobStatus,
  StudyMaterial,
  TranscriptSource,
  TranscriptSegment,
} from "./types";

export function apiPath(path: string): string {
  if (path.startsWith("/api/")) {
    return path;
  }
  return `/api${path.startsWith("/") ? path : `/${path}`}`;
}

export async function listItems(): Promise<CourseItem[]> {
  return requestJson<CourseItem[]>("/items");
}

export async function importCoursePackage(input: CourseSharePackage): Promise<CourseImportResponse> {
  return requestJson<CourseImportResponse>("/import", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function extractCourse(input: {
  url: string;
  mode: ExtractMode;
  browser: string;
  cookies_path?: string;
  language?: string;
  subtitle_source?: TranscriptSource;
}): Promise<CourseItem> {
  return requestJson<CourseItem>("/extract", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function startExtractJob(input: {
  url: string;
  mode: ExtractMode;
  browser: string;
  cookies_path?: string;
  language?: string;
  subtitle_source?: TranscriptSource;
}): Promise<StudyJobStatus> {
  return requestJson<StudyJobStatus>("/extract-jobs", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function previewCourse(input: {
  url: string;
  mode: ExtractMode;
  browser: string;
  cookies_path?: string;
  language?: string;
  subtitle_source?: TranscriptSource;
}): Promise<CourseItem> {
  return requestJson<CourseItem>("/preview", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function generateStudy(itemId: string, outputLanguage: OutputLanguage): Promise<StudyMaterial> {
  return requestJson<StudyMaterial>(`/items/${itemId}/study`, {
    method: "POST",
    body: JSON.stringify({ output_language: outputLanguage }),
  });
}

export async function startStudyJob(
  itemId: string,
  outputLanguage: OutputLanguage,
  section: StudySection = "all",
): Promise<StudyJobStatus> {
  return requestJson<StudyJobStatus>(`/items/${itemId}/study-jobs`, {
    method: "POST",
    body: JSON.stringify({ output_language: outputLanguage, section }),
  });
}

export async function startTranslationJob(itemId: string, outputLanguage: OutputLanguage): Promise<StudyJobStatus> {
  return requestJson<StudyJobStatus>(`/items/${itemId}/translation-jobs`, {
    method: "POST",
    body: JSON.stringify({ output_language: outputLanguage }),
  });
}

export async function getStudyJob(jobId: string): Promise<StudyJobStatus> {
  return requestJson<StudyJobStatus>(`/jobs/${jobId}`);
}

export async function saveTranscript(itemId: string, transcript: TranscriptSegment[]): Promise<CourseItem> {
  return requestJson<CourseItem>(`/items/${itemId}/transcript`, {
    method: "PUT",
    body: JSON.stringify({ transcript }),
  });
}

export async function startAsrCorrectionJob(
  itemId: string,
  input: {
    output_language?: OutputLanguage;
    transcript?: TranscriptSegment[];
    model_id?: string;
    user_context?: string;
    search: AsrCorrectionSearchConfig;
  },
): Promise<StudyJobStatus> {
  return requestJson<StudyJobStatus>(`/items/${itemId}/asr-correction-jobs`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function getAsrCorrectionResult(jobId: string): Promise<AsrCorrectionResult> {
  return requestJson<AsrCorrectionResult>(`/asr-correction-jobs/${jobId}/result`);
}

export async function getAsrSearchSettings(): Promise<AsrSearchSettings> {
  return requestJson<AsrSearchSettings>("/settings/asr-search");
}

export async function saveAsrSearchSettings(input: AsrSearchSettingsInput): Promise<AsrSearchSettings> {
  return requestJson<AsrSearchSettings>("/settings/asr-search", {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export async function getOnlineAsrSettings(): Promise<OnlineAsrSettings> {
  return requestJson<OnlineAsrSettings>("/settings/online-asr");
}

export async function saveOnlineAsrSettings(input: OnlineAsrSettingsInput): Promise<OnlineAsrSettings> {
  return requestJson<OnlineAsrSettings>("/settings/online-asr", {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export async function deleteCourse(itemId: string): Promise<{ deleted: boolean }> {
  return requestJson<{ deleted: boolean }>(`/items/${itemId}`, {
    method: "DELETE",
  });
}

export async function updateCourseItem(
  itemId: string,
  input: {
    title?: string;
    translated_title?: string | null;
    collection_title?: string | null;
    course_index?: number | null;
    sort_order?: number | null;
  },
): Promise<CourseItem> {
  return requestJson<CourseItem>(`/items/${itemId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export async function deleteLocalVideo(itemId: string): Promise<CourseItem> {
  return requestJson<CourseItem>(`/items/${itemId}/local-video`, {
    method: "DELETE",
  });
}

export async function getModelSettings(): Promise<ModelSettings> {
  return requestJson<ModelSettings>("/settings/model");
}

export async function saveModelSettings(input: ModelSettingsInput): Promise<ModelSettings> {
  return requestJson<ModelSettings>("/settings/model", {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export async function listAvailableModels(input: {
  provider_type: ModelProviderType;
  base_url: string;
  api_key?: string;
  profile_id?: string;
}): Promise<{ models: string[] }> {
  return requestJson<{ models: string[] }>("/settings/models", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function downloadVideo(
  itemId: string,
  input: { url: string; mode: ExtractMode; browser: string; cookies_path?: string },
): Promise<{ path: string }> {
  return requestJson<{ path: string }>(`/items/${itemId}/download`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function startDownloadJob(
  itemId: string,
  input: { url: string; mode: ExtractMode; browser: string; cookies_path?: string },
): Promise<StudyJobStatus> {
  return requestJson<StudyJobStatus>(`/items/${itemId}/download-jobs`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function itemVideoPath(itemId: string): string {
  return apiPath(`/items/${encodeURIComponent(itemId)}/video`);
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiPath(path), {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail ?? `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}
