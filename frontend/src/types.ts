export type TranscriptSegment = {
  start: number;
  end: number;
  text: string;
};

export type TimeRange = {
  start: number;
  end: number;
  title: string;
  summary: string;
  priority: "focus" | "skim" | "skip" | "review";
};

export type OutlineNode = {
  id: string;
  start: number;
  end: number;
  title: string;
  summary: string;
  children: OutlineNode[];
};

export type StudyMaterial = {
  one_line: string;
  translated_title?: string | null;
  context_summary?: string | null;
  time_map: TimeRange[];
  outline: OutlineNode[];
  detailed_notes: string;
  high_fidelity_text: string;
  translated_transcript: TranscriptSegment[];
  prerequisites: string[];
  thought_prompts: string[];
  review_suggestions: string[];
};

export type UiLanguage = "zh-CN" | "en";

export type OutputLanguage = "zh-CN" | "en" | "ja";
export type TranscriptSource = "subtitles" | "asr";
export type StudySection = "all" | "guide" | "outline" | "detailed" | "high";
export type ModelProviderType = "openai" | "anthropic";
export type StudyDetailLevel = "fast" | "standard" | "detailed" | "faithful";
export type TaskParameterKey =
  | "title_translation"
  | "subtitle_translation"
  | "asr_correction"
  | "semantic_segmentation"
  | "guide"
  | "outline"
  | "interpretation"
  | "high_fidelity";

export type TaskParameterOverride = {
  temperature?: number | null;
  max_tokens?: number | null;
};

export type JobStatusValue = "queued" | "running" | "succeeded" | "failed";

export type StudyJobStatus = {
  job_id: string;
  item_id: string;
  status: JobStatusValue;
  progress: number;
  phase: string;
  message: string;
  error: string | null;
  started_at?: string | null;
  updated_at?: string | null;
};

export type ModelProfile = {
  id: string;
  name: string;
  provider_type: ModelProviderType;
  base_url: string;
  model: string;
  context_window?: number | null;
  max_tokens?: number | null;
  has_api_key: boolean;
  api_key_preview: string | null;
};

export type ModelProfileInput = {
  id: string;
  name: string;
  provider_type: ModelProviderType;
  base_url: string;
  model: string;
  context_window?: number | null;
  max_tokens?: number | null;
  api_key?: string;
};

export type ModelSettings = {
  profiles: ModelProfile[];
  translation_model_id: string;
  learning_model_id: string;
  global_model_id: string;
  asr_model_id: string;
  study_detail_level: StudyDetailLevel;
  task_parameters: Partial<Record<TaskParameterKey, TaskParameterOverride>>;
};

export type ModelSettingsInput = {
  profiles: ModelProfileInput[];
  translation_model_id: string;
  learning_model_id: string;
  global_model_id: string;
  asr_model_id: string;
  study_detail_level: StudyDetailLevel;
  task_parameters: Partial<Record<TaskParameterKey, TaskParameterOverride>>;
};

export type AsrSearchProvider = "tavily" | "firecrawl";

export type AsrCorrectionSearchConfig = {
  enabled: boolean;
  provider: AsrSearchProvider;
  api_key?: string;
  base_url?: string;
  result_limit: number;
};

export type AsrSearchServiceSettings = {
  base_url?: string | null;
  has_api_key: boolean;
  api_key_preview: string | null;
};

export type AsrSearchSettings = {
  enabled: boolean;
  provider: AsrSearchProvider;
  result_limit: number;
  tavily: AsrSearchServiceSettings;
  firecrawl: AsrSearchServiceSettings;
};

export type AsrSearchServiceSettingsInput = {
  base_url?: string | null;
  api_key?: string;
};

export type AsrSearchSettingsInput = {
  enabled?: boolean;
  provider?: AsrSearchProvider;
  result_limit?: number;
  tavily?: AsrSearchServiceSettingsInput;
  firecrawl?: AsrSearchServiceSettingsInput;
};

export type AsrCorrectionSource = "model" | "search";
export type AsrCorrectionStatus = "pending" | "accepted" | "rejected";

export type AsrCorrectionSuggestion = {
  id: string;
  segment_index: number;
  start: number;
  end: number;
  original_text: string;
  corrected_text: string;
  confidence: number;
  reason: string;
  evidence?: string | null;
  status: AsrCorrectionStatus;
  source: AsrCorrectionSource;
};

export type AsrCorrectionResult = {
  job_id: string;
  item_id: string;
  generated_at: string;
  search_enabled: boolean;
  search_provider: AsrSearchProvider | null;
  suggestions: AsrCorrectionSuggestion[];
};

export type VideoMetadata = {
  id: string;
  title: string;
  duration: number | null;
  uploader?: string | null;
  channel?: string | null;
  creator?: string | null;
  description?: string | null;
  playlist_title?: string | null;
  playlist_index?: number | null;
  webpage_url: string;
  extractor: string;
  stream_url: string | null;
  hls_manifest_url?: string | null;
  language: string | null;
  subtitles: string[];
  automatic_captions: string[];
};

export type CourseItem = {
  id: string;
  source_url: string;
  title: string;
  custom_title?: boolean;
  collection_title?: string | null;
  course_index?: number | null;
  sort_order?: number | null;
  duration: number | null;
  created_at: string;
  transcript: TranscriptSegment[];
  transcript_source?: TranscriptSource | null;
  metadata?: VideoMetadata | null;
  study: StudyMaterial | null;
  local_video_path?: string | null;
};

export type ExtractMode = "normal" | "browser" | "cookies";
