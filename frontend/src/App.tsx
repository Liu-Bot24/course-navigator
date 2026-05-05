import {
  ArrowLeft,
  ArrowDown,
  ArrowUp,
  BookOpen,
  Captions,
  Check,
  CheckCheck,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  Copy,
  Download,
  FileText,
  FolderPlus,
  GitCompare,
  Languages,
  Loader2,
  Maximize2,
  Minimize2,
  Pencil,
  Play,
  Save,
  Settings as SettingsIcon,
  Sparkles,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import type {
  ChangeEvent as ReactChangeEvent,
  CSSProperties,
  MouseEvent as ReactMouseEvent,
  MutableRefObject,
  PointerEvent as ReactPointerEvent,
  ReactNode,
} from "react";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  deleteCourse,
  deleteLocalVideo,
  extractCourse,
  getAsrCorrectionResult,
  getAsrSearchSettings,
  getModelSettings,
  getOnlineAsrSettings,
  getStudyJob,
  importCoursePackage,
  itemVideoPath,
  listItems,
  listAvailableModels,
  previewCourse,
  saveModelSettings,
  saveAsrSearchSettings,
  saveOnlineAsrSettings,
  saveTranscript,
  startExtractJob,
  startAsrCorrectionJob,
  startDownloadJob,
  startStudyJob,
  startTranslationJob,
  updateCourseItem,
} from "./api";
import {
  applyAsrSuggestion,
  asrEditorHighlightRanges,
  asrSuggestionContext,
  type AsrEditorHighlightRange,
  editorTextToTranscript,
  filterAsrSuggestionsByConfidence,
  previewTextToEditorText,
  reconcilePreviewEditedSuggestions,
  sortAsrReviewSuggestions,
  transcriptToEditorText,
} from "./asrWorkbench";
import { parseUploadedSubtitleText } from "./subtitleUpload";
import type {
  AsrCorrectionSearchConfig,
  AsrCorrectionSuggestion,
  AsrSearchProvider,
  AsrSearchSettings,
  AsrSearchSettingsInput,
  CourseSharePackage,
  CourseItem,
  ExtractMode,
  ModelProfile,
  ModelProfileInput,
  ModelProviderType,
  ModelSettings,
  ModelSettingsInput,
  OnlineAsrProvider,
  OnlineAsrSettings,
  OnlineAsrSettingsInput,
  OutputLanguage,
  OutlineNode,
  StudyMaterial,
  StudySection,
  StudyJobStatus,
  StudyDetailLevel,
  TaskParameterKey,
  TaskParameterOverride,
  TranscriptSource,
  TranscriptSegment,
  UiLanguage,
} from "./types";
import { buildWebVttTrack, formatTime, getBilibiliVideoId, getYouTubeVideoId } from "./utils";

type AiTab = "guide" | "outline" | "detailed" | "high";
type SourceMode = "embed" | "local";
type TextDisplayMode = "source" | "target" | "bilingual";
type CaptionDisplayMode = TextDisplayMode | "hidden";
type CaptionPlacement = "overlay" | "panel";
type LayoutDragKind = "left" | "right" | "player";
type AsrSuggestionDirection = -1 | 1;
type SubtitleSourceChoice = TranscriptSource | "local_upload";

function requestTranscriptSource(source: SubtitleSourceChoice): TranscriptSource {
  return source === "local_upload" ? "subtitles" : source;
}

function usesBackgroundSubtitleExtraction(source: SubtitleSourceChoice): boolean {
  return source === "asr" || source === "online_asr";
}
type ModelProfileDraft = Omit<ModelProfile, "context_window" | "max_tokens"> & {
  api_key: string;
  context_window: string;
  max_tokens: string;
};
type TaskParameterDraft = {
  temperature: string;
  max_tokens: string;
};
type CourseEditDraft = {
  title: string;
  translated_title: string;
  collection_title: string;
  course_index: string;
};
type LibraryCollectionGroup = {
  key: string;
  title: string;
  value: string;
  items: CourseItem[];
};
type SettingsDraft = {
  profiles: ModelProfileDraft[];
  active_profile_id: string;
  translation_model_id: string;
  learning_model_id: string;
  global_model_id: string;
  asr_model_id: string;
  study_detail_level: StudyDetailLevel;
  task_parameters: Record<TaskParameterKey, TaskParameterDraft>;
};
type AsrSearchDraft = {
  enabled: boolean;
  provider: AsrSearchProvider;
  api_key: string;
  api_key_preview: string | null;
  base_url: string;
  result_limit: string;
};
type OnlineAsrDraft = {
  provider: OnlineAsrProvider;
  openai_api_key: string;
  openai_api_key_preview: string | null;
  groq_api_key: string;
  groq_api_key_preview: string | null;
  xai_api_key: string;
  xai_api_key_preview: string | null;
  custom_base_url: string;
  custom_model: string;
  custom_api_key: string;
  custom_api_key_preview: string | null;
};
type AsrSuggestionHover = {
  suggestionId: string;
  left: number;
  top: number;
};
type ModelRoleKey = "translation_model_id" | "learning_model_id" | "global_model_id";
type YouTubePlayer = {
  destroy?: () => void;
  getCurrentTime?: () => number;
  getPlayerState?: () => number;
  playVideo?: () => void;
  setOption?: (module: string, option: string, value: unknown) => void;
  seekTo?: (seconds: number, allowSeekAhead: boolean) => void;
  unloadModule?: (module: string) => void;
};

declare global {
  interface Window {
    YT?: {
      Player: new (
        element: HTMLIFrameElement | string,
        options?: {
          events?: {
            onReady?: () => void;
            onStateChange?: () => void;
          };
        },
      ) => YouTubePlayer;
    };
    onYouTubeIframeAPIReady?: () => void;
  }
}

let youtubeApiPromise: Promise<void> | null = null;

const COPY = {
  "zh-CN": {
    subtitle: "视频学习工作台",
    urlPlaceholder: "粘贴课程或视频 URL",
    modeNormal: "公开访问",
    modeBrowser: "浏览器 Cookie",
    modeCookies: "Cookies 文件",
    openUrl: "打开视频并提取字幕",
    openUrlTitle: "打开视频，并自动提取原始字幕",
    getSubtitles: "获取字幕",
    getSubtitlesTitle: "为当前视频获取字幕",
    getSubtitlesConfirm: "当前课程已经有字幕。继续获取会覆盖现有字幕和对应学习结果，确定继续吗？",
    extractSubtitles: "提取字幕",
    translateSubtitles: "翻译字幕",
    subtitleSource: "字幕来源",
    subtitleSourceOriginal: "原字幕优先",
    subtitleSourceAsr: "本地 ASR",
    subtitleSourceOnlineAsr: "在线 ASR",
    subtitleSourceLocalUpload: "本地上传",
    uploadSubtitleFile: "上传字幕文件",
    importingLocalSubtitle: "正在导入本地字幕",
    localSubtitleNoTarget: "请先打开或选择一个课程，再上传本地字幕。",
    localSubtitleEmpty: "没有解析到可用字幕。",
    subtitlesReady: "已有字幕",
    translationReady: "已有译文",
    extractAuth: "提取登录",
    cookieSource: "Cookie 来源",
    cookieFile: "Cookie 文件",
    previewTitle: "待分析视频",
    browserCookieHint: "chrome 或 chrome:Default",
    interfaceLanguage: "界面",
    outputLanguage: "输出",
    displayMode: "显示模式",
    modelSettings: "模型设置",
    modelSettingsTitle: "模型配置",
    asrModelSettingsTitle: "ASR 模型档案",
    modelProfileLibrary: "模型档案",
    asrModelProfileLibrary: "ASR 模型档案",
    addModelProfile: "新增档案",
    addCollection: "新建专辑",
    activeModelProfile: "正在编辑",
    unnamedModelProfile: "未命名档案",
    providerType: "接口格式",
    providerOpenAI: "OpenAI 格式",
    providerAnthropic: "Anthropic 格式",
    profileName: "档案名称",
    translationModel: "字幕模型",
    learningModel: "详解模型",
    globalModel: "结构模型",
    translationModelHelp: "字幕逐句翻译和标题翻译，优先使用便宜、快速、稳定的小模型。",
    learningModelHelp: "生成每个语义学习块的解读、详解和高保真文本，负责内容质量。",
    globalModelHelp: "生成上下文摘要、语义分块、导览、大纲和跨块整合，需要更强的长上下文能力。",
    onlineAsrSettingsTitle: "在线 ASR",
    onlineAsrSettingsHelp: "用于在没有站方字幕时通过在线语音识别生成带时间戳字幕。预设服务只需要填写 API Key；自定义接口会自动识别分段、词级时间戳、SRT 或 VTT 返回。",
    onlineAsrProvider: "在线 ASR 服务",
    onlineAsrProviderNone: "不使用在线 ASR",
    onlineAsrProviderOpenAI: "OpenAI Whisper",
    onlineAsrProviderGroq: "Groq Whisper",
    onlineAsrProviderXai: "xAI",
    onlineAsrProviderCustom: "自定义",
    onlineAsrApiKey: "在线 ASR API Key",
    onlineAsrCustomBaseUrl: "自定义接口地址",
    onlineAsrCustomModel: "自定义模型名称",
    onlineAsrPresetHelp: "选择在线 ASR 作为字幕来源时，会自动抽取音频、压缩并分块转写。",
    onlineAsrCustomHelp: "自定义接口会自动兼容分段时间戳、词级时间戳、SRT 和 VTT；纯文本转写不能作为字幕。",
    onlineAsrProviderSaved: "在线 ASR 服务已保存",
    advancedModelSettings: "高级调用参数",
    advancedModelSettingsHelp: "留空使用代码默认值。这里覆盖具体任务调用；不熟悉模型参数时建议保持默认。",
    modelCapabilitySettings: "模型能力覆盖",
    taskStrategySettings: "任务策略覆盖",
    taskStrategyHelp: "按任务分别覆盖 Temperature 和最大输出。错误设置可能导致输出变短、JSON 解析失败、成本上升或结果不稳定。",
    titleTranslationTask: "标题翻译",
    subtitleTranslationTask: "字幕翻译",
    asrCorrectionTask: "ASR 校正",
    semanticSegmentationTask: "语义分块",
    guideTask: "导览",
    outlineTask: "大纲",
    interpretationTask: "解读",
    highFidelityTask: "详解",
    modelBaseUrl: "接口地址",
    modelName: "模型",
    contextWindow: "上下文窗口上限（选填）",
    temperature: "Temperature（选填）",
    maxTokens: "最大输出上限（选填）",
    taskMaxTokens: "最大输出",
    fetchModels: "获取模型",
    fetchingModels: "正在获取",
    modelFetchFailed: "模型列表获取失败",
    noModelCandidates: "没有可用模型",
    modelApiKey: "API Key",
    modelApiKeyHint: "留空则保留当前 Key",
    apiKeyOptionalHint: "未配置，可留空",
    modelConfigured: "已配置",
    modelNotConfigured: "未配置",
    closeDialog: "关闭",
    closeSettings: "关闭设置",
    saveSettings: "保存档案",
    settingsSaved: "档案已保存",
    saveAsrSettings: "保存 ASR 档案",
    modelRolesSaving: "正在保存模型选择",
    modelRolesSaved: "模型选择已保存",
    modelRolesSaveFailed: "模型选择保存失败",
    analyze: "提取字幕",
    previewing: "正在打开视频预览",
    extracting: "正在提取字幕",
    generating: "正在生成学习地图",
    caching: "正在缓存本地视频",
    library: "课程库",
    importCourses: "导入课程",
    exportCourses: "导出课程",
    importCoursePackage: "导入课程包",
    exportCoursePackage: "导出课程包",
    exportCoursePackageTitle: "选择要导出的课程",
    exportCoursePackageHelp: "完整选择某个专辑时会保留专辑名称和排序；单独选择课程会导入到未归档。",
    exportSelected: "导出所选",
    selectCoursesToExport: "选择课程",
    shareMessage: "留言",
    shareMessagePlaceholder: "可以写一句想留给导入者的话，也可以留空。",
    noExportSelection: "请先选择至少一个课程。",
    importPackageFailed: "课程包导入失败",
    importMessageTitle: "来自分享者的留言",
    closeImportMessage: "知道了",
    timeMap: "时间地图",
    collapseTimeMap: "收起时间地图",
    expandTimeMap: "展开时间地图",
    noDuration: "无时长",
    emptyLibrary: "打开一个视频开始学习。",
    noTimeMap: "生成学习地图后会显示 AI 分块时间地图。",
    noCourse: "尚未选择课程",
    pasteAndAnalyze: "粘贴 URL 后点击播放按钮，系统会自动提取字幕。",
    stream: "在线播放",
    local: "本地",
    cache: "缓存",
    transcript: "字幕列表",
    asrCorrection: "ASR 校正",
    openAsrCorrection: "打开 ASR 校正工作台",
    asrWorkbenchTitle: "ASR 校正工作台",
    asrWorkbenchSubtitle: "校正原字幕，保存后会刷新视频工作台的字幕。",
    backToWorkspace: "返回主工作台",
    sourceTranscriptEditor: "原字幕编辑区",
    saveTranscript: "保存字幕",
    transcriptSaved: "字幕已保存",
    runAsrCorrection: "生成校正建议",
    asrModel: "ASR 校正模型",
    asrModelHelp: "选择用于校正字幕的模型档案。",
    asrUserContext: "附加参考信息",
    asrUserContextHelp: "写入你已经确认的术语、人名、产品名和常见误识别，模型会把它作为高优先级参考。",
    asrUserContextPlaceholder: "",
    noModelProfiles: "还没有模型档案",
    configureModelProfiles: "管理 ASR 模型档案",
    asrCorrectionApiUnavailable: "ASR 校正接口暂不可用。请重启后端服务后再生成建议。",
    asrProgressTitle: "ASR 校正进行中",
    asrProgressElapsed: "已用时",
    asrProgressUpdated: "最近更新",
    asrProgressStale: "后端状态已经超过 30 秒没有更新，可能是模型接口长时间无响应。",
    asrPhaseQueued: "排队中",
    asrPhasePreparing: "准备请求",
    asrPhaseCandidate: "提取可疑术语",
    asrPhaseSearch: "搜索证据",
    asrPhaseBackground: "归纳搜索背景",
    asrPhaseReview: "生成建议",
    asrPhaseModelRequest: "发送模型请求",
    asrPhaseModelWait: "等待模型响应",
    asrPhaseModelParse: "解析模型返回",
    asrPhaseFinalizing: "整理结果",
    asrPhaseComplete: "完成",
    asrPhaseFailed: "失败",
    searchCalibration: "搜索校验",
    searchCalibrationOn: "开启搜索",
    searchCalibrationOff: "关闭搜索",
    searchProvider: "搜索服务",
    searchApiKey: "搜索 API Key",
    firecrawlBaseUrl: "Firecrawl 地址",
    searchResultLimit: "结果数",
    correctionSuggestions: "修改建议",
    noCorrectionSuggestions: "还没有修改建议。",
    asrBeforeTranscript: "修改前",
    asrAfterTranscript: "修改后预览",
    expandSuggestions: "展开",
    collapseSuggestions: "收起",
    previousSuggestion: "上一个",
    nextSuggestion: "下一个",
    rerunAsrCorrection: "再次校正",
    saveAcceptedChanges: "接受后自动保存字幕",
    sortSuggestionsByConfidence: "按置信度从高到低排序",
    acceptConfidencePrefix: "一键接受置信度",
    acceptConfidenceSuffix: "% 以上的修改建议",
    acceptConfidenceAction: "接受高置信度建议",
    modelCalibration: "模型校验",
    suggestionDetail: "理由 / 证据",
    originalSpanNotFound: "原文未精确命中",
    candidateSpan: "候选片段",
    acceptChange: "接受",
    rejectChange: "拒绝",
    acceptAllChanges: "全部接受",
    originalText: "原文",
    correctedText: "建议",
    confidence: "置信度",
    evidence: "证据",
    reason: "理由",
    pendingChanges: "待处理",
    acceptedChanges: "已接受",
    rejectedChanges: "已拒绝",
    noAsrTranscript: "请先提取字幕后再进入 ASR 校正。",
    noVideo: "还没有加载视频",
    notEmbeddable: "这个来源暂时不能嵌入播放，但字幕导航仍可使用。",
    bilibiliEmbedUnavailable: "bilibili站外播放不提供字幕时间轴功能，建议缓存后观看。",
    forceStream: "强制在线播放",
    noTranscript: "还没有加载字幕。",
    noTranscriptForStudy: "请先打开视频并完成字幕提取，再翻译或生成学习地图。",
    guide: "导览",
    outline: "大纲",
    detailed: "解读",
    high: "详解",
    selectFirst: "请先选择或提取一个课程。",
    noStudy: "这个课程已有字幕，但还没有学习地图。",
    generateStudy: "生成学习地图",
    regenerateGuide: "重新生成导览",
    regenerateOutline: "重新生成大纲",
    regenerateDetailed: "重新生成解读",
    regenerateHigh: "重新生成详解",
    studyActionHint: "学习内容按当前输出语言生成；更改输出语言后需要重新生成。",
    deleteCourse: "删除课程",
    deleteCourseConfirm: "确定要从课程库删除这个课程吗？本地缓存和字幕文件也会一起移除。",
    editTitle: "编辑标题",
    saveTitle: "保存标题",
    cancelTitleEdit: "取消编辑标题",
    courseTitle: "课程标题",
    courseTranslatedTitle: "译文标题",
    courseCollection: "所属专辑",
    courseCollectionFallback: "未归档",
    emptyCollection: "暂无课程",
    newCollectionPrompt: "输入新专辑名称",
    collapseCollection: "收起专辑",
    expandCollection: "展开专辑",
    editCollection: "编辑专辑",
    deleteCollection: "删除专辑",
    deleteCollectionConfirm: "删除这个专辑？课程不会被删除，会移动到未归档。",
    saveCollection: "保存专辑",
    cancelCollectionEdit: "取消编辑专辑",
    collectionTitle: "专辑名称",
    collectionTitleRequired: "专辑名称不能为空。",
    courseIndex: "课程序号",
    courseTitleRequired: "课程标题不能为空。",
    moveCourseUp: "上移课程",
    moveCourseDown: "下移课程",
    moveCollectionUp: "上移专辑",
    moveCollectionDown: "下移专辑",
    removeLocalCache: "移除缓存",
    removeLocalCacheConfirm: "确定要删除这个课程的本地视频缓存吗？字幕和学习地图会保留。",
    regenerateStudy: "重新生成",
    prerequisites: "预备知识",
    thoughtPrompts: "思考提示",
    reviewSuggestions: "复习建议",
    noPrerequisites: "暂未标记预备知识。",
    noPrompts: "暂未生成思考提示。",
    noReviews: "暂未生成复习建议。",
    unknownError: "未知错误",
    outputZh: "中文",
    outputEn: "English",
    outputJa: "日本語",
    sourceOnly: "只看原文",
    targetOnly: "只看译文",
    bilingual: "双语",
    hideCaption: "隐藏字幕",
    sourceLabel: "原文",
    targetLabel: "译文",
    videoCaption: "视频字幕",
    captionOverlay: "浮层",
    captionPanel: "字幕栏",
    fullscreenVideo: "全屏",
    exitFullscreen: "退出全屏",
    fullscreenEscHint: "全屏模式请按 Esc 键退出",
    copyUrl: "复制 URL",
    outlineLevel1: "L1",
    outlineLevel2: "L2",
    outlineExpandAll: "全部",
  },
  en: {
    subtitle: "Video learning workspace",
    urlPlaceholder: "Paste a course or video URL",
    modeNormal: "Normal",
    modeBrowser: "Browser cookies",
    modeCookies: "Cookies file",
    openUrl: "Open and extract subtitles",
    openUrlTitle: "Open the video and extract source subtitles",
    getSubtitles: "Get subtitles",
    getSubtitlesTitle: "Get subtitles for the current video",
    getSubtitlesConfirm: "This course already has subtitles. Getting subtitles again will overwrite the current transcript and related study results. Continue?",
    extractSubtitles: "Extract subtitles",
    translateSubtitles: "Translate subtitles",
    subtitleSource: "Subtitle source",
    subtitleSourceOriginal: "Source first",
    subtitleSourceAsr: "Local ASR",
    subtitleSourceOnlineAsr: "Online ASR",
    subtitleSourceLocalUpload: "Local upload",
    uploadSubtitleFile: "Upload subtitle file",
    importingLocalSubtitle: "Importing local subtitles",
    localSubtitleNoTarget: "Open or select a course before uploading local subtitles.",
    localSubtitleEmpty: "No usable subtitles were found in this file.",
    subtitlesReady: "Transcript ready",
    translationReady: "Translation ready",
    extractAuth: "Auth",
    cookieSource: "Cookie source",
    cookieFile: "Cookie file",
    previewTitle: "Video preview",
    browserCookieHint: "chrome or chrome:Default",
    interfaceLanguage: "Interface",
    outputLanguage: "Output",
    displayMode: "Display mode",
    modelSettings: "Model settings",
    modelSettingsTitle: "Model settings",
    asrModelSettingsTitle: "ASR model profiles",
    modelProfileLibrary: "Model profiles",
    asrModelProfileLibrary: "ASR model profiles",
    addModelProfile: "Add profile",
    addCollection: "New collection",
    activeModelProfile: "Editing",
    unnamedModelProfile: "Unnamed profile",
    providerType: "API format",
    providerOpenAI: "OpenAI format",
    providerAnthropic: "Anthropic format",
    profileName: "Profile name",
    translationModel: "Subtitle model",
    learningModel: "Detailed model",
    globalModel: "Structure model",
    translationModelHelp: "Sentence-by-sentence subtitle and title translation; best with a fast, cheaper model.",
    learningModelHelp: "Generates interpretation, detailed notes, and high-fidelity text for each semantic block.",
    globalModelHelp: "Context summary, semantic segmentation, guide, outline, and cross-block synthesis.",
    onlineAsrSettingsTitle: "Online ASR",
    onlineAsrSettingsHelp: "Use an online speech-to-text service to generate timestamped subtitles when source subtitles are unavailable. Preset services only need an API key; custom endpoints auto-detect segment timestamps, word timestamps, SRT, or VTT responses.",
    onlineAsrProvider: "Online ASR service",
    onlineAsrProviderNone: "Do not use online ASR",
    onlineAsrProviderOpenAI: "OpenAI Whisper",
    onlineAsrProviderGroq: "Groq Whisper",
    onlineAsrProviderXai: "xAI",
    onlineAsrProviderCustom: "Custom",
    onlineAsrApiKey: "Online ASR API Key",
    onlineAsrCustomBaseUrl: "Custom base URL",
    onlineAsrCustomModel: "Custom model name",
    onlineAsrPresetHelp: "When Online ASR is selected as the subtitle source, audio is extracted, compressed, split, and transcribed automatically.",
    onlineAsrCustomHelp: "Custom endpoints auto-detect segment timestamps, word timestamps, SRT, and VTT. Plain text responses cannot be used as subtitles.",
    onlineAsrProviderSaved: "Online ASR service saved",
    advancedModelSettings: "Advanced call parameters",
    advancedModelSettingsHelp: "Blank fields use code defaults. These values override individual task calls.",
    modelCapabilitySettings: "Model capability overrides",
    taskStrategySettings: "Task strategy overrides",
    taskStrategyHelp: "Override temperature and max output per task. Bad values can shorten output, break JSON, raise cost, or reduce stability.",
    titleTranslationTask: "Title translation",
    subtitleTranslationTask: "Subtitle translation",
    asrCorrectionTask: "ASR correction",
    semanticSegmentationTask: "Semantic segmentation",
    guideTask: "Guide",
    outlineTask: "Outline",
    interpretationTask: "Interpretation",
    highFidelityTask: "Detailed",
    modelBaseUrl: "Base URL",
    modelName: "Model",
    contextWindow: "Context window limit (optional)",
    temperature: "Temperature (optional)",
    maxTokens: "Max output limit (optional)",
    taskMaxTokens: "Max output",
    fetchModels: "Fetch models",
    fetchingModels: "Fetching",
    modelFetchFailed: "Failed to fetch models",
    noModelCandidates: "No models found",
    modelApiKey: "API Key",
    modelApiKeyHint: "Leave blank to keep current key",
    apiKeyOptionalHint: "Not configured, optional",
    modelConfigured: "Configured",
    modelNotConfigured: "Not configured",
    closeDialog: "Close",
    closeSettings: "Close settings",
    saveSettings: "Save profile",
    settingsSaved: "Profile saved",
    saveAsrSettings: "Save ASR profile",
    modelRolesSaving: "Saving model selection",
    modelRolesSaved: "Model selection saved",
    modelRolesSaveFailed: "Failed to save model selection",
    analyze: "Extract subtitles",
    previewing: "Opening video preview",
    extracting: "Extracting subtitles",
    generating: "Generating study map",
    caching: "Caching video locally",
    library: "Library",
    importCourses: "Import courses",
    exportCourses: "Export courses",
    importCoursePackage: "Import course package",
    exportCoursePackage: "Export course package",
    exportCoursePackageTitle: "Choose courses to export",
    exportCoursePackageHelp: "Selecting a full collection preserves its name and order. Individually selected courses import as unfiled.",
    exportSelected: "Export selected",
    selectCoursesToExport: "Select courses",
    shareMessage: "Message",
    shareMessagePlaceholder: "Add an optional note for the person importing this package.",
    noExportSelection: "Select at least one course first.",
    importPackageFailed: "Failed to import course package",
    importMessageTitle: "Message from the sharer",
    closeImportMessage: "Got it",
    timeMap: "Time Map",
    collapseTimeMap: "Collapse time map",
    expandTimeMap: "Expand time map",
    noDuration: "No duration",
    emptyLibrary: "Open a video to start.",
    noTimeMap: "The AI block time map appears after study generation.",
    noCourse: "No course selected",
    pasteAndAnalyze: "Paste a URL and press play; subtitles are extracted automatically.",
    stream: "Stream",
    local: "Local",
    cache: "Cache",
    transcript: "Subtitle list",
    asrCorrection: "ASR correction",
    openAsrCorrection: "Open ASR correction workbench",
    asrWorkbenchTitle: "ASR correction workbench",
    asrWorkbenchSubtitle: "Correct source subtitles; saving refreshes captions in the video workspace.",
    backToWorkspace: "Back to main workspace",
    sourceTranscriptEditor: "Source transcript editor",
    saveTranscript: "Save transcript",
    transcriptSaved: "Transcript saved",
    runAsrCorrection: "Generate suggestions",
    asrModel: "ASR correction model",
    asrModelHelp: "Choose the model profile used for subtitle correction.",
    asrUserContext: "Additional reference info",
    asrUserContextHelp: "Add confirmed terms, names, products, and recurring ASR mistakes. The model treats this as high-priority context.",
    asrUserContextPlaceholder: "",
    noModelProfiles: "No model profiles yet",
    configureModelProfiles: "Manage ASR model profiles",
    asrCorrectionApiUnavailable: "The ASR correction API is not available. Restart the backend service and try again.",
    asrProgressTitle: "ASR correction running",
    asrProgressElapsed: "Elapsed",
    asrProgressUpdated: "Last update",
    asrProgressStale: "The backend status has not updated for over 30 seconds. The model API may be taking too long to respond.",
    asrPhaseQueued: "Queued",
    asrPhasePreparing: "Preparing request",
    asrPhaseCandidate: "Finding suspicious terms",
    asrPhaseSearch: "Searching evidence",
    asrPhaseBackground: "Synthesizing search background",
    asrPhaseReview: "Generating suggestions",
    asrPhaseModelRequest: "Sending model request",
    asrPhaseModelWait: "Waiting for model",
    asrPhaseModelParse: "Parsing model response",
    asrPhaseFinalizing: "Finalizing results",
    asrPhaseComplete: "Complete",
    asrPhaseFailed: "Failed",
    searchCalibration: "Search validation",
    searchCalibrationOn: "Search on",
    searchCalibrationOff: "Search off",
    searchProvider: "Search service",
    searchApiKey: "Search API key",
    firecrawlBaseUrl: "Firecrawl URL",
    searchResultLimit: "Results",
    correctionSuggestions: "Change suggestions",
    noCorrectionSuggestions: "No suggestions yet.",
    asrBeforeTranscript: "Before",
    asrAfterTranscript: "After preview",
    expandSuggestions: "Expand",
    collapseSuggestions: "Collapse",
    previousSuggestion: "Previous",
    nextSuggestion: "Next",
    rerunAsrCorrection: "Run again",
    saveAcceptedChanges: "Auto-save subtitles after accept",
    sortSuggestionsByConfidence: "Sort by confidence, high to low",
    acceptConfidencePrefix: "Accept suggestions at",
    acceptConfidenceSuffix: "% confidence or higher",
    acceptConfidenceAction: "Accept high-confidence suggestions",
    modelCalibration: "Model validation",
    suggestionDetail: "Reason / evidence",
    originalSpanNotFound: "Original span not found",
    candidateSpan: "Candidate span",
    acceptChange: "Accept",
    rejectChange: "Reject",
    acceptAllChanges: "Accept all",
    originalText: "Original",
    correctedText: "Suggested",
    confidence: "Confidence",
    evidence: "Evidence",
    reason: "Reason",
    pendingChanges: "Pending",
    acceptedChanges: "Accepted",
    rejectedChanges: "Rejected",
    noAsrTranscript: "Extract subtitles before opening ASR correction.",
    noVideo: "No video loaded",
    notEmbeddable: "This source is not embeddable yet. Transcript navigation still works.",
    bilibiliEmbedUnavailable: "Bilibili off-site playback does not provide subtitle timeline control. Cache the video for the best experience.",
    forceStream: "Force stream",
    noTranscript: "No transcript loaded.",
    noTranscriptForStudy: "Open the video and finish subtitle extraction before translating or generating a study map.",
    guide: "Guide",
    outline: "Outline",
    detailed: "Interpretation",
    high: "Detailed",
    selectFirst: "Select or extract a course first.",
    noStudy: "This course has a transcript but no AI study map yet.",
    generateStudy: "Generate study map",
    regenerateGuide: "Regenerate guide",
    regenerateOutline: "Regenerate outline",
    regenerateDetailed: "Regenerate interpretation",
    regenerateHigh: "Regenerate detailed",
    studyActionHint: "Study content uses the current output language. Regenerate after changing it.",
    deleteCourse: "Delete course",
    deleteCourseConfirm: "Delete this course from the library? Local cache and subtitle files will be removed too.",
    editTitle: "Edit title",
    saveTitle: "Save title",
    cancelTitleEdit: "Cancel title edit",
    courseTitle: "Course title",
    courseTranslatedTitle: "Translated title",
    courseCollection: "Collection",
    courseCollectionFallback: "Unfiled",
    emptyCollection: "No courses yet",
    newCollectionPrompt: "Enter a new collection name",
    collapseCollection: "Collapse collection",
    expandCollection: "Expand collection",
    editCollection: "Edit collection",
    deleteCollection: "Delete collection",
    deleteCollectionConfirm: "Delete this collection? Courses stay in the library and move to Unfiled.",
    saveCollection: "Save collection",
    cancelCollectionEdit: "Cancel collection edit",
    collectionTitle: "Collection name",
    collectionTitleRequired: "Collection name is required.",
    courseIndex: "Course no.",
    courseTitleRequired: "Course title is required.",
    moveCourseUp: "Move course up",
    moveCourseDown: "Move course down",
    moveCollectionUp: "Move collection up",
    moveCollectionDown: "Move collection down",
    removeLocalCache: "Remove cache",
    removeLocalCacheConfirm: "Remove this course's local video cache? Transcript and study map will stay.",
    regenerateStudy: "Regenerate",
    prerequisites: "Prerequisites",
    thoughtPrompts: "Thought prompts",
    reviewSuggestions: "Review suggestions",
    noPrerequisites: "No prerequisites flagged.",
    noPrompts: "No prompts generated.",
    noReviews: "No review suggestions.",
    unknownError: "Unknown error",
    outputZh: "中文",
    outputEn: "English",
    outputJa: "日本語",
    sourceOnly: "Source only",
    targetOnly: "Translation only",
    bilingual: "Bilingual",
    hideCaption: "Hide captions",
    sourceLabel: "Source",
    targetLabel: "Target",
    videoCaption: "Video captions",
    captionOverlay: "Overlay",
    captionPanel: "Caption bar",
    fullscreenVideo: "Fullscreen",
    exitFullscreen: "Exit fullscreen",
    fullscreenEscHint: "Press Esc to exit fullscreen",
    copyUrl: "Copy URL",
    outlineLevel1: "L1",
    outlineLevel2: "L2",
    outlineExpandAll: "All",
  },
} satisfies Record<UiLanguage, Record<string, string>>;

const DEFAULT_LAYOUT = {
  leftWidth: 270,
  rightWidth: 600,
  playerHeight: 440,
};
const MIN_LEFT_WIDTH = 210;
const MAX_LEFT_WIDTH = 420;
const MIN_RIGHT_WIDTH = 360;
const MAX_RIGHT_WIDTH = 880;
const MIN_MAIN_WIDTH = 420;
const MIN_ASR_REVIEW_WIDTH = 340;
const MAX_ASR_REVIEW_WIDTH = 760;
const MIN_ASR_EDITOR_WIDTH = 520;
const MIN_PLAYER_HEIGHT_OVERLAY = 390;
const MIN_PLAYER_HEIGHT_PANEL = 500;
const MANUAL_COLLECTIONS_STORAGE_KEY = "course-navigator-manual-collections";
const COLLAPSED_COLLECTIONS_STORAGE_KEY = "course-navigator-collapsed-collections";
const COLLECTION_ORDER_STORAGE_KEY = "course-navigator-collection-order";
const TIME_MAP_AUTO_OPEN_STORAGE_KEY = "course-navigator-time-map-auto-open";
const SELECTED_COURSE_STORAGE_KEY = "course-navigator-last-selected-course";
const ASR_SAVE_ACCEPTED_CHANGES_STORAGE_KEY = "course-navigator-asr-save-accepted-changes";
const ASR_SORT_BY_CONFIDENCE_STORAGE_KEY = "course-navigator-asr-sort-by-confidence";
const TASK_PARAMETER_KEYS: TaskParameterKey[] = [
  "title_translation",
  "subtitle_translation",
  "asr_correction",
  "semantic_segmentation",
  "guide",
  "outline",
  "interpretation",
  "high_fidelity",
];

const EMPTY_SETTINGS_DRAFT: SettingsDraft = {
  profiles: [],
  active_profile_id: "",
  translation_model_id: "",
  learning_model_id: "",
  global_model_id: "",
  asr_model_id: "",
  study_detail_level: "faithful",
  task_parameters: emptyTaskParameterDrafts(),
};
const EMPTY_ONLINE_ASR_DRAFT: OnlineAsrDraft = {
  provider: "none",
  openai_api_key: "",
  openai_api_key_preview: null,
  groq_api_key: "",
  groq_api_key_preview: null,
  xai_api_key: "",
  xai_api_key_preview: null,
  custom_base_url: "",
  custom_model: "",
  custom_api_key: "",
  custom_api_key_preview: null,
};

export function App() {
  const [url, setUrl] = useState("");
  const [mode, setMode] = useState<ExtractMode>("browser");
  const [browser, setBrowser] = useState("chrome");
  const [cookiesPath, setCookiesPath] = useState("");
  const [subtitleSource, setSubtitleSource] = useState<SubtitleSourceChoice>("subtitles");
  const [uiLanguage, setUiLanguage] = useState<UiLanguage>("zh-CN");
  const [outputLanguage, setOutputLanguage] = useState<OutputLanguage>("zh-CN");
  const [videoCaptionDisplayMode, setVideoCaptionDisplayMode] = useState<CaptionDisplayMode>("bilingual");
  const [videoCaptionPlacement, setVideoCaptionPlacement] = useState<CaptionPlacement>("overlay");
  const [transcriptDisplayMode, setTranscriptDisplayMode] = useState<TextDisplayMode>("bilingual");
  const [fullscreenRequestId, setFullscreenRequestId] = useState(0);
  const [items, setItems] = useState<CourseItem[]>([]);
  const [selected, setSelected] = useState<CourseItem | null>(null);
  const [view, setView] = useState<"workspace" | "asr">("workspace");
  const [forcedBilibiliEmbedIds, setForcedBilibiliEmbedIds] = useState<string[]>([]);
  const [activeTab, setActiveTab] = useState<AiTab>("guide");
  const [sourceMode, setSourceMode] = useState<SourceMode>("embed");
  const [seekTime, setSeekTime] = useState(0);
  const [playheadTime, setPlayheadTime] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<StudyJobStatus | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [asrSettingsOpen, setAsrSettingsOpen] = useState(false);
  const [modelSettings, setModelSettings] = useState<ModelSettings | null>(null);
  const [settingsDraft, setSettingsDraft] = useState<SettingsDraft>(EMPTY_SETTINGS_DRAFT);
  const [onlineAsrSettings, setOnlineAsrSettings] = useState<OnlineAsrSettings | null>(null);
  const [onlineAsrDraft, setOnlineAsrDraft] = useState<OnlineAsrDraft>(EMPTY_ONLINE_ASR_DRAFT);
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [settingsMessage, setSettingsMessage] = useState<string | null>(null);
  const [roleSettingsBusy, setRoleSettingsBusy] = useState(false);
  const [roleSettingsMessage, setRoleSettingsMessage] = useState<string | null>(null);
  const [layout, setLayout] = useState(DEFAULT_LAYOUT);
  const [timeMapOpen, setTimeMapOpen] = useState(false);
  const [editingTitleId, setEditingTitleId] = useState<string | null>(null);
  const [editingCourseDraft, setEditingCourseDraft] = useState<CourseEditDraft>({
    title: "",
    translated_title: "",
    collection_title: "",
    course_index: "",
  });
  const [manualCollections, setManualCollections] = useState<string[]>(() => loadManualCollections());
  const [collapsedCollections, setCollapsedCollections] = useState<string[]>(() =>
    loadStoredStrings(COLLAPSED_COLLECTIONS_STORAGE_KEY),
  );
  const [collectionOrder, setCollectionOrder] = useState<string[]>(() => loadStoredStrings(COLLECTION_ORDER_STORAGE_KEY));
  const [exportModalOpen, setExportModalOpen] = useState(false);
  const [exportSelectedIds, setExportSelectedIds] = useState<string[]>([]);
  const [exportMessage, setExportMessage] = useState("");
  const [importBusy, setImportBusy] = useState(false);
  const [importMessage, setImportMessage] = useState<string | null>(null);
  const [timeMapAutoOpen, setTimeMapAutoOpen] = useState(() =>
    loadBooleanPreference(TIME_MAP_AUTO_OPEN_STORAGE_KEY, true),
  );
  const [editingCollectionKey, setEditingCollectionKey] = useState<string | null>(null);
  const [editingCollectionDraft, setEditingCollectionDraft] = useState("");
  const [savingCollectionKey, setSavingCollectionKey] = useState<string | null>(null);
  const [savingTitleId, setSavingTitleId] = useState<string | null>(null);
  const [activeJobKind, setActiveJobKind] = useState<"study" | "translation" | "download" | "extract" | null>(null);
  const workspaceRef = useRef<HTMLElement | null>(null);
  const mainColumnRef = useRef<HTMLElement | null>(null);
  const dragCleanupRef = useRef<(() => void) | null>(null);
  const importFileInputRef = useRef<HTMLInputElement | null>(null);
  const subtitleUploadInputRef = useRef<HTMLInputElement | null>(null);
  const copy = COPY[uiLanguage];

  useEffect(() => {
    listItems()
      .then((loaded) => {
        setItems(loaded);
        selectCourse(initialSelectedCourse(loaded));
      })
      .catch((err: unknown) => setError(errorMessage(err, copy.unknownError)));
  }, []);

  useEffect(() => {
    getModelSettings()
      .then((settings) => {
        setModelSettings(settings);
        setSettingsDraft(draftFromModelSettings(settings));
      })
      .catch(() => undefined);
    getOnlineAsrSettings()
      .then((settings) => {
        setOnlineAsrSettings(settings);
        setOnlineAsrDraft(draftFromOnlineAsrSettings(settings));
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    setSourceMode(selected?.local_video_path ? "local" : "embed");
    setSeekTime(0);
    setPlayheadTime(0);
  }, [selected?.id, selected?.local_video_path]);

  useEffect(() => {
    const minPlayerHeight = playerHeightMinimum(videoCaptionPlacement);
    setLayout((current) => {
      if (current.playerHeight >= minPlayerHeight) return current;
      return {
        ...current,
        playerHeight: minPlayerHeight,
      };
    });
  }, [videoCaptionPlacement]);

  useEffect(() => () => dragCleanupRef.current?.(), []);

  const selectedStudy = selected?.study ?? null;
  const translatedTranscript = selectedStudy?.translated_transcript ?? [];
  const selectedHasStudy = hasStudyMaterial(selectedStudy);
  const selectedIsBilibili = selected ? isBilibiliItem(selected) : false;
  const forcedBilibiliEmbed = selected ? forcedBilibiliEmbedIds.includes(selected.id) : false;
  const showVideoCaptionDock = Boolean(selected) && (!selectedIsBilibili || sourceMode === "local" || forcedBilibiliEmbed);
  const videoCaptionControlsAvailable = !(selectedIsBilibili && sourceMode === "embed");
  const timeMapVisible = selectedHasStudy && timeMapOpen;
  const leftRailClassName = timeMapVisible
    ? "left-rail"
    : selectedHasStudy
      ? "left-rail time-map-mini"
      : "left-rail time-map-collapsed";
  const collectionOptions = useMemo(
    () => collectionNames(items, manualCollections, copy.courseCollectionFallback),
    [items, manualCollections, copy.courseCollectionFallback],
  );
  const groupedItems = useMemo(
    () => groupCourseItems(items, copy.courseCollectionFallback, manualCollections, collectionOrder),
    [items, copy.courseCollectionFallback, manualCollections, collectionOrder],
  );
  const collapsedCollectionKeys = useMemo(() => new Set(collapsedCollections), [collapsedCollections]);

  useEffect(() => {
    setTimeMapOpen(selectedHasStudy && timeMapAutoOpen);
  }, [selected?.id, selectedHasStudy, timeMapAutoOpen]);

  function selectCourse(item: CourseItem | null) {
    setSelected(item);
    if (item?.source_url) {
      setUrl(item.source_url);
    }
    if (item && !isPreviewItem(item)) {
      saveSelectedCourseId(item.id);
    }
  }

  async function refreshItems(nextSelectedId?: string) {
    const loaded = await listItems();
    setItems(loaded);
    if (nextSelectedId) {
      selectCourse(loaded.find((item) => item.id === nextSelectedId) ?? loaded[0] ?? null);
    }
  }

  function upsertCourseItem(item: CourseItem) {
    setItems((current) => current.map((entry) => (entry.id === item.id ? item : entry)));
    setSelected((current) => (current?.id === item.id ? item : current));
  }

  async function handleOpenUrl() {
    const normalizedUrl = url.trim();
    if (!normalizedUrl) return;
    if (subtitleSource === "local_upload") {
      openLocalSubtitlePicker();
      return;
    }
    setError(null);
    setJobStatus(null);
    setSourceMode("embed");
    setSeekTime(0);
    setPlayheadTime(0);
    const existing = findExistingItemForUrl(items, normalizedUrl);
    if (existing?.transcript.length) {
      selectCourse(existing);
      return;
    }
    try {
      let previewItem = existing;
      if (existing) {
        selectCourse(existing);
      }
      if (!previewItem?.metadata) {
        previewItem = await previewUrlToItem(normalizedUrl);
      }
      if (previewItem.transcript.length) {
        return;
      }
      if (usesBackgroundSubtitleExtraction(subtitleSource)) {
        await runExtractJob(normalizedUrl);
      } else {
        await extractUrlToItem(normalizedUrl);
      }
    } catch (err) {
      setError(extractionErrorMessage(err, mode, browser, copy.unknownError));
    } finally {
      setBusy(null);
      setJobStatus(null);
      setActiveJobKind(null);
    }
  }

  async function handleGetSubtitles() {
    if (subtitleSource === "local_upload") {
      openLocalSubtitlePicker();
      return;
    }
    const normalizedUrl = url.trim() || selected?.source_url.trim() || "";
    if (!normalizedUrl) return;
    const existing = findExistingItemForUrl(items, normalizedUrl);
    const selectedMatchesUrl = selected ? canonicalSourceKey(selected.source_url) === canonicalSourceKey(normalizedUrl) : false;
    if ((existing?.transcript.length || (selectedMatchesUrl && selected?.transcript.length)) && !window.confirm(copy.getSubtitlesConfirm)) {
      return;
    }
    setError(null);
    setJobStatus(null);
    setSourceMode("embed");
    setSeekTime(0);
    setPlayheadTime(0);
    try {
      if (usesBackgroundSubtitleExtraction(subtitleSource)) {
        await runExtractJob(normalizedUrl);
      } else {
        await extractUrlToItem(normalizedUrl);
      }
    } catch (err) {
      setError(extractionErrorMessage(err, mode, browser, copy.unknownError));
    } finally {
      setBusy(null);
      setJobStatus(null);
      setActiveJobKind(null);
    }
  }

  function handleSubtitleSourceChange(nextSource: SubtitleSourceChoice) {
    setSubtitleSource(nextSource);
    if (nextSource === "local_upload") {
      window.setTimeout(() => openLocalSubtitlePicker(), 0);
    }
  }

  function openLocalSubtitlePicker() {
    subtitleUploadInputRef.current?.click();
  }

  async function handleLocalSubtitleFile(event: ReactChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0] ?? null;
    event.currentTarget.value = "";
    if (!file) return;
    setError(null);
    setJobStatus(null);
    setBusy(copy.importingLocalSubtitle);
    try {
      const normalizedUrl = url.trim();
      const selectedMatchesUrl =
        selected && normalizedUrl ? canonicalSourceKey(selected.source_url) === canonicalSourceKey(normalizedUrl) : true;
      let target = selectedMatchesUrl && selected && !isPreviewItem(selected) ? selected : null;
      if (!target && normalizedUrl) {
        target = await previewUrlToItem(normalizedUrl);
      }
      if (!target) {
        throw new Error(copy.localSubtitleNoTarget);
      }
      const text = await file.text();
      const transcript = parseUploadedSubtitleText(text, file.name, target.duration);
      if (!transcript.length) {
        throw new Error(copy.localSubtitleEmpty);
      }
      await handleSaveWorkbenchTranscript(target.id, transcript);
      setSubtitleSource("local_upload");
    } catch (err) {
      setError(errorMessage(err, copy.unknownError));
    } finally {
      setBusy(null);
      setActiveJobKind(null);
    }
  }

  function openExportModal() {
    setExportSelectedIds(selected && !isPreviewItem(selected) ? [selected.id] : []);
    setExportMessage("");
    setExportModalOpen(true);
  }

  function toggleExportCourse(itemId: string) {
    setExportSelectedIds((current) =>
      current.includes(itemId) ? current.filter((id) => id !== itemId) : [...current, itemId],
    );
  }

  function toggleExportGroup(group: LibraryCollectionGroup) {
    const groupIds = group.items.map((item) => item.id);
    if (!groupIds.length) return;
    setExportSelectedIds((current) => {
      const selectedSet = new Set(current);
      const allSelected = groupIds.every((id) => selectedSet.has(id));
      if (allSelected) {
        return current.filter((id) => !groupIds.includes(id));
      }
      return mergeStringKeys([...current, ...groupIds]);
    });
  }

  function handleExportCourses() {
    const selectedSet = new Set(exportSelectedIds);
    if (!selectedSet.size) {
      setError(copy.noExportSelection);
      return;
    }
    const selectedItems = items.filter((item) => selectedSet.has(item.id));
    if (selectedItems.some((item) => !item.transcript.length)) {
      setError(copy.noTranscript);
      return;
    }
    const fullCollectionKeys = new Set(
      groupedItems
        .filter((group) => group.items.length > 0 && group.items.every((item) => selectedSet.has(item.id)))
        .map((group) => group.key),
    );
    const unfiledKey = collectionStorageKey("");
    const packageItems = sortCourseItems(selectedItems).map((item) => {
      const itemCollectionKey = collectionStorageKey(item.collection_title);
      const keepCollection = itemCollectionKey !== unfiledKey && fullCollectionKeys.has(itemCollectionKey);
      return {
        id: item.id,
        source_url: item.source_url,
        title: item.title,
        custom_title: item.custom_title ?? false,
        collection_title: keepCollection ? item.collection_title ?? "" : null,
        course_index: keepCollection ? item.course_index ?? null : null,
        sort_order: keepCollection ? item.sort_order ?? null : null,
        duration: item.duration,
        created_at: item.created_at,
        transcript: item.transcript,
        transcript_source: "imported" as const,
        metadata: item.metadata ?? null,
        study: item.study ?? null,
      };
    });
    const packagePayload: CourseSharePackage = {
      format: "course-navigator-share",
      version: 1,
      exported_at: new Date().toISOString(),
      message: exportMessage.trim() || null,
      items: packageItems,
    };
    downloadJsonFile(packagePayload, coursePackageFileName(packageItems));
    setExportModalOpen(false);
    setExportMessage("");
    setExportSelectedIds([]);
  }

  async function handleImportPackageFile(event: ReactChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (!file) return;
    setImportBusy(true);
    setError(null);
    try {
      const raw = await file.text();
      const payload = JSON.parse(raw) as CourseSharePackage;
      const response = await importCoursePackage(payload);
      const loaded = await listItems();
      setItems(loaded);
      const firstImported = response.items[0];
      selectCourse(firstImported ? loaded.find((item) => item.id === firstImported.id) ?? firstImported : initialSelectedCourse(loaded));
      if (response.message?.trim()) {
        setImportMessage(response.message.trim());
      }
    } catch (err) {
      setError(`${copy.importPackageFailed}: ${errorMessage(err, copy.unknownError)}`);
    } finally {
      setImportBusy(false);
    }
  }

  async function handleTranslate() {
    if (!selected?.transcript.length) return;
    setError(null);
    try {
      await runTranslationJob(selected.id);
    } catch (err) {
      setError(errorMessage(err, copy.unknownError));
    } finally {
      setBusy(null);
      setJobStatus(null);
      setActiveJobKind(null);
    }
  }

  async function handleGenerateStudy() {
    if (!selected?.transcript.length) {
      setError(copy.noTranscriptForStudy);
      return;
    }
    setError(null);
    try {
      await runStudyJob(selected.id, hasStudyMaterial(selected.study) ? activeTab : "all");
    } catch (err) {
      setError(errorMessage(err, copy.unknownError));
    } finally {
      setBusy(null);
      setJobStatus(null);
      setActiveJobKind(null);
    }
  }

  async function runStudyJob(itemId: string, section: StudySection = "all") {
    setActiveJobKind("study");
    setBusy(section === "all" ? copy.generating : regenerateLabelForTab(section, copy));
    const firstStatus = await startStudyJob(itemId, outputLanguage, section);
    setJobStatus(firstStatus);
    let current = firstStatus;
    while (current.status === "queued" || current.status === "running") {
      await delay(1000);
      current = await getStudyJob(firstStatus.job_id);
      setJobStatus(current);
      setBusy(`${current.message} ${current.progress}%`);
      if (current.status === "running" && current.phase === "translation") {
        await refreshItems(itemId);
      }
    }
    if (current.status === "failed") {
      throw new Error(current.error ?? current.message);
    }
    await refreshItems(itemId);
  }

  async function runTranslationJob(itemId: string) {
    setActiveJobKind("translation");
    setBusy(copy.translateSubtitles);
    const firstStatus = await startTranslationJob(itemId, outputLanguage);
    setJobStatus(firstStatus);
    let current = firstStatus;
    while (current.status === "queued" || current.status === "running") {
      await delay(1000);
      current = await getStudyJob(firstStatus.job_id);
      setJobStatus(current);
      setBusy(`${current.message} ${current.progress}%`);
      if (current.status === "running" && current.phase === "translation") {
        await refreshItems(itemId);
      }
    }
    if (current.status === "failed") {
      throw new Error(current.error ?? current.message);
    }
    await refreshItems(itemId);
  }

  async function runDownloadJob(itemId: string) {
    const item = items.find((entry) => entry.id === itemId);
    if (!item) return;
    setActiveJobKind("download");
    setBusy(`${copy.caching} 0%`);
    const firstStatus = await startDownloadJob(itemId, {
      url: item.source_url,
      mode,
      browser,
      cookies_path: mode === "cookies" ? cookiesPath : undefined,
    });
    setJobStatus(firstStatus);
    let current = firstStatus;
    while (current.status === "queued" || current.status === "running") {
      await delay(1000);
      current = await getStudyJob(firstStatus.job_id);
      setJobStatus(current);
      setBusy(`${current.message} ${current.progress}%`);
    }
    if (current.status === "failed") {
      throw new Error(current.error ?? current.message);
    }
    await refreshItems(itemId);
    setSourceMode("local");
  }

  async function runExtractJob(sourceUrl: string) {
    setActiveJobKind("extract");
    setBusy(`${copy.extracting} 0%`);
    const firstStatus = await startExtractJob({
      url: sourceUrl,
      mode,
      browser,
      cookies_path: mode === "cookies" ? cookiesPath : undefined,
      subtitle_source: requestTranscriptSource(subtitleSource),
    });
    setJobStatus(firstStatus);
    let current = firstStatus;
    while (current.status === "queued" || current.status === "running") {
      await delay(1000);
      current = await getStudyJob(firstStatus.job_id);
      setJobStatus(current);
      setBusy(`${current.message} ${current.progress}%`);
    }
    if (current.status === "failed") {
      throw new Error(current.error ?? current.message);
    }
    await refreshItems(current.item_id || undefined);
  }

  async function handleDownload() {
    if (!selected || isPreviewItem(selected)) return;
    setError(null);
    try {
      await runDownloadJob(selected.id);
    } catch (err) {
      setError(errorMessage(err, copy.unknownError));
    } finally {
      setBusy(null);
      setJobStatus(null);
      setActiveJobKind(null);
    }
  }

  async function handleRemoveLocalCache() {
    if (!selected?.local_video_path) return;
    if (!window.confirm(copy.removeLocalCacheConfirm)) return;
    setError(null);
    try {
      const next = await deleteLocalVideo(selected.id);
      await refreshItems(next.id);
      setSourceMode("embed");
    } catch (err) {
      setError(errorMessage(err, copy.unknownError));
    }
  }

  async function handleDeleteCourse(item: CourseItem) {
    if (!window.confirm(copy.deleteCourseConfirm)) return;
    setError(null);
    try {
      await deleteCourse(item.id);
      const loaded = await listItems();
      setItems(loaded);
      if (selected?.id === item.id) {
        selectCourse(initialSelectedCourse(loaded));
      }
    } catch (err) {
      setError(errorMessage(err, copy.unknownError));
    }
  }

  async function handleCopyCourseUrl(item: CourseItem) {
    try {
      await navigator.clipboard?.writeText(item.source_url);
    } catch {
      setError(item.source_url);
    }
  }

  function startEditingTitle(item: CourseItem) {
    setEditingTitleId(item.id);
    setEditingCourseDraft({
      title: item.title,
      translated_title: item.study?.translated_title ?? "",
      collection_title: item.collection_title ?? "",
      course_index: formatCourseIndexInput(item.course_index),
    });
  }

  function cancelEditingTitle() {
    setEditingTitleId(null);
    setEditingCourseDraft({ title: "", translated_title: "", collection_title: "", course_index: "" });
  }

  function handleAddCollection() {
    const name = window.prompt(copy.newCollectionPrompt)?.trim();
    if (!name) return;
    setManualCollections((current) => {
      const next = mergeCollectionNames([...current, name]);
      saveStoredStrings(MANUAL_COLLECTIONS_STORAGE_KEY, next);
      return next;
    });
    setCollectionOrder((current) => {
      const next = mergeStringKeys([...current, collectionStorageKey(name)]);
      saveStoredStrings(COLLECTION_ORDER_STORAGE_KEY, next);
      return next;
    });
  }

  function setTimeMapPreference(nextOpen: boolean) {
    setTimeMapAutoOpen(nextOpen);
    try {
      window.localStorage.setItem(TIME_MAP_AUTO_OPEN_STORAGE_KEY, String(nextOpen));
    } catch {
      // Local storage is a convenience; the UI state still updates if it is unavailable.
    }
    setTimeMapOpen(selectedHasStudy && nextOpen);
  }

  function toggleCollectionCollapse(collectionKey: string) {
    setCollapsedCollections((current) => {
      const next = current.includes(collectionKey)
        ? current.filter((key) => key !== collectionKey)
        : [...current, collectionKey];
      saveStoredStrings(COLLAPSED_COLLECTIONS_STORAGE_KEY, next);
      return next;
    });
  }

  function handleMoveCollection(group: LibraryCollectionGroup, direction: -1 | 1) {
    const visibleKeys = groupedItems.map((entry) => entry.key);
    const index = visibleKeys.indexOf(group.key);
    const targetIndex = index + direction;
    if (index < 0 || targetIndex < 0 || targetIndex >= visibleKeys.length) return;
    const nextVisibleKeys = [...visibleKeys];
    [nextVisibleKeys[index], nextVisibleKeys[targetIndex]] = [nextVisibleKeys[targetIndex], nextVisibleKeys[index]];
    setCollectionOrder((current) => {
      const visibleSet = new Set(visibleKeys);
      const hiddenKeys = current.filter((key) => !visibleSet.has(key));
      const next = mergeStringKeys([...nextVisibleKeys, ...hiddenKeys]);
      saveStoredStrings(COLLECTION_ORDER_STORAGE_KEY, next);
      return next;
    });
  }

  function startEditingCollection(group: LibraryCollectionGroup) {
    setEditingCollectionKey(group.key);
    setEditingCollectionDraft(group.value);
  }

  function cancelEditingCollection() {
    setEditingCollectionKey(null);
    setEditingCollectionDraft("");
  }

  async function handleRenameCollection(group: LibraryCollectionGroup) {
    const nextTitle = editingCollectionDraft.trim();
    if (!nextTitle) {
      setError(copy.collectionTitleRequired);
      return;
    }
    const nextKey = collectionStorageKey(nextTitle);
    setError(null);
    setSavingCollectionKey(group.key);
    try {
      const affectedItems = items.filter((item) => collectionStorageKey(item.collection_title) === group.key);
      const updatedItems = await Promise.all(
        affectedItems.map((item) =>
          updateCourseItem(item.id, {
            collection_title: nextTitle,
            course_index: item.course_index ?? null,
            sort_order: item.sort_order ?? null,
          }),
        ),
      );
      const updatedById = new Map(updatedItems.map((item) => [item.id, item]));
      setItems((current) => sortCourseItems(current.map((item) => updatedById.get(item.id) ?? item)));
      setSelected((current) => (current ? updatedById.get(current.id) ?? current : current));
      setManualCollections((current) => {
        const renamed = current.map((name) => (collectionStorageKey(name) === group.key ? nextTitle : name));
        const next = mergeCollectionNames(affectedItems.length ? renamed : [...renamed, nextTitle]);
        saveStoredStrings(MANUAL_COLLECTIONS_STORAGE_KEY, next);
        return next;
      });
      setCollapsedCollections((current) => {
        const next = mergeStringKeys(current.map((key) => (key === group.key ? nextKey : key)));
        saveStoredStrings(COLLAPSED_COLLECTIONS_STORAGE_KEY, next);
        return next;
      });
      setCollectionOrder((current) => {
        const next = mergeStringKeys(current.map((key) => (key === group.key ? nextKey : key)));
        saveStoredStrings(COLLECTION_ORDER_STORAGE_KEY, next);
        return next;
      });
      cancelEditingCollection();
    } catch (err) {
      setError(errorMessage(err, copy.unknownError));
    } finally {
      setSavingCollectionKey(null);
    }
  }

  async function handleDeleteCollection(group: LibraryCollectionGroup) {
    if (group.key === collectionStorageKey("")) return;
    if (!window.confirm(copy.deleteCollectionConfirm)) return;
    setError(null);
    setSavingCollectionKey(group.key);
    try {
      const affectedItems = items.filter((item) => collectionStorageKey(item.collection_title) === group.key);
      const updatedItems = await Promise.all(
        affectedItems.map((item) =>
          updateCourseItem(item.id, {
            collection_title: null,
            course_index: null,
            sort_order: null,
          }),
        ),
      );
      const updatedById = new Map(updatedItems.map((item) => [item.id, item]));
      setItems((current) => sortCourseItems(current.map((item) => updatedById.get(item.id) ?? item)));
      setSelected((current) => (current ? updatedById.get(current.id) ?? current : current));
      setManualCollections((current) => {
        const next = current.filter((name) => collectionStorageKey(name) !== group.key);
        saveStoredStrings(MANUAL_COLLECTIONS_STORAGE_KEY, next);
        return next;
      });
      setCollapsedCollections((current) => {
        const next = current.filter((key) => key !== group.key);
        saveStoredStrings(COLLAPSED_COLLECTIONS_STORAGE_KEY, next);
        return next;
      });
      setCollectionOrder((current) => {
        const next = current.filter((key) => key !== group.key);
        saveStoredStrings(COLLECTION_ORDER_STORAGE_KEY, next);
        return next;
      });
      if (editingCollectionKey === group.key) {
        cancelEditingCollection();
      }
    } catch (err) {
      setError(errorMessage(err, copy.unknownError));
    } finally {
      setSavingCollectionKey(null);
    }
  }

  async function handleRenameCourse(item: CourseItem) {
    const title = editingCourseDraft.title.trim();
    if (!title) {
      setError(copy.courseTitleRequired);
      return;
    }
    const courseIndex = parseCourseIndex(editingCourseDraft.course_index);
    setError(null);
    setSavingTitleId(item.id);
    try {
      const renamed = await updateCourseItem(item.id, {
        title,
        translated_title: editingCourseDraft.translated_title.trim() || null,
        collection_title: editingCourseDraft.collection_title.trim() || null,
        course_index: courseIndex,
        sort_order: courseIndex ?? item.sort_order ?? null,
      });
      upsertCourseItem(renamed);
      cancelEditingTitle();
    } catch (err) {
      setError(errorMessage(err, copy.unknownError));
    } finally {
      setSavingTitleId(null);
    }
  }

  async function handleMoveCourse(item: CourseItem, direction: -1 | 1) {
    const group = courseGroupForItem(items, item);
    const index = group.findIndex((entry) => entry.id === item.id);
    if (index < 0) return;
    const swapWith = group[index + direction];
    if (!swapWith) return;
    const normalized = group.map((entry, entryIndex) => ({
      ...entry,
      course_index: entry.course_index ?? entryIndex + 1,
    }));
    const current = normalized[index];
    const target = normalized[index + direction];
    setError(null);
    try {
      const [nextCurrent, nextTarget] = await Promise.all([
        updateCourseItem(current.id, {
          course_index: target.course_index,
          sort_order: target.course_index,
        }),
        updateCourseItem(target.id, {
          course_index: current.course_index,
          sort_order: current.course_index,
        }),
      ]);
      setItems((existing) =>
        sortCourseItems(
          existing.map((entry) =>
            entry.id === nextCurrent.id ? nextCurrent : entry.id === nextTarget.id ? nextTarget : entry,
          ),
        ),
      );
      setSelected((currentSelected) =>
        currentSelected?.id === nextCurrent.id ? nextCurrent : currentSelected?.id === nextTarget.id ? nextTarget : currentSelected,
      );
    } catch (err) {
      setError(errorMessage(err, copy.unknownError));
    }
  }

  function seek(seconds: number) {
    const nextTime = Math.max(0, seconds);
    setSeekTime(nextTime);
    setPlayheadTime(nextTime);
  }

  function switchSource(nextMode: SourceMode) {
    setSourceMode(nextMode);
    setSeekTime(Math.max(0, playheadTime));
  }

  function forceBilibiliStreaming(itemId: string) {
    setForcedBilibiliEmbedIds((current) => (current.includes(itemId) ? current : [...current, itemId]));
    setSourceMode("embed");
  }

  async function previewUrlToItem(sourceUrl: string): Promise<CourseItem> {
    setBusy(copy.previewing);
    const item = await previewCourse({
      url: sourceUrl,
      mode,
      browser,
      cookies_path: mode === "cookies" ? cookiesPath : undefined,
      subtitle_source: requestTranscriptSource(subtitleSource),
    });
    selectCourse(item);
    setItems((current) => sortCourseItems([item, ...current.filter((entry) => entry.id !== item.id)]));
    return item;
  }

  async function extractUrlToItem(sourceUrl: string): Promise<CourseItem> {
    setBusy(copy.extracting);
    const item = await extractCourse({
      url: sourceUrl,
      mode,
      browser,
      cookies_path: mode === "cookies" ? cookiesPath : undefined,
      subtitle_source: requestTranscriptSource(subtitleSource),
    });
    selectCourse(item);
    setItems((current) => sortCourseItems([item, ...current.filter((entry) => entry.id !== item.id)]));
    return item;
  }

  function startLayoutDrag(kind: LayoutDragKind, event: ReactPointerEvent<HTMLButtonElement>) {
    event.preventDefault();
    dragCleanupRef.current?.();
    const workspaceBox = workspaceRef.current?.getBoundingClientRect();
    const mainBox = mainColumnRef.current?.getBoundingClientRect();
    if (!workspaceBox || (kind === "player" && !mainBox)) return;
    const handle = event.currentTarget;
    const pointerId = event.pointerId;
    let active = true;
    let frameId: number | null = null;
    let latestPoint = { x: event.clientX, y: event.clientY };

    const applyLayout = (clientX: number, clientY: number) => {
      setLayout((current) => {
        if (kind === "left") {
          const maxLeft = Math.min(
            MAX_LEFT_WIDTH,
            Math.max(MIN_LEFT_WIDTH, workspaceBox.width - current.rightWidth - MIN_MAIN_WIDTH - 12),
          );
          const leftWidth = clamp(clientX - workspaceBox.left, MIN_LEFT_WIDTH, maxLeft);
          if (leftWidth === current.leftWidth) return current;
          return {
            ...current,
            leftWidth,
          };
        }
        if (kind === "right") {
          const maxRight = Math.min(
            MAX_RIGHT_WIDTH,
            Math.max(MIN_RIGHT_WIDTH, workspaceBox.width - current.leftWidth - MIN_MAIN_WIDTH - 12),
          );
          const rightWidth = clamp(workspaceBox.right - clientX, MIN_RIGHT_WIDTH, maxRight);
          if (rightWidth === current.rightWidth) return current;
          return {
            ...current,
            rightWidth,
          };
        }
        const minPlayerHeight = playerHeightMinimum(videoCaptionPlacement);
        const maxPlayerHeight = Math.max(minPlayerHeight, (mainBox?.height ?? 720) - 190);
        const playerHeight = clamp(clientY - (mainBox?.top ?? 0), minPlayerHeight, maxPlayerHeight);
        if (playerHeight === current.playerHeight) return current;
        return {
          ...current,
          playerHeight,
        };
      });
    };

    const handlePointerMove = (moveEvent: PointerEvent) => {
      latestPoint = { x: moveEvent.clientX, y: moveEvent.clientY };
      if (frameId !== null) return;
      frameId = window.requestAnimationFrame(() => {
        frameId = null;
        applyLayout(latestPoint.x, latestPoint.y);
      });
    };

    const stopDrag = () => {
      if (!active) return;
      active = false;
      if (frameId !== null) {
        window.cancelAnimationFrame(frameId);
        frameId = null;
      }
      handle.removeEventListener("pointermove", handlePointerMove);
      handle.removeEventListener("pointerup", stopDrag);
      handle.removeEventListener("pointercancel", stopDrag);
      handle.removeEventListener("lostpointercapture", stopDrag);
      window.removeEventListener("pointerup", stopDrag);
      window.removeEventListener("blur", stopDrag);
      document.body.classList.remove("is-resizing-layout");
      if (handle.hasPointerCapture?.(pointerId)) {
        handle.releasePointerCapture(pointerId);
      }
      dragCleanupRef.current = null;
    };

    document.body.classList.add("is-resizing-layout");
    handle.setPointerCapture?.(pointerId);
    handle.addEventListener("pointermove", handlePointerMove);
    handle.addEventListener("pointerup", stopDrag);
    handle.addEventListener("pointercancel", stopDrag);
    handle.addEventListener("lostpointercapture", stopDrag);
    window.addEventListener("pointerup", stopDrag);
    window.addEventListener("blur", stopDrag);
    dragCleanupRef.current = stopDrag;
  }

  async function handleSaveSettings() {
    setSettingsBusy(true);
    setSettingsMessage(null);
    try {
      const next = await saveModelSettings({
        profiles: settingsDraft.profiles.map(modelProfileDraftToInput),
        translation_model_id: settingsDraft.translation_model_id,
        learning_model_id: settingsDraft.learning_model_id,
        global_model_id: settingsDraft.global_model_id,
        asr_model_id: settingsDraft.asr_model_id,
        study_detail_level: "faithful",
        task_parameters: taskParameterDraftsToInput(settingsDraft.task_parameters),
      });
      const nextOnlineAsr = await saveOnlineAsrSettings(onlineAsrDraftToInput(onlineAsrDraft));
      setModelSettings(next);
      setSettingsDraft(draftFromModelSettings(next, settingsDraft.active_profile_id));
      setOnlineAsrSettings(nextOnlineAsr);
      setOnlineAsrDraft(draftFromOnlineAsrSettings(nextOnlineAsr));
      setSettingsMessage(copy.settingsSaved);
    } catch (err) {
      setSettingsMessage(errorMessage(err, copy.unknownError));
    } finally {
      setSettingsBusy(false);
    }
  }

  async function handleOnlineAsrProviderChange(provider: OnlineAsrProvider) {
    setOnlineAsrDraft((current) => ({ ...current, provider }));
    setSettingsMessage(null);
    try {
      const next = await saveOnlineAsrSettings({ provider });
      setOnlineAsrSettings(next);
      setOnlineAsrDraft((current) => ({ ...current, provider: next.provider }));
      setSettingsMessage(copy.onlineAsrProviderSaved);
    } catch (err) {
      setSettingsMessage(errorMessage(err, copy.unknownError));
    }
  }

  async function handleSaveModelRole(role: ModelRoleKey, profileId: string) {
    const previousRoleId = settingsDraft[role];
    setSettingsDraft((current) => ({ ...current, [role]: profileId }));
    setRoleSettingsBusy(true);
    setRoleSettingsMessage(copy.modelRolesSaving);
    try {
      const source: ModelSettingsInput = modelSettings
        ? modelSettingsToInput(modelSettings)
        : {
            profiles: settingsDraft.profiles.map(modelProfileDraftToInput),
            translation_model_id: settingsDraft.translation_model_id,
            learning_model_id: settingsDraft.learning_model_id,
            global_model_id: settingsDraft.global_model_id,
            asr_model_id: settingsDraft.asr_model_id,
            study_detail_level: "faithful",
            task_parameters: taskParameterDraftsToInput(settingsDraft.task_parameters),
          };
      const next = await saveModelSettings({ ...source, [role]: profileId });
      setModelSettings(next);
      setSettingsDraft((current) => ({
        ...current,
        translation_model_id: next.translation_model_id,
        learning_model_id: next.learning_model_id,
        global_model_id: next.global_model_id,
        asr_model_id: next.asr_model_id,
        study_detail_level: "faithful",
        task_parameters: taskParametersToDraft(next.task_parameters),
      }));
      setRoleSettingsMessage(copy.modelRolesSaved);
    } catch (err) {
      setSettingsDraft((current) => ({ ...current, [role]: previousRoleId }));
      setRoleSettingsMessage(`${copy.modelRolesSaveFailed}: ${errorMessage(err, copy.unknownError)}`);
    } finally {
      setRoleSettingsBusy(false);
    }
  }

  async function handleSaveAsrModelRole(profileId: string) {
    if (!profileId) return;
    const previousRoleId = settingsDraft.asr_model_id;
    setSettingsDraft((current) => ({ ...current, asr_model_id: profileId }));
    setRoleSettingsBusy(true);
    setRoleSettingsMessage(copy.modelRolesSaving);
    try {
      const source: ModelSettingsInput = modelSettings
        ? modelSettingsToInput(modelSettings)
        : {
            profiles: settingsDraft.profiles.map(modelProfileDraftToInput),
            translation_model_id: settingsDraft.translation_model_id,
            learning_model_id: settingsDraft.learning_model_id,
            global_model_id: settingsDraft.global_model_id,
            asr_model_id: settingsDraft.asr_model_id,
            study_detail_level: "faithful",
            task_parameters: taskParameterDraftsToInput(settingsDraft.task_parameters),
          };
      const next = await saveModelSettings({ ...source, asr_model_id: profileId });
      setModelSettings(next);
      setSettingsDraft(draftFromModelSettings(next, settingsDraft.active_profile_id));
      setRoleSettingsMessage(copy.modelRolesSaved);
    } catch (err) {
      setSettingsDraft((current) => ({ ...current, asr_model_id: previousRoleId }));
      setRoleSettingsMessage(`${copy.modelRolesSaveFailed}: ${errorMessage(err, copy.unknownError)}`);
    } finally {
      setRoleSettingsBusy(false);
    }
  }

  async function handleSaveWorkbenchTranscript(itemId: string, transcript: TranscriptSegment[]): Promise<CourseItem> {
    const next = await saveTranscript(itemId, transcript);
    upsertCourseItem(next);
    return next;
  }

  function handleAddModelProfile() {
    const id = `profile-${Date.now()}`;
    setSettingsDraft((current) => {
      const nextProfile: ModelProfileDraft = {
        id,
        name: "",
        provider_type: "openai",
        base_url: "",
        model: "",
        context_window: "",
        max_tokens: "",
        has_api_key: false,
        api_key_preview: null,
        api_key: "",
      };
      return {
        profiles: [...current.profiles, nextProfile],
        active_profile_id: id,
        translation_model_id: current.translation_model_id || id,
        learning_model_id: current.learning_model_id || id,
        global_model_id: current.global_model_id || id,
        asr_model_id: current.asr_model_id || id,
        study_detail_level: "faithful",
        task_parameters: current.task_parameters,
      };
    });
  }

  function handleAddAsrModelProfile() {
    const id = `profile-${Date.now()}`;
    setSettingsDraft((current) => {
      const nextProfile: ModelProfileDraft = {
        id,
        name: "",
        provider_type: "openai",
        base_url: "",
        model: "",
        context_window: "",
        max_tokens: "",
        has_api_key: false,
        api_key_preview: null,
        api_key: "",
      };
      return {
        profiles: [...current.profiles, nextProfile],
        active_profile_id: id,
        translation_model_id: current.translation_model_id || id,
        learning_model_id: current.learning_model_id || id,
        global_model_id: current.global_model_id || id,
        asr_model_id: id,
        study_detail_level: "faithful",
        task_parameters: current.task_parameters,
      };
    });
  }

  if (view === "asr") {
    return (
      <main className="app-shell">
        <AsrWorkbench
          copy={copy}
          item={selected}
          outputLanguage={outputLanguage}
          modelSettings={modelSettings}
          roleBusy={roleSettingsBusy}
          roleMessage={roleSettingsMessage}
          onBack={() => setView("workspace")}
          onOpenSettings={() => setAsrSettingsOpen(true)}
          onAsrModelChange={handleSaveAsrModelRole}
          onSaveTranscript={handleSaveWorkbenchTranscript}
        />
        {asrSettingsOpen ? (
          <SettingsModal
            scope="asr"
            copy={copy}
            draft={settingsDraft}
            onlineAsrDraft={onlineAsrDraft}
            modelSettings={modelSettings}
            busy={settingsBusy}
            message={settingsMessage}
            roleBusy={roleSettingsBusy}
            roleMessage={roleSettingsMessage}
            onClose={() => {
              setAsrSettingsOpen(false);
              setSettingsMessage(null);
              setRoleSettingsMessage(null);
              if (modelSettings) {
                setSettingsDraft(draftFromModelSettings(modelSettings, settingsDraft.active_profile_id));
              }
              if (onlineAsrSettings) {
                setOnlineAsrDraft(draftFromOnlineAsrSettings(onlineAsrSettings));
              }
            }}
            onAddProfile={handleAddAsrModelProfile}
            onDraftChange={setSettingsDraft}
            onOnlineAsrDraftChange={setOnlineAsrDraft}
            onOnlineAsrProviderChange={handleOnlineAsrProviderChange}
            onRoleChange={handleSaveModelRole}
            onSave={handleSaveSettings}
          />
        ) : null}
      </main>
    );
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand-cluster">
          <div className="brand">
            <div className="brand-mark">CN</div>
            <div>
              <h1>Course Navigator</h1>
              <p>{copy.subtitle}</p>
            </div>
          </div>
          <button
            className="settings-trigger"
            aria-label={copy.modelSettings}
            onClick={() => setSettingsOpen(true)}
          >
            <SettingsIcon size={18} />
          </button>
        </div>
        <form
          className="url-form"
          onSubmit={(event) => {
            event.preventDefault();
            void handleOpenUrl();
          }}
        >
          <input
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                void handleOpenUrl();
              }
            }}
            placeholder={copy.urlPlaceholder}
          />
          <button
            aria-label={copy.openUrl}
            className="open-url-button"
            title={copy.openUrlTitle}
            type="submit"
            disabled={!url.trim() || Boolean(busy)}
          >
            <Play size={15} />
          </button>
          <label className="control-field">
            <span>{copy.extractAuth}</span>
            <select value={mode} onChange={(event) => setMode(event.target.value as ExtractMode)}>
              <option value="normal">{copy.modeNormal}</option>
              <option value="browser">{copy.modeBrowser}</option>
              <option value="cookies">{copy.modeCookies}</option>
            </select>
          </label>
          {mode === "browser" ? (
            <label className="control-field auth-source-field">
              <span>{copy.cookieSource}</span>
              <input
                className="short-input"
                value={browser}
                onChange={(event) => setBrowser(event.target.value)}
                placeholder={copy.browserCookieHint}
              />
            </label>
          ) : mode === "cookies" ? (
            <label className="control-field auth-source-field">
              <span>{copy.cookieFile}</span>
              <input
                className="path-input"
                value={cookiesPath}
                onChange={(event) => setCookiesPath(event.target.value)}
                placeholder="/path/to/cookies.txt"
              />
            </label>
          ) : (
            <div className="auth-source-placeholder" aria-hidden="true" />
          )}
          <label className="control-field">
            <span>{copy.subtitleSource}</span>
            <select
              aria-label={copy.subtitleSource}
              value={subtitleSource}
              onChange={(event) => handleSubtitleSourceChange(event.target.value as SubtitleSourceChoice)}
            >
              <option value="subtitles">{copy.subtitleSourceOriginal}</option>
              <option value="asr">{copy.subtitleSourceAsr}</option>
              <option value="online_asr">{copy.subtitleSourceOnlineAsr}</option>
              <option value="local_upload">{copy.subtitleSourceLocalUpload}</option>
            </select>
          </label>
          <input
            ref={subtitleUploadInputRef}
            aria-label={copy.uploadSubtitleFile}
            className="visually-hidden"
            type="file"
            accept=".srt,.vtt,.txt,.md,.markdown,.lrc,.ass,.ssa,text/plain,text/markdown,text/vtt"
            onChange={(event) => void handleLocalSubtitleFile(event)}
          />
          <label className="control-field">
            <span>{copy.interfaceLanguage}</span>
            <select
              aria-label={copy.interfaceLanguage}
              className="language-select"
              value={uiLanguage}
              onChange={(event) => setUiLanguage(event.target.value as UiLanguage)}
            >
              <option value="zh-CN">中文</option>
              <option value="en">English</option>
            </select>
          </label>
          <label className="control-field">
            <span>{copy.outputLanguage}</span>
            <select
              aria-label={copy.outputLanguage}
              className="language-select"
              value={outputLanguage}
              onChange={(event) => setOutputLanguage(event.target.value as OutputLanguage)}
            >
              <option value="zh-CN">{copy.outputZh}</option>
              <option value="en">{copy.outputEn}</option>
              <option value="ja">{copy.outputJa}</option>
            </select>
          </label>
          <button
            className="top-subtitle-button"
            type="button"
            title={copy.getSubtitlesTitle}
            onClick={() => void handleGetSubtitles()}
            disabled={Boolean(busy) || !(url.trim() || selected?.source_url)}
          >
            {activeJobKind === "extract" ? <Loader2 className="spin" size={16} /> : <Captions size={16} />}
            {copy.getSubtitles}
          </button>
          <button
            className="top-translate-button"
            type="button"
            onClick={handleTranslate}
            disabled={Boolean(busy) || !selected?.transcript.length}
          >
            {activeJobKind === "translation" ? <Loader2 className="spin" size={16} /> : <Languages size={16} />}
            {copy.translateSubtitles}
          </button>
        </form>
      </header>

      {settingsOpen ? (
        <SettingsModal
          copy={copy}
          draft={settingsDraft}
          onlineAsrDraft={onlineAsrDraft}
          modelSettings={modelSettings}
          busy={settingsBusy}
          message={settingsMessage}
          roleBusy={roleSettingsBusy}
          roleMessage={roleSettingsMessage}
          onClose={() => {
            setSettingsOpen(false);
            setSettingsMessage(null);
            setRoleSettingsMessage(null);
            if (modelSettings) {
              setSettingsDraft(draftFromModelSettings(modelSettings, settingsDraft.active_profile_id));
            }
            if (onlineAsrSettings) {
              setOnlineAsrDraft(draftFromOnlineAsrSettings(onlineAsrSettings));
            }
          }}
          onAddProfile={handleAddModelProfile}
          onDraftChange={setSettingsDraft}
          onOnlineAsrDraftChange={setOnlineAsrDraft}
          onOnlineAsrProviderChange={handleOnlineAsrProviderChange}
          onRoleChange={handleSaveModelRole}
          onSave={handleSaveSettings}
        />
      ) : null}

      {exportModalOpen ? (
        <CourseShareExportModal
          copy={copy}
          groups={groupedItems}
          selectedIds={exportSelectedIds}
          message={exportMessage}
          onMessageChange={setExportMessage}
          onToggleCourse={toggleExportCourse}
          onToggleGroup={toggleExportGroup}
          onExport={handleExportCourses}
          onClose={() => setExportModalOpen(false)}
        />
      ) : null}

      {importMessage ? (
        <ImportMessageModal copy={copy} message={importMessage} onClose={() => setImportMessage(null)} />
      ) : null}

      {error ? <div className="error-strip" role="alert" aria-live="polite">{error}</div> : null}
      {busy ? (
        <div className="status-strip">
          <span>{busy}</span>
          {jobStatus ? <progress max={100} value={jobStatus.progress} /> : null}
        </div>
      ) : null}

      <section
        className="workspace"
        ref={workspaceRef}
        style={
          {
            "--left-rail-width": `${layout.leftWidth}px`,
            "--right-rail-width": `${layout.rightWidth}px`,
          } as CSSProperties
        }
      >
        <aside className={leftRailClassName}>
          <section className="panel open-panel">
            <div className="panel-header library-panel-header">
              <h2>{copy.library}</h2>
              <div className="library-panel-actions">
                <button
                  aria-label={copy.importCourses}
                  className="panel-icon-button"
                  disabled={importBusy}
                  title={copy.importCourses}
                  onClick={() => importFileInputRef.current?.click()}
                >
                  {importBusy ? <Loader2 className="spin" size={14} /> : <Download size={14} />}
                </button>
                <button
                  aria-label={copy.exportCourses}
                  className="panel-icon-button"
                  disabled={!items.length}
                  title={copy.exportCourses}
                  onClick={openExportModal}
                >
                  <Upload size={14} />
                </button>
                <button
                  aria-label={copy.addCollection}
                  className="panel-icon-button"
                  title={copy.addCollection}
                  onClick={handleAddCollection}
                >
                  <FolderPlus size={14} />
                </button>
                <input
                  ref={importFileInputRef}
                  className="visually-hidden"
                  type="file"
                  accept=".course-nav.json,application/json"
                  onChange={(event) => void handleImportPackageFile(event)}
                />
              </div>
            </div>
            <div className="library-list">
              {groupedItems.map((group, groupIndex) => {
                const collectionCollapsed = collapsedCollectionKeys.has(group.key);
                const collectionEditing = editingCollectionKey === group.key;
                const canDeleteCollection = group.key !== collectionStorageKey("");
                return (
                <section
                  className={collectionCollapsed ? "library-collection collapsed" : "library-collection"}
                  key={group.key}
                >
                  {collectionEditing ? (
                    <form
                      className="library-collection-edit-form"
                      onSubmit={(event) => {
                        event.preventDefault();
                        void handleRenameCollection(group);
                      }}
                    >
                      <label>
                        <span>{copy.collectionTitle}</span>
                        <input
                          aria-label={copy.collectionTitle}
                          autoFocus
                          value={editingCollectionDraft}
                          onChange={(event) => setEditingCollectionDraft(event.target.value)}
                          onKeyDown={(event) => {
                            if (event.key === "Escape") {
                              event.preventDefault();
                              cancelEditingCollection();
                            }
                          }}
                        />
                      </label>
                      <div className="library-collection-edit-actions">
                        <button
                          aria-label={`${copy.saveCollection} ${editingCollectionDraft || group.title}`}
                          className="library-collection-save"
                          disabled={savingCollectionKey === group.key}
                          type="submit"
                        >
                          {savingCollectionKey === group.key ? <Loader2 className="spin" size={13} /> : <Check size={13} />}
                        </button>
                        <button
                          aria-label={copy.cancelCollectionEdit}
                          className="library-collection-cancel"
                          onClick={cancelEditingCollection}
                          type="button"
                        >
                          <X size={13} />
                        </button>
                      </div>
                    </form>
                  ) : (
                    <div className="library-collection-head">
                      <button
                        aria-label={`${collectionCollapsed ? copy.expandCollection : copy.collapseCollection} ${group.title}`}
                        className="library-collection-toggle"
                        onClick={() => toggleCollectionCollapse(group.key)}
                      >
                        <span
                          aria-hidden="true"
                          className={collectionCollapsed ? "collection-disclosure collapsed" : "collection-disclosure"}
                        />
                        <span>{group.title}</span>
                      </button>
                      {groupIndex > 0 ? (
                        <button
                          aria-label={`${copy.moveCollectionUp} ${group.title}`}
                          className="library-collection-move"
                          title={copy.moveCollectionUp}
                          onClick={() => handleMoveCollection(group, -1)}
                        >
                          <ArrowUp size={12} />
                        </button>
                      ) : <span className="library-collection-spacer" aria-hidden="true" />}
                      {groupIndex < groupedItems.length - 1 ? (
                        <button
                          aria-label={`${copy.moveCollectionDown} ${group.title}`}
                          className="library-collection-move"
                          title={copy.moveCollectionDown}
                          onClick={() => handleMoveCollection(group, 1)}
                        >
                          <ArrowDown size={12} />
                        </button>
                      ) : <span className="library-collection-spacer" aria-hidden="true" />}
                      <button
                        aria-label={`${copy.editCollection} ${group.title}`}
                        className="library-collection-edit"
                        title={copy.editCollection}
                        onClick={() => startEditingCollection(group)}
                      >
                        <Pencil size={13} />
                      </button>
                      {canDeleteCollection ? (
                        <button
                          aria-label={`${copy.deleteCollection} ${group.title}`}
                          className="library-collection-delete"
                          disabled={savingCollectionKey === group.key}
                          title={copy.deleteCollection}
                          onClick={() => void handleDeleteCollection(group)}
                        >
                          {savingCollectionKey === group.key ? <Loader2 className="spin" size={13} /> : <Trash2 size={13} />}
                        </button>
                      ) : <span className="library-collection-spacer" aria-hidden="true" />}
                      <small>{group.items.length}</small>
                    </div>
                  )}
                  {!collectionCollapsed && group.items.length ? group.items.map((item) => (
                    <div className={item.id === selected?.id ? "library-entry active" : "library-entry"} key={item.id}>
                      {editingTitleId === item.id ? (
                        <form
                          className="library-title-form"
                          onSubmit={(event) => {
                            event.preventDefault();
                            void handleRenameCourse(item);
                          }}
                        >
                          <label className="title-field">
                            <span>{copy.courseTitle}</span>
                            <input
                              aria-label={copy.courseTitle}
                              autoFocus
                              value={editingCourseDraft.title}
                              onChange={(event) =>
                                setEditingCourseDraft((current) => ({ ...current, title: event.target.value }))
                              }
                              onKeyDown={(event) => {
                                if (event.key === "Escape") {
                                  event.preventDefault();
                                  cancelEditingTitle();
                                }
                              }}
                            />
                          </label>
                          <label className="translated-title-field">
                            <span>{copy.courseTranslatedTitle}</span>
                            <input
                              aria-label={copy.courseTranslatedTitle}
                              value={editingCourseDraft.translated_title}
                              onChange={(event) =>
                                setEditingCourseDraft((current) => ({ ...current, translated_title: event.target.value }))
                              }
                              onKeyDown={(event) => {
                                if (event.key === "Escape") {
                                  event.preventDefault();
                                  cancelEditingTitle();
                                }
                              }}
                            />
                          </label>
                          <label className="collection-field">
                            <span>{copy.courseCollection}</span>
                            <select
                              aria-label={copy.courseCollection}
                              value={editingCourseDraft.collection_title}
                              onChange={(event) =>
                                setEditingCourseDraft((current) => ({ ...current, collection_title: event.target.value }))
                              }
                            >
                              {collectionOptions.map((collection) => (
                                <option key={collection.value} value={collection.value}>
                                  {collection.label}
                                </option>
                              ))}
                            </select>
                          </label>
                          <label className="index-field">
                            <span>{copy.courseIndex}</span>
                            <input
                              aria-label={copy.courseIndex}
                              inputMode="decimal"
                              value={editingCourseDraft.course_index}
                              onChange={(event) =>
                                setEditingCourseDraft((current) => ({ ...current, course_index: event.target.value }))
                              }
                            />
                          </label>
                          <div className="library-title-actions">
                            <button
                              aria-label={`${copy.saveTitle} ${editingCourseDraft.title || item.title}`}
                              className="library-save"
                              disabled={savingTitleId === item.id}
                              type="submit"
                            >
                              {savingTitleId === item.id ? <Loader2 className="spin" size={14} /> : <Check size={14} />}
                            </button>
                            <button
                              aria-label={copy.cancelTitleEdit}
                              className="library-cancel"
                              onClick={cancelEditingTitle}
                              type="button"
                            >
                              <X size={14} />
                            </button>
                          </div>
                        </form>
                      ) : (
                        <>
                          <button
                            className="library-item"
                            onClick={() => selectCourse(item)}
                            onDoubleClick={() => startEditingTitle(item)}
                          >
                            <span className="library-title-line">
                              {displayCourseNumber(item) ? <small className="library-index-badge">{displayCourseNumber(item)}</small> : null}
                              <span>{item.title}</span>
                            </span>
                            {item.study?.translated_title ? (
                              <span className="library-translated-title">{item.study.translated_title}</span>
                            ) : null}
                            <small>{formatCourseDuration(item) ?? copy.noDuration}</small>
                          </button>
                          <div className="library-actions">
                            <button
                              className="library-move"
                              aria-label={`${copy.moveCourseUp} ${item.title}`}
                              title={copy.moveCourseUp}
                              disabled={!canMoveCourse(items, item, -1)}
                              onClick={() => void handleMoveCourse(item, -1)}
                            >
                              <ArrowUp size={13} />
                            </button>
                            <button
                              className="library-move"
                              aria-label={`${copy.moveCourseDown} ${item.title}`}
                              title={copy.moveCourseDown}
                              disabled={!canMoveCourse(items, item, 1)}
                              onClick={() => void handleMoveCourse(item, 1)}
                            >
                              <ArrowDown size={13} />
                            </button>
                            <button
                              className="library-edit"
                              aria-label={`${copy.editTitle} ${item.title}`}
                              title={copy.editTitle}
                              onClick={() => startEditingTitle(item)}
                            >
                              <Pencil size={14} />
                            </button>
                            <button
                              className="library-copy"
                              aria-label={`${copy.copyUrl} ${item.title}`}
                              data-tooltip={copy.copyUrl}
                              onClick={() => void handleCopyCourseUrl(item)}
                            >
                              <Copy size={14} />
                            </button>
                            <button
                              className="library-delete"
                              aria-label={`${copy.deleteCourse} ${item.title}`}
                              title={copy.deleteCourse}
                              onClick={() => handleDeleteCourse(item)}
                            >
                              <Trash2 size={14} />
                            </button>
                          </div>
                        </>
                      )}
                    </div>
                  )) : !collectionCollapsed ? <p className="empty library-empty">{copy.emptyCollection}</p> : null}
                </section>
              );
              })}
              {!items.length && !manualCollections.length ? <p className="empty">{copy.emptyLibrary}</p> : null}
            </div>
          </section>

          {timeMapVisible ? (
            <section className="panel open-panel">
              <div className="panel-header">
                <h2>{copy.timeMap}</h2>
                <button
                  aria-label={copy.collapseTimeMap}
                  className="panel-icon-button"
                  title={copy.collapseTimeMap}
                  onClick={() => setTimeMapPreference(false)}
                >
                  <ChevronDown size={14} />
                </button>
              </div>
              <TimeMap
                study={selectedStudy}
                currentTime={playheadTime}
                onSeek={seek}
                emptyLabel={copy.noTimeMap}
              />
            </section>
          ) : null}
          {selectedHasStudy && !timeMapOpen ? (
            <section className="panel open-panel time-map-mini-panel">
              <button
                aria-label={copy.expandTimeMap}
                className="time-map-toggle-row"
                title={copy.expandTimeMap}
                onClick={() => setTimeMapPreference(true)}
              >
                <span>{copy.timeMap}</span>
                <ChevronDown className="rotate-180" size={14} />
              </button>
            </section>
          ) : null}
        </aside>

        <ResizeHandle
          ariaLabel="调整课程库和主视频区域宽度"
          kind="vertical"
          onPointerDown={(event) => startLayoutDrag("left", event)}
        />

        <section
          className="main-column"
          ref={mainColumnRef}
          style={
            {
              "--player-row-height": `${layout.playerHeight}px`,
              "--player-row-min-height": `${playerHeightMinimum(videoCaptionPlacement)}px`,
            } as CSSProperties
          }
        >
          <section className="player-wrap">
            <div className="player-toolbar">
              <div className="player-info">
                <h2>{selected?.title ?? copy.noCourse}</h2>
                {selected?.study?.translated_title ? (
                  <p className="player-title-translation">{selected.study.translated_title}</p>
                ) : null}
              </div>
              <div className="source-controls">
                <button
                  className={sourceMode === "embed" ? "seg active" : "seg"}
                  onClick={() => switchSource("embed")}
                >
                  {copy.stream}
                </button>
                <button
                  className={sourceMode === "local" ? "seg active" : "seg"}
                  onClick={() => switchSource("local")}
                  disabled={!selected?.local_video_path}
                >
                  {copy.local}
                </button>
                <button
                  className="icon-button"
                  onClick={handleDownload}
                  disabled={!selected || isPreviewItem(selected) || Boolean(busy)}
                >
                  {activeJobKind === "download" ? <Loader2 className="spin" size={16} /> : <Download size={16} />}
                  {copy.cache}
                </button>
                {selected?.local_video_path ? (
                  <button className="icon-button subtle-danger" onClick={handleRemoveLocalCache} disabled={Boolean(busy)}>
                    <Trash2 size={15} />
                    {copy.removeLocalCache}
                  </button>
                ) : null}
              </div>
            </div>
            <Player
              item={selected}
              seekTime={seekTime}
              sourceMode={sourceMode}
              onProgress={setPlayheadTime}
              copy={copy}
              translatedTranscript={translatedTranscript}
              textDisplayMode={videoCaptionDisplayMode}
              captionPlacement={videoCaptionPlacement}
              fullscreenRequestId={fullscreenRequestId}
              allowBilibiliEmbed={forcedBilibiliEmbed}
              onForceBilibiliEmbed={forceBilibiliStreaming}
            />
            {showVideoCaptionDock ? (
              <VideoCaptionDock
                copy={copy}
                sourceSegments={selected?.transcript ?? []}
                translatedSegments={translatedTranscript}
                currentTime={playheadTime}
                mode={videoCaptionDisplayMode}
                placement={videoCaptionPlacement}
                captionControlsAvailable={videoCaptionControlsAvailable}
                onModeChange={setVideoCaptionDisplayMode}
                onPlacementChange={setVideoCaptionPlacement}
                onFullscreen={() => setFullscreenRequestId((value) => value + 1)}
              />
            ) : null}
          </section>

          <ResizeHandle
            ariaLabel="调整视频和字幕区域高度"
            kind="horizontal"
            onPointerDown={(event) => startLayoutDrag("player", event)}
          />

          <section className="transcript-panel">
            <div className="section-title">
              <div className="section-heading">
                <Captions size={16} />
                <h2>{copy.transcript}</h2>
              </div>
              <div className="transcript-tools">
                <button
                  className="asr-workbench-trigger"
                  type="button"
                  title={copy.openAsrCorrection}
                  onClick={() => setView("asr")}
                  disabled={!selected?.transcript.length}
                >
                  <GitCompare size={17} />
                  {copy.asrCorrection}
                </button>
                <DisplayModeControls
                  copy={copy}
                  scopeLabel={copy.transcript}
                  value={transcriptDisplayMode}
                  onChange={(value) => {
                    if (value !== "hidden") setTranscriptDisplayMode(value);
                  }}
                />
              </div>
            </div>
            <Transcript
              item={selected}
              translatedTranscript={translatedTranscript}
              textDisplayMode={transcriptDisplayMode}
              copy={copy}
              currentTime={playheadTime}
              onSeek={seek}
              emptyLabel={copy.noTranscript}
            />
          </section>
        </section>

        <ResizeHandle
          ariaLabel="调整学习材料区域宽度"
          kind="vertical"
          onPointerDown={(event) => startLayoutDrag("right", event)}
        />

        <aside className={selectedHasStudy ? "right-rail" : "right-rail no-study-actions"}>
          <div className="ai-tabs">
            <TabButton active={activeTab === "guide"} onClick={() => setActiveTab("guide")}>
              {copy.guide}
            </TabButton>
            <TabButton active={activeTab === "outline"} onClick={() => setActiveTab("outline")}>
              {copy.outline}
            </TabButton>
            <TabButton active={activeTab === "detailed"} onClick={() => setActiveTab("detailed")}>
              {copy.detailed}
            </TabButton>
            <TabButton active={activeTab === "high"} onClick={() => setActiveTab("high")}>
              {copy.high}
            </TabButton>
          </div>
          {selectedHasStudy ? (
            <div className="study-actions">
              <button
                className="study-primary-action"
                onClick={handleGenerateStudy}
                disabled={Boolean(busy) || !selected?.transcript.length}
              >
                {regenerateLabelForTab(activeTab, copy)}
              </button>
              <small>
                {translatedTranscript.length ? copy.translationReady : selected?.transcript.length ? copy.subtitlesReady : copy.studyActionHint}
              </small>
            </div>
          ) : null}
          <StudyView
            tab={activeTab}
            item={selected}
            currentTime={playheadTime}
            onSeek={seek}
            copy={copy}
            busy={Boolean(busy)}
            onGenerateStudy={handleGenerateStudy}
          />
        </aside>
      </section>
    </main>
  );
}

function CourseShareExportModal({
  copy,
  groups,
  selectedIds,
  message,
  onMessageChange,
  onToggleCourse,
  onToggleGroup,
  onExport,
  onClose,
}: {
  copy: (typeof COPY)[UiLanguage];
  groups: LibraryCollectionGroup[];
  selectedIds: string[];
  message: string;
  onMessageChange: (value: string) => void;
  onToggleCourse: (itemId: string) => void;
  onToggleGroup: (group: LibraryCollectionGroup) => void;
  onExport: () => void;
  onClose: () => void;
}) {
  const selectedSet = new Set(selectedIds);
  const selectedCount = selectedIds.length;
  return (
    <div className="modal-backdrop" role="presentation">
      <section className="settings-modal course-share-modal" role="dialog" aria-modal="true" aria-labelledby="course-share-title">
        <div className="modal-head">
          <div>
            <h2 id="course-share-title">{copy.exportCoursePackage}</h2>
            <p>{copy.exportCoursePackageHelp}</p>
          </div>
          <button className="icon-only" aria-label={copy.closeDialog} onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        <div className="course-share-body">
          <section className="course-share-list" aria-label={copy.selectCoursesToExport}>
            {groups.map((group) => {
              const groupIds = group.items.map((item) => item.id);
              const allChecked = groupIds.length > 0 && groupIds.every((id) => selectedSet.has(id));
              const someChecked = groupIds.some((id) => selectedSet.has(id));
              return (
                <div className="course-share-group" key={group.key}>
                  <label className="course-share-group-head">
                    <input
                      type="checkbox"
                      checked={allChecked}
                      ref={(element) => {
                        if (element) element.indeterminate = someChecked && !allChecked;
                      }}
                      onChange={() => onToggleGroup(group)}
                      disabled={!group.items.length}
                    />
                    <span>{group.title}</span>
                    <small>{group.items.length}</small>
                  </label>
                  {group.items.length ? (
                    <div className="course-share-courses">
                      {group.items.map((item) => (
                        <label className="course-share-course" key={item.id}>
                          <input
                            type="checkbox"
                            checked={selectedSet.has(item.id)}
                            onChange={() => onToggleCourse(item.id)}
                          />
                          <span>{displayCourseNumber(item) ? `${displayCourseNumber(item)}. ${item.title}` : item.title}</span>
                        </label>
                      ))}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </section>
          <label className="settings-field course-share-message">
            <span>{copy.shareMessage}</span>
            <textarea
              value={message}
              onChange={(event) => onMessageChange(event.target.value)}
              placeholder={copy.shareMessagePlaceholder}
              maxLength={4000}
            />
          </label>
        </div>
        <div className="modal-actions">
          <span>{selectedCount ? `${copy.selectCoursesToExport} · ${selectedCount}` : copy.noExportSelection}</span>
          <button className="secondary-modal-action" type="button" onClick={onClose}>
            {copy.closeDialog}
          </button>
          <button type="button" onClick={onExport} disabled={!selectedCount}>
            <Download size={15} />
            {copy.exportSelected}
          </button>
        </div>
      </section>
    </div>
  );
}

function ImportMessageModal({
  copy,
  message,
  onClose,
}: {
  copy: (typeof COPY)[UiLanguage];
  message: string;
  onClose: () => void;
}) {
  return (
    <div className="modal-backdrop import-message-backdrop" role="presentation">
      <section className="settings-modal import-message-modal" role="dialog" aria-modal="true" aria-labelledby="import-message-title">
        <div className="modal-head">
          <h2 id="import-message-title">{copy.importMessageTitle}</h2>
          <button className="icon-only" aria-label={copy.closeDialog} onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        <p>{message}</p>
        <div className="modal-actions">
          <button type="button" onClick={onClose}>{copy.closeImportMessage}</button>
        </div>
      </section>
    </div>
  );
}

function ResizeHandle({
  ariaLabel,
  kind,
  onPointerDown,
}: {
  ariaLabel: string;
  kind: "vertical" | "horizontal";
  onPointerDown: (event: ReactPointerEvent<HTMLButtonElement>) => void;
}) {
  return (
    <button
      className={`resize-handle ${kind}`}
      aria-label={ariaLabel}
      onPointerDown={onPointerDown}
      type="button"
    />
  );
}

function DisplayModeControls({
  copy,
  scopeLabel,
  value,
  onChange,
  allowHidden = false,
}: {
  copy: (typeof COPY)[UiLanguage];
  scopeLabel: string;
  value: CaptionDisplayMode;
  onChange: (value: CaptionDisplayMode) => void;
  allowHidden?: boolean;
}) {
  return (
    <div className="display-mode-controls" role="group" aria-label={`${scopeLabel}${copy.displayMode}`}>
      <button
        className={value === "source" ? "mode-chip active" : "mode-chip"}
        aria-label={`${scopeLabel}${copy.sourceOnly}`}
        title={copy.sourceOnly}
        onClick={() => onChange("source")}
      >
        <span className="mode-glyph">原</span>
      </button>
      <button
        className={value === "target" ? "mode-chip active" : "mode-chip"}
        aria-label={`${scopeLabel}${copy.targetOnly}`}
        title={copy.targetOnly}
        onClick={() => onChange("target")}
      >
        <span className="mode-glyph">译</span>
      </button>
      <button
        className={value === "bilingual" ? "mode-chip active" : "mode-chip"}
        aria-label={`${scopeLabel}${copy.bilingual}`}
        title={copy.bilingual}
        onClick={() => onChange("bilingual")}
      >
        <span className="mode-glyph bilingual-glyph">双</span>
      </button>
      {allowHidden ? (
        <button
          className={value === "hidden" ? "mode-chip active" : "mode-chip"}
          aria-label={`${scopeLabel}${copy.hideCaption}`}
          title={copy.hideCaption}
          onClick={() => onChange("hidden")}
        >
          <span className="mode-glyph">隐</span>
        </button>
      ) : null}
    </div>
  );
}

function AsrWorkbench({
  copy,
  item,
  outputLanguage,
  modelSettings,
  roleBusy,
  roleMessage,
  onBack,
  onOpenSettings,
  onAsrModelChange,
  onSaveTranscript,
}: {
  copy: (typeof COPY)[UiLanguage];
  item: CourseItem | null;
  outputLanguage: OutputLanguage;
  modelSettings: ModelSettings | null;
  roleBusy: boolean;
  roleMessage: string | null;
  onBack: () => void;
  onOpenSettings: () => void;
  onAsrModelChange: (profileId: string) => Promise<void>;
  onSaveTranscript: (itemId: string, transcript: TranscriptSegment[]) => Promise<CourseItem>;
}) {
  const editorRef = useRef<HTMLTextAreaElement | null>(null);
  const previewRef = useRef<HTMLTextAreaElement | null>(null);
  const asrGridRef = useRef<HTMLDivElement | null>(null);
  const scrollSyncRef = useRef(false);
  const asrDragCleanupRef = useRef<(() => void) | null>(null);
  const hoverHideTimerRef = useRef<number | null>(null);
  const [editorText, setEditorText] = useState(() => transcriptToEditorText(item?.transcript ?? []));
  const [suggestions, setSuggestions] = useState<AsrCorrectionSuggestion[]>([]);
  const [suggestionsExpanded, setSuggestionsExpanded] = useState(false);
  const [saveAcceptedChanges, setSaveAcceptedChanges] = useState(() =>
    loadBooleanPreference(ASR_SAVE_ACCEPTED_CHANGES_STORAGE_KEY, false),
  );
  const [sortSuggestionsByConfidence, setSortSuggestionsByConfidence] = useState(() =>
    loadBooleanPreference(ASR_SORT_BY_CONFIDENCE_STORAGE_KEY, true),
  );
  const [confidenceThreshold, setConfidenceThreshold] = useState("95");
  const [activeSuggestionId, setActiveSuggestionId] = useState<string | null>(null);
  const [reviewWidth, setReviewWidth] = useState(420);
  const [hoverCard, setHoverCard] = useState<AsrSuggestionHover | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<StudyJobStatus | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [userContext, setUserContext] = useState("");
  const [searchSettings, setSearchSettings] = useState<AsrSearchSettings | null>(null);
  const [searchDraft, setSearchDraft] = useState<AsrSearchDraft>({
    enabled: false,
    provider: "tavily",
    api_key: "",
    api_key_preview: null,
    base_url: "",
    result_limit: "5",
  });

  useEffect(() => {
    setEditorText(transcriptToEditorText(item?.transcript ?? []));
    setSuggestions([]);
    setMessage(null);
    setError(null);
    setJobStatus(null);
    setUserContext("");
    setSuggestionsExpanded(false);
    setHoverCard(null);
    setActiveSuggestionId(null);
  }, [item?.id]);

  useEffect(() => {
    let cancelled = false;
    getAsrSearchSettings()
      .then((settings) => {
        if (cancelled) return;
        setSearchSettings(settings);
        setSearchDraft(settingsToSearchDraft(settings));
      })
      .catch(() => {
        if (!cancelled) {
          setSearchSettings(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    return () => {
      if (hoverHideTimerRef.current !== null) {
        window.clearTimeout(hoverHideTimerRef.current);
      }
      asrDragCleanupRef.current?.();
    };
  }, []);

  const profiles = modelSettings?.profiles ?? [];
  const selectedModelId = modelSettings?.asr_model_id && profiles.some((profile) => profile.id === modelSettings.asr_model_id)
    ? modelSettings.asr_model_id
    : (profiles[0]?.id ?? "");
  const counts = suggestionCounts(suggestions);
  const pendingSuggestions = useMemo(
    () => suggestions.filter((suggestion) => suggestion.status === "pending"),
    [suggestions],
  );
  const reviewSuggestions = useMemo(
    () => sortAsrReviewSuggestions(pendingSuggestions, sortSuggestionsByConfidence),
    [pendingSuggestions, sortSuggestionsByConfidence],
  );
  const suggestionById = useMemo(
    () => new Map(suggestions.map((suggestion) => [suggestion.id, suggestion])),
    [suggestions],
  );
  const hasCorrectionSuggestions = pendingSuggestions.length > 0;
  const effectiveSuggestionsExpanded = suggestionsExpanded && hasCorrectionSuggestions;
  const activeSuggestionIndex = activeSuggestionId
    ? reviewSuggestions.findIndex((suggestion) => suggestion.id === activeSuggestionId)
    : -1;
  const activeSuggestion =
    reviewSuggestions[activeSuggestionIndex >= 0 ? activeSuggestionIndex : 0] ?? null;
  const displaySuggestionIndex = activeSuggestion ? Math.max(0, activeSuggestionIndex) + 1 : 0;
  const hoverSuggestion = hoverCard ? suggestionById.get(hoverCard.suggestionId) ?? null : null;
  const progressInfo = jobStatus && busy ? asrProgressInfo(jobStatus, copy) : null;
  const confidenceThresholdPercent = normalizedConfidenceThreshold(confidenceThreshold);
  const thresholdAcceptCount = useMemo(
    () => filterAsrSuggestionsByConfidence(pendingSuggestions, confidenceThresholdPercent).length,
    [confidenceThresholdPercent, pendingSuggestions],
  );
  const reviewTranscript = useMemo(() => {
    try {
      return editorTextToTranscript(editorText);
    } catch {
      return item?.transcript ?? [];
    }
  }, [editorText, item?.transcript]);
  const editorHighlights = useMemo(
    () => asrEditorHighlightRanges(editorText, suggestions),
    [editorText, suggestions],
  );
  const previewText = useMemo(() => {
    try {
      const transcript = suggestions
        .filter((suggestion) => suggestion.status === "pending")
        .reduce((current, suggestion) => applyAsrSuggestion(current, suggestion), editorTextToTranscript(editorText));
      return transcriptToEditorText(transcript);
    } catch {
      return editorText;
    }
  }, [editorText, suggestions]);
  const previewHighlights = useMemo(
    () => asrEditorHighlightRanges(previewText, suggestions, "corrected"),
    [previewText, suggestions],
  );

  useEffect(() => {
    if (pendingSuggestions.length) return;
    setSuggestionsExpanded(false);
    setHoverCard(null);
    setActiveSuggestionId(null);
  }, [pendingSuggestions.length]);

  useEffect(() => {
    if (!reviewSuggestions.length) return;
    if (activeSuggestionId && reviewSuggestions.some((suggestion) => suggestion.id === activeSuggestionId)) return;
    setActiveSuggestionId(reviewSuggestions[0].id);
  }, [activeSuggestionId, reviewSuggestions]);

  useEffect(() => {
    if (!hoverSuggestion || hoverSuggestion.status === "pending") return;
    setHoverCard(null);
  }, [hoverSuggestion]);

  async function runCorrection() {
    if (!item) return;
    setError(null);
    setMessage(null);
    setSuggestions([]);
    setSuggestionsExpanded(false);
    setHoverCard(null);
    try {
      const transcript = editorTextToTranscript(editorText);
      setBusy(`${copy.runAsrCorrection} 0%`);
      const searchConfig = searchDraftToConfig(searchDraft);
      const nextSearchSettings = await saveAsrSearchSettings(searchDraftToSettingsInput(searchDraft));
      setSearchSettings(nextSearchSettings);
      const firstStatus = await startAsrCorrectionJob(item.id, {
        output_language: outputLanguage,
        transcript,
        model_id: selectedModelId || undefined,
        user_context: userContext.trim() || undefined,
        search: searchConfig,
      });
      setJobStatus(firstStatus);
      let current = firstStatus;
      while (current.status === "queued" || current.status === "running") {
        await delay(1000);
        current = await getStudyJob(firstStatus.job_id);
        setJobStatus(current);
        setBusy(`${current.message} ${current.progress}%`);
      }
      if (current.status === "failed") {
        throw new Error(current.error ?? current.message);
      }
      const result = await getAsrCorrectionResult(firstStatus.job_id);
      setSuggestions(result.suggestions);
      setActiveSuggestionId(result.suggestions.find((suggestion) => suggestion.status === "pending")?.id ?? null);
      setMessage(result.suggestions.length ? null : copy.noCorrectionSuggestions);
    } catch (err) {
      setError(asrCorrectionErrorMessage(err, copy));
    } finally {
      setBusy(null);
    }
  }

  function toggleSaveAcceptedChanges(checked: boolean) {
    setSaveAcceptedChanges(checked);
    saveBooleanPreference(ASR_SAVE_ACCEPTED_CHANGES_STORAGE_KEY, checked);
  }

  function toggleSortSuggestionsByConfidence(checked: boolean) {
    setSortSuggestionsByConfidence(checked);
    saveBooleanPreference(ASR_SORT_BY_CONFIDENCE_STORAGE_KEY, checked);
  }

  function changeSearchProvider(provider: AsrSearchProvider) {
    const savedBaseUrl = searchSettings?.[provider]?.base_url ?? "";
    const apiKeyPreview = searchSettings?.[provider]?.api_key_preview ?? null;
    setSearchDraft((current) => ({
      ...current,
      provider,
      api_key: maskedSecretValue(apiKeyPreview),
      api_key_preview: apiKeyPreview,
      base_url: provider === "firecrawl" ? savedBaseUrl : "",
    }));
  }

  async function saveCurrentTranscript() {
    if (!item) return;
    setError(null);
    setMessage(null);
    try {
      const transcript = editorTextToTranscript(editorText);
      const next = await onSaveTranscript(item.id, transcript);
      setEditorText(transcriptToEditorText(next.transcript));
      setMessage(copy.transcriptSaved);
    } catch (err) {
      setError(errorMessage(err, copy.unknownError));
    }
  }

  async function saveTranscriptText(nextEditorText: string) {
    if (!item) return;
    const transcript = editorTextToTranscript(nextEditorText);
    const next = await onSaveTranscript(item.id, transcript);
    setEditorText(transcriptToEditorText(next.transcript));
    setMessage(copy.transcriptSaved);
  }

  async function acceptSuggestion(suggestionId: string) {
    const suggestion = suggestions.find((entry) => entry.id === suggestionId);
    if (!suggestion) return;
    try {
      const transcript = editorTextToTranscript(editorText);
      const nextTranscript = applyAsrSuggestion(transcript, suggestion);
      const nextEditorText = transcriptToEditorText(nextTranscript);
      setEditorText(nextEditorText);
      setSuggestions((current) =>
        current.map((entry) => (entry.id === suggestionId ? { ...entry, status: "accepted" } : entry)),
      );
      if (saveAcceptedChanges) {
        await saveTranscriptText(nextEditorText);
      }
    } catch (err) {
      setError(errorMessage(err, copy.unknownError));
    }
  }

  function rejectSuggestion(suggestionId: string) {
    setSuggestions((current) =>
      current.map((entry) => (entry.id === suggestionId ? { ...entry, status: "rejected" } : entry)),
    );
  }

  async function acceptAllSuggestions() {
    await acceptSuggestionBatch(pendingSuggestions);
  }

  async function acceptSuggestionsAboveThreshold() {
    await acceptSuggestionBatch(
      filterAsrSuggestionsByConfidence(pendingSuggestions, Number(confidenceThreshold)),
    );
  }

  async function acceptSuggestionBatch(targetSuggestions: AsrCorrectionSuggestion[]) {
    if (!targetSuggestions.length) return;
    try {
      const acceptedIds = new Set(targetSuggestions.map((suggestion) => suggestion.id));
      const transcript = targetSuggestions.reduce(
        (current, suggestion) => applyAsrSuggestion(current, suggestion),
        editorTextToTranscript(editorText),
      );
      const nextEditorText = transcriptToEditorText(transcript);
      setEditorText(nextEditorText);
      setSuggestions((current) =>
        current.map((entry) => (acceptedIds.has(entry.id) ? { ...entry, status: "accepted" } : entry)),
      );
      if (saveAcceptedChanges) {
        await saveTranscriptText(nextEditorText);
      }
    } catch (err) {
      setError(errorMessage(err, copy.unknownError));
    }
  }

  function changePreviewText(nextPreviewText: string) {
    try {
      setEditorText(previewTextToEditorText(nextPreviewText, suggestions));
      setSuggestions((current) => reconcilePreviewEditedSuggestions(nextPreviewText, current));
    } catch {
      setEditorText(nextPreviewText);
    }
  }

  function focusSuggestionInPreview(suggestion: AsrCorrectionSuggestion) {
    setActiveSuggestionId(suggestion.id);
    const [range] = asrEditorHighlightRanges(previewText, [suggestion], "corrected");
    if (!range || !previewRef.current) return;
    const previewEditor = previewRef.current;
    previewEditor.focus();
    previewEditor.setSelectionRange(range.start, range.end);
    window.requestAnimationFrame(() => {
      if (!previewRef.current) return;
      const marker = findAsrEditorMarker("preview", suggestion.id, "corrected");
      if (marker) {
        const maxTop = Math.max(0, previewRef.current.scrollHeight - previewRef.current.clientHeight);
        const targetTop = marker.offsetTop - previewRef.current.clientHeight * 0.28;
        previewRef.current.scrollTop = clamp(targetTop, 0, maxTop);
      }
      syncTranscriptScroll("preview", {
        left: previewRef.current.scrollLeft,
        top: previewRef.current.scrollTop,
      });
    });
  }

  function navigateSuggestion(direction: AsrSuggestionDirection) {
    if (!reviewSuggestions.length) return;
    const currentIndex = activeSuggestionIndex >= 0 ? activeSuggestionIndex : 0;
    const nextIndex = clamp(currentIndex + direction, 0, reviewSuggestions.length - 1);
    focusSuggestionInPreview(reviewSuggestions[nextIndex]);
  }

  function syncTranscriptScroll(source: "editor" | "preview", scroll: { left: number; top: number }) {
    if (scrollSyncRef.current) return;
    scrollSyncRef.current = true;
    if (source === "editor" && previewRef.current) {
      previewRef.current.scrollLeft = scroll.left;
      previewRef.current.scrollTop = scroll.top;
    }
    if (source === "preview" && editorRef.current) {
      editorRef.current.scrollLeft = scroll.left;
      editorRef.current.scrollTop = scroll.top;
    }
    window.requestAnimationFrame(() => {
      scrollSyncRef.current = false;
    });
  }

  function clearHoverHideTimer() {
    if (hoverHideTimerRef.current === null) return;
    window.clearTimeout(hoverHideTimerRef.current);
    hoverHideTimerRef.current = null;
  }

  function scheduleHoverClose() {
    clearHoverHideTimer();
    hoverHideTimerRef.current = window.setTimeout(() => {
      setHoverCard(null);
      hoverHideTimerRef.current = null;
    }, 180);
  }

  function showSuggestionHover(suggestionId: string, event: ReactMouseEvent<HTMLElement>) {
    const suggestion = suggestionById.get(suggestionId);
    if (!suggestion || suggestion.status !== "pending") return;
    clearHoverHideTimer();
    const rect = event.currentTarget.getBoundingClientRect();
    const width = 320;
    const height = 188;
    const left = Math.min(Math.max(12, rect.left), Math.max(12, window.innerWidth - width - 12));
    const below = rect.bottom + 8;
    const top = below + height > window.innerHeight ? Math.max(12, rect.top - height - 8) : below;
    setHoverCard({ suggestionId, left, top });
  }

  function acceptHoveredSuggestion(suggestionId: string) {
    void acceptSuggestion(suggestionId);
    setHoverCard(null);
  }

  function rejectHoveredSuggestion(suggestionId: string) {
    rejectSuggestion(suggestionId);
    setHoverCard(null);
  }

  function startAsrReviewDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    event.preventDefault();
    asrDragCleanupRef.current?.();
    const gridBox = asrGridRef.current?.getBoundingClientRect();
    if (!gridBox) return;
    const handle = event.currentTarget;
    const pointerId = event.pointerId;
    let active = true;
    let frameId: number | null = null;
    let latestX = event.clientX;

    const applyLayout = (clientX: number) => {
      setReviewWidth((current) => {
        const maxWidth = Math.min(
          MAX_ASR_REVIEW_WIDTH,
          Math.max(MIN_ASR_REVIEW_WIDTH, gridBox.width - MIN_ASR_EDITOR_WIDTH - 6),
        );
        const nextWidth = clamp(gridBox.right - clientX, MIN_ASR_REVIEW_WIDTH, maxWidth);
        return nextWidth === current ? current : nextWidth;
      });
    };

    const handlePointerMove = (moveEvent: PointerEvent) => {
      latestX = moveEvent.clientX;
      if (frameId !== null) return;
      frameId = window.requestAnimationFrame(() => {
        frameId = null;
        applyLayout(latestX);
      });
    };

    const stopDrag = () => {
      if (!active) return;
      active = false;
      if (frameId !== null) {
        window.cancelAnimationFrame(frameId);
        frameId = null;
      }
      handle.removeEventListener("pointermove", handlePointerMove);
      handle.removeEventListener("pointerup", stopDrag);
      handle.removeEventListener("pointercancel", stopDrag);
      handle.removeEventListener("lostpointercapture", stopDrag);
      window.removeEventListener("pointerup", stopDrag);
      window.removeEventListener("blur", stopDrag);
      document.body.classList.remove("is-resizing-layout");
      if (handle.hasPointerCapture?.(pointerId)) {
        handle.releasePointerCapture(pointerId);
      }
      asrDragCleanupRef.current = null;
    };

    document.body.classList.add("is-resizing-layout");
    handle.setPointerCapture?.(pointerId);
    handle.addEventListener("pointermove", handlePointerMove);
    handle.addEventListener("pointerup", stopDrag);
    handle.addEventListener("pointercancel", stopDrag);
    handle.addEventListener("lostpointercapture", stopDrag);
    window.addEventListener("pointerup", stopDrag);
    window.addEventListener("blur", stopDrag);
    asrDragCleanupRef.current = stopDrag;
  }

  const gridClassName = hasCorrectionSuggestions ? "asr-grid has-suggestions" : "asr-grid";
  const reviewPanelClassName = [
    "asr-review-panel",
    hasCorrectionSuggestions ? "has-suggestions" : "",
    effectiveSuggestionsExpanded ? "suggestions-expanded" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <section className="asr-workbench">
      <header className="asr-topbar">
        <button className="asr-back-button" type="button" onClick={onBack}>
          <ArrowLeft size={16} />
          {copy.backToWorkspace}
        </button>
        <div className="asr-title-block">
          <h1>{copy.asrWorkbenchTitle}</h1>
          <p>{item?.title ?? copy.noCourse}</p>
        </div>
        <button className="settings-trigger" aria-label={copy.asrModelSettingsTitle} onClick={onOpenSettings}>
          <SettingsIcon size={18} />
        </button>
      </header>

      {error ? <div className="error-strip" role="alert" aria-live="polite">{error}</div> : null}
      {!hasCorrectionSuggestions && message ? (
        <div className="status-strip">{message}</div>
      ) : null}
      {progressInfo ? (
        <div className="asr-progress-card" aria-live="polite">
          <div className="asr-progress-topline">
            <div>
              <span>{copy.asrProgressTitle}</span>
              <strong>{progressInfo.phaseLabel}</strong>
            </div>
            <b>{jobStatus?.progress ?? 0}%</b>
          </div>
          {jobStatus ? <progress max={100} value={jobStatus.progress} /> : null}
          <p>{jobStatus?.message ?? busy}</p>
          <div className="asr-progress-meta">
            <span>{copy.asrProgressElapsed} {progressInfo.elapsed}</span>
            <span>{copy.asrProgressUpdated} {progressInfo.lastUpdate}</span>
          </div>
          {progressInfo.stale ? <p className="asr-progress-warning">{copy.asrProgressStale}</p> : null}
        </div>
      ) : null}

      {!item?.transcript.length ? (
        <div className="asr-empty-state">
          <FileText size={28} />
          <p>{copy.noAsrTranscript}</p>
          <button type="button" onClick={onBack}>{copy.backToWorkspace}</button>
        </div>
      ) : (
        <div
          className={gridClassName}
          ref={asrGridRef}
          style={{ "--asr-review-width": `${reviewWidth}px` } as CSSProperties}
        >
          <section className="asr-editor-panel">
            <div className="asr-panel-head">
              <div>
                <h2>{copy.sourceTranscriptEditor}</h2>
                <p>{copy.asrWorkbenchSubtitle}</p>
              </div>
              <button className="asr-primary-action" type="button" onClick={saveCurrentTranscript} disabled={Boolean(busy)}>
                <Save size={15} />
                {copy.saveTranscript}
              </button>
            </div>
            {hasCorrectionSuggestions ? (
              <div className="asr-transcript-compare">
                <div className="asr-transcript-pane source">
                  <div className="asr-pane-label">{copy.asrBeforeTranscript}</div>
                  <AsrSourceEditor
                    refObject={editorRef}
                    value={editorText}
                    highlights={editorHighlights}
                    activeSuggestionId={activeSuggestion?.id}
                    suggestionById={suggestionById}
                    copy={copy}
                    onChange={setEditorText}
                    onScroll={(scroll) => syncTranscriptScroll("editor", scroll)}
                    onMarkerEnter={showSuggestionHover}
                    onMarkerLeave={scheduleHoverClose}
                  />
                </div>
                <div className="asr-transcript-pane preview">
                  <div className="asr-pane-label with-nav">
                    <span>{copy.asrAfterTranscript}</span>
                    <div className="asr-pane-review-nav" aria-label={copy.correctionSuggestions}>
                      <button
                        type="button"
                        onClick={() => navigateSuggestion(-1)}
                        disabled={!activeSuggestion || displaySuggestionIndex <= 1}
                      >
                        <ArrowUp size={13} />
                        {copy.previousSuggestion}
                      </button>
                      <strong>{displaySuggestionIndex}/{reviewSuggestions.length}</strong>
                      <button
                        type="button"
                        onClick={() => navigateSuggestion(1)}
                        disabled={!activeSuggestion || displaySuggestionIndex >= reviewSuggestions.length}
                      >
                        <ArrowDown size={13} />
                        {copy.nextSuggestion}
                      </button>
                    </div>
                  </div>
                  <AsrSourceEditor
                    refObject={previewRef}
                    value={previewText}
                    highlights={previewHighlights}
                    activeSuggestionId={activeSuggestion?.id}
                    suggestionById={suggestionById}
                    copy={copy}
                    onChange={changePreviewText}
                    onScroll={(scroll) => syncTranscriptScroll("preview", scroll)}
                    onMarkerEnter={showSuggestionHover}
                    onMarkerLeave={scheduleHoverClose}
                  />
                </div>
              </div>
            ) : (
              <div className="asr-manual-editor">
                <AsrSourceEditor
                  refObject={editorRef}
                  value={editorText}
                  highlights={editorHighlights}
                  suggestionById={suggestionById}
                  copy={copy}
                  onChange={setEditorText}
                />
              </div>
            )}
          </section>

          <ResizeHandle
            ariaLabel="调整字幕编辑区和 ASR 侧栏宽度"
            kind="vertical"
            onPointerDown={startAsrReviewDrag}
          />

          <aside className={reviewPanelClassName}>
            <section className="asr-config-panel">
              <label className="settings-field">
                <span>{copy.asrModel}</span>
                <select
                  value={selectedModelId}
                  disabled={roleBusy || !profiles.length}
                  onChange={(event) => void onAsrModelChange(event.target.value)}
                >
                  {profiles.length ? (
                    profiles.map((profile) => (
                      <option value={profile.id} key={profile.id}>
                        {profile.name || profile.model || copy.unnamedModelProfile}
                      </option>
                    ))
                  ) : (
                    <option value="">{copy.noModelProfiles}</option>
                  )}
                </select>
                <small>{copy.asrModelHelp}</small>
              </label>
              {roleMessage ? (
                <div className="settings-role-status" aria-live="polite">
                  {roleBusy ? <Loader2 className="spin" size={13} /> : null}
                  <span>{roleMessage}</span>
                </div>
              ) : null}
              <label className="settings-field asr-context-field">
                <span>{copy.asrUserContext}</span>
                <textarea
                  value={userContext}
                  onChange={(event) => setUserContext(event.target.value)}
                  placeholder={copy.asrUserContextPlaceholder}
                />
                <small>{copy.asrUserContextHelp}</small>
              </label>
              <div className="asr-config-actions">
                <button className="secondary-action" type="button" onClick={onOpenSettings}>
                  {copy.configureModelProfiles}
                </button>
                <label className="asr-switch">
                  <input
                    type="checkbox"
                    checked={searchDraft.enabled}
                    onChange={(event) => setSearchDraft((current) => ({ ...current, enabled: event.target.checked }))}
                  />
                  <span className="asr-switch-track" aria-hidden="true">
                    <span />
                  </span>
                  <span>{copy.searchCalibration}</span>
                </label>
              </div>
              {searchDraft.enabled ? (
                <div className="asr-search-grid">
                  <label className="settings-field">
                    <span>{copy.searchProvider}</span>
                    <select
                      value={searchDraft.provider}
                      onChange={(event) => changeSearchProvider(event.target.value as AsrSearchProvider)}
                    >
                      <option value="tavily">Tavily</option>
                      <option value="firecrawl">Firecrawl</option>
                    </select>
                  </label>
                  {searchDraft.provider === "firecrawl" ? (
                    <label className="settings-field">
                      <span>{copy.firecrawlBaseUrl}</span>
                      <input
                        value={searchDraft.base_url}
                        onChange={(event) => setSearchDraft((current) => ({ ...current, base_url: event.target.value }))}
                        placeholder="http://127.0.0.1:3002"
                      />
                    </label>
                  ) : null}
                  <label className="settings-field">
                    <span>{copy.searchApiKey}</span>
                    <input
                      autoComplete="off"
                      value={searchDraft.api_key}
                      placeholder={searchDraft.api_key_preview ? copy.modelApiKeyHint : copy.apiKeyOptionalHint}
                      onChange={(event) => setSearchDraft((current) => ({
                        ...current,
                        api_key: event.target.value,
                      }))}
                    />
                  </label>
                  <label className="settings-field">
                    <span>{copy.searchResultLimit}</span>
                    <input
                      inputMode="numeric"
                      value={searchDraft.result_limit}
                      onChange={(event) => setSearchDraft((current) => ({ ...current, result_limit: event.target.value }))}
                    />
                  </label>
                </div>
              ) : null}
              <button className="asr-primary-action wide" type="button" onClick={() => void runCorrection()} disabled={Boolean(busy) || !selectedModelId}>
                {busy ? <Loader2 className="spin" size={15} /> : <Sparkles size={15} />}
                {copy.runAsrCorrection}
              </button>
            </section>

            {hasCorrectionSuggestions ? (
              <section className="asr-suggestion-panel">
                <div className="asr-panel-head compact">
                  <div>
                    <h2>{copy.correctionSuggestions}</h2>
                    <p>
                      {copy.pendingChanges} {counts.pending} · {copy.acceptedChanges} {counts.accepted} · {copy.rejectedChanges} {counts.rejected}
                    </p>
                  </div>
                  <div className="asr-review-control-block">
                    <div className="asr-review-options">
                      <label className="asr-inline-check">
                        <input
                          type="checkbox"
                          checked={sortSuggestionsByConfidence}
                          onChange={(event) => toggleSortSuggestionsByConfidence(event.target.checked)}
                        />
                        <span>{copy.sortSuggestionsByConfidence}</span>
                      </label>
                      <label className="asr-inline-check">
                        <input
                          type="checkbox"
                          checked={saveAcceptedChanges}
                          onChange={(event) => toggleSaveAcceptedChanges(event.target.checked)}
                        />
                        <span>{copy.saveAcceptedChanges}</span>
                      </label>
                    </div>
                    <div className="asr-confidence-bulk">
                      <span className="asr-confidence-line">
                        <span>{copy.acceptConfidencePrefix}</span>
                        <input
                          aria-label={copy.confidence}
                          inputMode="decimal"
                          value={confidenceThreshold}
                          onBlur={(event) => setConfidenceThreshold(String(normalizedConfidenceThreshold(event.currentTarget.value)))}
                          onChange={(event) => setConfidenceThreshold(event.target.value)}
                        />
                        <span>{copy.acceptConfidenceSuffix}</span>
                      </span>
                      <button
                        type="button"
                        aria-label={copy.acceptConfidenceAction}
                        title={copy.acceptConfidenceAction}
                        onClick={() => void acceptSuggestionsAboveThreshold()}
                        disabled={!thresholdAcceptCount}
                      >
                        <Check size={14} />
                      </button>
                    </div>
                  </div>
                  <button
                    className="asr-expand-toggle"
                    type="button"
                    onClick={() => setSuggestionsExpanded((current) => !current)}
                    aria-label={effectiveSuggestionsExpanded ? copy.collapseSuggestions : copy.expandSuggestions}
                    title={effectiveSuggestionsExpanded ? copy.collapseSuggestions : copy.expandSuggestions}
                  >
                    {effectiveSuggestionsExpanded ? <ChevronDown size={18} /> : <ChevronUp size={18} />}
                  </button>
                  <div className="asr-panel-actions">
                    <button
                      className="secondary-action"
                      type="button"
                      onClick={() => void acceptAllSuggestions()}
                      disabled={!counts.pending}
                    >
                      <CheckCheck size={14} />
                      {copy.acceptAllChanges}
                    </button>
                    <button
                      className="secondary-action asr-rerun-action"
                      type="button"
                      onClick={() => void runCorrection()}
                      disabled={Boolean(busy) || !selectedModelId}
                    >
                      <Sparkles size={14} />
                      {copy.rerunAsrCorrection}
                    </button>
                  </div>
                </div>
                <div className="asr-suggestions">
                  {reviewSuggestions.map((suggestion) => {
                    const context = asrSuggestionContext(reviewTranscript, suggestion);
                    const tooltip = asrSuggestionTitle(suggestion, copy);
                    return (
                      <article
                        className={`asr-suggestion ${suggestion.status} ${suggestion.id === activeSuggestion?.id ? "active" : ""}`}
                        data-asr-suggestion-id={suggestion.id}
                        key={suggestion.id}
                      >
                        <div className="asr-suggestion-meta">
                          <button
                            className="asr-jump-link"
                            type="button"
                            onClick={() => focusSuggestionInPreview(suggestion)}
                          >
                            {formatTime(suggestion.start)}
                          </button>
                          <span>{copy.confidence} {Math.round(suggestion.confidence * 100)}%</span>
                          <span>{suggestion.source === "search" ? copy.searchCalibration : copy.modelCalibration}</span>
                          {!context.originalMatched ? <span className="warning">{copy.originalSpanNotFound}</span> : null}
                          <span className="asr-suggestion-detail">
                            {copy.suggestionDetail}
                          </span>
                        </div>
                        <div className="asr-diff contextual">
                          <div>
                            <small>{copy.originalText}</small>
                            <HighlightedSuggestionText
                              text={context.originalLine}
                              highlight={suggestion.original_text}
                              variant="original"
                              tooltip={tooltip}
                              suggestionId={suggestion.id}
                              onMarkerEnter={showSuggestionHover}
                              onMarkerLeave={scheduleHoverClose}
                            />
                            {!context.originalMatched ? <em>{copy.candidateSpan}: {suggestion.original_text}</em> : null}
                          </div>
                          <div>
                            <small>{copy.correctedText}</small>
                            <HighlightedSuggestionText
                              text={context.correctedLine}
                              highlight={suggestion.corrected_text}
                              variant="corrected"
                              tooltip={tooltip}
                              suggestionId={suggestion.id}
                              onMarkerEnter={showSuggestionHover}
                              onMarkerLeave={scheduleHoverClose}
                            />
                          </div>
                        </div>
                        <div className="asr-suggestion-note">
                          <p><strong>{copy.reason}</strong>{suggestion.reason}</p>
                          {suggestion.evidence ? <p><strong>{copy.evidence}</strong>{suggestion.evidence}</p> : null}
                        </div>
                        <div className="asr-suggestion-actions">
                          <button type="button" onClick={() => void acceptSuggestion(suggestion.id)} disabled={suggestion.status !== "pending"}>
                            <Check size={14} />
                            {copy.acceptChange}
                          </button>
                          <button type="button" onClick={() => rejectSuggestion(suggestion.id)} disabled={suggestion.status !== "pending"}>
                            <X size={14} />
                            {copy.rejectChange}
                          </button>
                        </div>
                      </article>
                    );
                  })}
                </div>
              </section>
            ) : null}
          </aside>
        </div>
      )}
      {hoverCard && hoverSuggestion && hoverSuggestion.status === "pending" ? (
        <div
          className="asr-hover-card"
          style={{ left: hoverCard.left, top: hoverCard.top }}
          onMouseEnter={clearHoverHideTimer}
          onMouseLeave={scheduleHoverClose}
          role="dialog"
          aria-label={copy.suggestionDetail}
        >
          <div className="asr-hover-card-meta">
            <span>{formatTime(hoverSuggestion.start)}</span>
            <span>{copy.confidence} {Math.round(hoverSuggestion.confidence * 100)}%</span>
          </div>
          <p><strong>{copy.reason}</strong>{hoverSuggestion.reason}</p>
          {hoverSuggestion.evidence ? <p><strong>{copy.evidence}</strong>{hoverSuggestion.evidence}</p> : null}
          <div className="asr-hover-actions">
            <button type="button" onClick={() => acceptHoveredSuggestion(hoverSuggestion.id)}>
              <Check size={13} />
              {copy.acceptChange}
            </button>
            <button type="button" onClick={() => rejectHoveredSuggestion(hoverSuggestion.id)}>
              <X size={13} />
              {copy.rejectChange}
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function HighlightedSuggestionText({
  text,
  highlight,
  variant,
  tooltip,
  suggestionId,
  onMarkerEnter,
  onMarkerLeave,
}: {
  text: string;
  highlight: string;
  variant: "original" | "corrected";
  tooltip?: string;
  suggestionId?: string;
  onMarkerEnter?: (suggestionId: string, event: ReactMouseEvent<HTMLElement>) => void;
  onMarkerLeave?: () => void;
}) {
  const index = highlight ? text.indexOf(highlight) : -1;
  if (index < 0) {
    return <span className="asr-diff-text">{text}</span>;
  }
  return (
    <span className="asr-diff-text">
      {text.slice(0, index)}
      <mark
        className={`asr-highlight ${variant}`}
        data-tooltip={tooltip}
        onMouseEnter={(event) => {
          if (suggestionId) onMarkerEnter?.(suggestionId, event);
        }}
        onMouseLeave={onMarkerLeave}
      >
        {highlight}
      </mark>
      {text.slice(index + highlight.length)}
    </span>
  );
}

function AsrSourceEditor({
  refObject,
  value,
  highlights,
  activeSuggestionId,
  suggestionById,
  copy,
  onChange,
  onScroll,
  onMarkerEnter,
  onMarkerLeave,
}: {
  refObject: MutableRefObject<HTMLTextAreaElement | null>;
  value: string;
  highlights: AsrEditorHighlightRange[];
  activeSuggestionId?: string;
  suggestionById?: Map<string, AsrCorrectionSuggestion>;
  copy?: (typeof COPY)[UiLanguage];
  onChange: (value: string) => void;
  onScroll?: (scroll: { left: number; top: number }) => void;
  onMarkerEnter?: (suggestionId: string, event: ReactMouseEvent<HTMLElement>) => void;
  onMarkerLeave?: () => void;
}) {
  const [scroll, setScroll] = useState({ left: 0, top: 0 });
  const renderOptions = {
    activeSuggestionId,
    suggestionById,
    copy,
    onMarkerEnter,
    onMarkerLeave,
    onMarkerMouseDown: (range: AsrEditorHighlightRange, event: ReactMouseEvent<HTMLElement>) => {
      event.preventDefault();
      refObject.current?.focus();
      refObject.current?.setSelectionRange(range.start, range.end);
    },
  };
  return (
    <div className="asr-editor-shell">
      <div className="asr-editor-backdrop" aria-hidden="true">
        <pre style={{ transform: `translate(${-scroll.left}px, ${-scroll.top}px)` }}>
          {renderAsrEditorText(value, highlights, renderOptions)}
        </pre>
      </div>
      <textarea
        ref={refObject}
        className="asr-editor"
        value={value}
        spellCheck={false}
        onChange={(event) => onChange(event.target.value)}
        onScroll={(event) => {
          const nextScroll = {
            left: event.currentTarget.scrollLeft,
            top: event.currentTarget.scrollTop,
          };
          setScroll(nextScroll);
          onScroll?.(nextScroll);
        }}
      />
      {onMarkerEnter ? (
        <div className="asr-editor-hover-layer" aria-hidden="true">
          <pre style={{ transform: `translate(${-scroll.left}px, ${-scroll.top}px)` }}>
            {renderAsrEditorText(value, highlights, renderOptions)}
          </pre>
        </div>
      ) : null}
    </div>
  );
}

function renderAsrEditorText(
  value: string,
  highlights: AsrEditorHighlightRange[],
  options: {
    activeSuggestionId?: string;
    suggestionById?: Map<string, AsrCorrectionSuggestion>;
    copy?: (typeof COPY)[UiLanguage];
    onMarkerEnter?: (suggestionId: string, event: ReactMouseEvent<HTMLElement>) => void;
    onMarkerLeave?: () => void;
    onMarkerMouseDown?: (range: AsrEditorHighlightRange, event: ReactMouseEvent<HTMLElement>) => void;
  } = {},
): ReactNode[] {
  const nodes: ReactNode[] = [];
  let cursor = 0;
  for (const range of highlights) {
    if (range.start < cursor) continue;
    if (range.start > cursor) {
      nodes.push(value.slice(cursor, range.start));
    }
    const suggestion = options.suggestionById?.get(range.id);
    const tooltip = suggestion && options.copy ? asrSuggestionTitle(suggestion, options.copy) : undefined;
    nodes.push(
      <mark
        className={`asr-editor-mark ${range.variant} ${range.status} ${
          range.id === options.activeSuggestionId ? "active" : ""
        }`}
        data-tooltip={tooltip}
        data-asr-marker-id={range.id}
        data-asr-marker-variant={range.variant}
        key={`${range.id}-${range.start}`}
        onMouseEnter={(event) => options.onMarkerEnter?.(range.id, event)}
        onMouseLeave={options.onMarkerLeave}
        onMouseDown={(event) => options.onMarkerMouseDown?.(range, event)}
      >
        {value.slice(range.start, range.end)}
      </mark>,
    );
    cursor = range.end;
  }
  nodes.push(value.slice(cursor) || " ");
  return nodes;
}

function asrSuggestionTitle(suggestion: AsrCorrectionSuggestion, copy: (typeof COPY)[UiLanguage]): string {
  const lines = [`${copy.reason}: ${suggestion.reason || ""}`];
  if (suggestion.evidence) {
    lines.push(`${copy.evidence}: ${suggestion.evidence}`);
  }
  return lines.join("\n");
}

function findAsrEditorMarker(
  scope: "source" | "preview",
  suggestionId: string,
  variant: "original" | "corrected",
): HTMLElement | null {
  const escapedId = typeof CSS !== "undefined" && CSS.escape ? CSS.escape(suggestionId) : suggestionId;
  return document.querySelector<HTMLElement>(
    `.asr-transcript-pane.${scope} .asr-editor-backdrop [data-asr-marker-id="${escapedId}"][data-asr-marker-variant="${variant}"]`,
  );
}

function draftFromModelSettings(settings: ModelSettings, preferredActiveProfileId?: string): SettingsDraft {
  const profiles =
    settings.profiles.length > 0
      ? settings.profiles.map((profile) => ({
          ...profile,
          context_window: formatNullableNumberInput(profile.context_window),
          max_tokens: formatNullableNumberInput(profile.max_tokens),
          api_key: maskedSecretValue(profile.api_key_preview),
        }))
      : [
          {
            id: "default",
            name: "",
            provider_type: "openai" as ModelProviderType,
            base_url: "",
            model: "",
            context_window: "",
            max_tokens: "",
            has_api_key: false,
            api_key_preview: null,
            api_key: "",
          },
        ];
  const firstId = profiles[0]?.id ?? "default";
  const activeProfileId =
    preferredActiveProfileId && profiles.some((profile) => profile.id === preferredActiveProfileId)
      ? preferredActiveProfileId
      : firstId;
  return {
    profiles,
    active_profile_id: activeProfileId,
    translation_model_id: settings.translation_model_id || firstId,
    learning_model_id: settings.learning_model_id || firstId,
    global_model_id: settings.global_model_id || firstId,
    asr_model_id: settings.asr_model_id || firstId,
    study_detail_level: "faithful",
    task_parameters: taskParametersToDraft(settings.task_parameters),
  };
}

function modelProfileDraftToInput(profile: ModelProfileDraft): ModelProfileInput {
  return {
    id: profile.id,
    name: profile.name,
    provider_type: profile.provider_type,
    base_url: profile.base_url,
    model: profile.model,
    context_window: parsePositiveIntegerInput(profile.context_window),
    max_tokens: parsePositiveIntegerInput(profile.max_tokens),
    api_key: secretInputValue(profile.api_key, profile.api_key_preview),
  };
}

function savedProfileToInput(profile: ModelProfile): ModelProfileInput {
  return {
    id: profile.id,
    name: profile.name,
    provider_type: profile.provider_type,
    base_url: profile.base_url,
    model: profile.model,
    context_window: profile.context_window ?? null,
    max_tokens: profile.max_tokens ?? null,
  };
}

function modelSettingsToInput(settings: ModelSettings): ModelSettingsInput {
  return {
    profiles: settings.profiles.map(savedProfileToInput),
    translation_model_id: settings.translation_model_id,
    learning_model_id: settings.learning_model_id,
    global_model_id: settings.global_model_id,
    asr_model_id: settings.asr_model_id,
    study_detail_level: "faithful",
    task_parameters: settings.task_parameters,
  };
}

function emptyTaskParameterDrafts(): Record<TaskParameterKey, TaskParameterDraft> {
  return TASK_PARAMETER_KEYS.reduce(
    (accumulator, key) => {
      accumulator[key] = { temperature: "", max_tokens: "" };
      return accumulator;
    },
    {} as Record<TaskParameterKey, TaskParameterDraft>,
  );
}

function taskParametersToDraft(
  taskParameters: Partial<Record<TaskParameterKey, TaskParameterOverride>> | undefined,
): Record<TaskParameterKey, TaskParameterDraft> {
  const draft = emptyTaskParameterDrafts();
  TASK_PARAMETER_KEYS.forEach((key) => {
    const parameter = taskParameters?.[key];
    draft[key] = {
      temperature: formatNullableNumberInput(parameter?.temperature ?? null),
      max_tokens: formatNullableNumberInput(parameter?.max_tokens ?? null),
    };
  });
  return draft;
}

function taskParameterDraftsToInput(
  drafts: Record<TaskParameterKey, TaskParameterDraft>,
): Partial<Record<TaskParameterKey, TaskParameterOverride>> {
  return TASK_PARAMETER_KEYS.reduce(
    (accumulator, key) => {
      const temperature = parseNullableNumberInput(drafts[key].temperature);
      const maxTokens = parsePositiveIntegerInput(drafts[key].max_tokens);
      if (temperature !== null || maxTokens !== null) {
        accumulator[key] = {
          temperature,
          max_tokens: maxTokens,
        };
      }
      return accumulator;
    },
    {} as Partial<Record<TaskParameterKey, TaskParameterOverride>>,
  );
}

function taskParameterLabel(key: TaskParameterKey, copy: (typeof COPY)[UiLanguage]): string {
  return {
    title_translation: copy.titleTranslationTask,
    subtitle_translation: copy.subtitleTranslationTask,
    asr_correction: copy.asrCorrectionTask,
    semantic_segmentation: copy.semanticSegmentationTask,
    guide: copy.guideTask,
    outline: copy.outlineTask,
    interpretation: copy.interpretationTask,
    high_fidelity: copy.highFidelityTask,
  }[key];
}

function SettingsModal({
  scope = "workspace",
  copy,
  draft,
  onlineAsrDraft,
  modelSettings,
  busy,
  message,
  roleBusy,
  roleMessage,
  onClose,
  onAddProfile,
  onDraftChange,
  onOnlineAsrDraftChange,
  onOnlineAsrProviderChange,
  onRoleChange,
  onSave,
}: {
  scope?: "workspace" | "asr";
  copy: (typeof COPY)[UiLanguage];
  draft: SettingsDraft;
  onlineAsrDraft: OnlineAsrDraft;
  modelSettings: ModelSettings | null;
  busy: boolean;
  message: string | null;
  roleBusy: boolean;
  roleMessage: string | null;
  onClose: () => void;
  onAddProfile: () => void;
  onDraftChange: (draft: SettingsDraft) => void;
  onOnlineAsrDraftChange: (draft: OnlineAsrDraft) => void;
  onOnlineAsrProviderChange: (provider: OnlineAsrProvider) => void;
  onRoleChange: (role: ModelRoleKey, profileId: string) => void;
  onSave: () => void;
}) {
  const isAsrScope = scope === "asr";
  const selectedProfile = draft.profiles.find((profile) => profile.id === draft.active_profile_id) ?? draft.profiles[0];
  const [modelOptions, setModelOptions] = useState<string[]>([]);
  const [modelsBusy, setModelsBusy] = useState(false);
  const [modelsMessage, setModelsMessage] = useState<string | null>(null);
  const [onlineAsrOpen, setOnlineAsrOpen] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const roleProfiles = modelSettings?.profiles.length ? modelSettings.profiles : draft.profiles;
  const roleProfileIds = useMemo(() => new Set(roleProfiles.map((profile) => profile.id)), [roleProfiles]);
  const profileOptions = draft.profiles.map((profile) => (
    <option value={profile.id} key={profile.id}>
      {profile.name || profile.model || copy.unnamedModelProfile}
    </option>
  ));
  const roleProfileOptions = roleProfiles.map((profile) => (
    <option value={profile.id} key={profile.id}>
      {profile.name || profile.model || copy.unnamedModelProfile}
    </option>
  ));
  const filteredModelOptions = useMemo(() => {
    const query = (selectedProfile?.model ?? "").trim().toLowerCase();
    const candidates = query
      ? modelOptions.filter((model) => model.toLowerCase().includes(query))
      : modelOptions;
    return candidates.slice(0, 10);
  }, [modelOptions, selectedProfile?.model]);

  useEffect(() => {
    setModelOptions([]);
    setModelsMessage(null);
  }, [selectedProfile?.id]);

  function updateSelectedProfile(update: Partial<ModelProfileDraft>) {
    if (!selectedProfile) return;
    onDraftChange({
      ...draft,
      profiles: draft.profiles.map((profile) =>
        profile.id === selectedProfile.id ? { ...profile, ...update } : profile,
      ),
    });
  }

  function updateTaskParameter(key: TaskParameterKey, field: keyof TaskParameterDraft, value: string) {
    onDraftChange({
      ...draft,
      task_parameters: {
        ...draft.task_parameters,
        [key]: {
          ...draft.task_parameters[key],
          [field]: value,
        },
      },
    });
  }

  function updateOnlineAsrDraft(update: Partial<OnlineAsrDraft>) {
    onOnlineAsrDraftChange({ ...onlineAsrDraft, ...update });
  }

  function updateProviderType(providerType: ModelProviderType) {
    if (!selectedProfile || selectedProfile.provider_type === providerType) return;
    setModelOptions([]);
    setModelsMessage(null);
    updateSelectedProfile({ provider_type: providerType });
  }

  function setRole(role: ModelRoleKey, id: string) {
    onRoleChange(role, id);
  }

  function roleValue(role: ModelRoleKey): string {
    return roleProfileIds.has(draft[role]) ? draft[role] : (roleProfiles[0]?.id ?? "");
  }

  async function handleFetchModels() {
    if (!selectedProfile?.base_url.trim()) return;
    setModelsBusy(true);
    setModelsMessage(null);
    try {
      const payload = await listAvailableModels({
        provider_type: selectedProfile.provider_type ?? "openai",
        base_url: selectedProfile.base_url,
        api_key: secretInputValue(selectedProfile.api_key, selectedProfile.api_key_preview),
        profile_id: selectedProfile.id,
      });
      setModelOptions(payload.models);
      setModelsMessage(payload.models.length ? null : copy.noModelCandidates);
    } catch (err) {
      setModelsMessage(`${copy.modelFetchFailed}: ${errorMessage(err, copy.unknownError)}`);
    } finally {
      setModelsBusy(false);
    }
  }

  const configuredCount = modelSettings?.profiles.filter((profile) => profile.has_api_key).length ?? 0;
  const baseUrlPlaceholder =
    selectedProfile?.provider_type === "anthropic" ? "https://api.anthropic.com/v1" : "https://api.openai.com/v1";
  const taskParameterKeys: TaskParameterKey[] = isAsrScope ? ["asr_correction"] : TASK_PARAMETER_KEYS;

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="settings-modal" role="dialog" aria-modal="true" aria-labelledby="settings-title">
        <div className="modal-head">
          <div>
            <h2 id="settings-title">{isAsrScope ? copy.asrModelSettingsTitle : copy.modelSettingsTitle}</h2>
            <p>
              {configuredCount ? `${copy.modelConfigured} · ${configuredCount}` : copy.modelNotConfigured}
              {selectedProfile?.api_key_preview ? ` · ${selectedProfile.api_key_preview}` : ""}
            </p>
          </div>
          <button className="icon-only" aria-label={copy.closeSettings} onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        {!isAsrScope ? (
          <div className="settings-grid">
            <label className="settings-field">
              <span>{copy.translationModel}</span>
              <select
                value={roleValue("translation_model_id")}
                disabled={roleBusy || !roleProfiles.length}
                onChange={(event) => setRole("translation_model_id", event.target.value)}
              >
                {roleProfileOptions}
              </select>
              <small>{copy.translationModelHelp}</small>
            </label>
            <label className="settings-field">
              <span>{copy.learningModel}</span>
              <select
                value={roleValue("learning_model_id")}
                disabled={roleBusy || !roleProfiles.length}
                onChange={(event) => setRole("learning_model_id", event.target.value)}
              >
                {roleProfileOptions}
              </select>
              <small>{copy.learningModelHelp}</small>
            </label>
            <label className="settings-field">
              <span>{copy.globalModel}</span>
              <select
                value={roleValue("global_model_id")}
                disabled={roleBusy || !roleProfiles.length}
                onChange={(event) => setRole("global_model_id", event.target.value)}
              >
                {roleProfileOptions}
              </select>
              <small>{copy.globalModelHelp}</small>
            </label>
          </div>
        ) : null}
        {!isAsrScope && roleMessage ? (
          <div className="settings-role-status" aria-live="polite">
            {roleBusy ? <Loader2 className="spin" size={13} /> : null}
            <span>{roleMessage}</span>
          </div>
        ) : null}
        {!isAsrScope ? (
          <div className="settings-advanced online-asr-settings">
            <button
              type="button"
              className="settings-advanced-toggle"
              aria-expanded={onlineAsrOpen}
              onClick={() => setOnlineAsrOpen((value) => !value)}
            >
              <ChevronRight size={16} className={onlineAsrOpen ? "rotate" : ""} />
              {copy.onlineAsrSettingsTitle}
            </button>
            {onlineAsrOpen ? (
              <>
                <p>{copy.onlineAsrSettingsHelp}</p>
                <div className="settings-grid compact-settings-grid">
                  <label className="settings-field">
                    <span>{copy.onlineAsrProvider}</span>
                    <select
                      value={onlineAsrDraft.provider}
                      onChange={(event) => onOnlineAsrProviderChange(event.target.value as OnlineAsrProvider)}
                    >
                      <option value="none">{copy.onlineAsrProviderNone}</option>
                      <option value="openai">{copy.onlineAsrProviderOpenAI}</option>
                      <option value="groq">{copy.onlineAsrProviderGroq}</option>
                      <option value="xai">{copy.onlineAsrProviderXai}</option>
                      <option value="custom">{copy.onlineAsrProviderCustom}</option>
                    </select>
                  </label>
                  {onlineAsrDraft.provider === "custom" ? (
                    <label className="settings-field">
                      <span>{copy.onlineAsrCustomModel}</span>
                      <input
                        value={onlineAsrDraft.custom_model}
                        onChange={(event) => updateOnlineAsrDraft({ custom_model: event.target.value })}
                        placeholder="whisper-large-v3"
                      />
                    </label>
                  ) : null}
                </div>
                {onlineAsrDraft.provider === "custom" ? (
                  <label className="settings-field">
                    <span>{copy.onlineAsrCustomBaseUrl}</span>
                    <input
                      value={onlineAsrDraft.custom_base_url}
                      onChange={(event) => updateOnlineAsrDraft({ custom_base_url: event.target.value })}
                      placeholder="https://api.example.com/v1/audio/transcriptions"
                    />
                  </label>
                ) : null}
                {onlineAsrDraft.provider !== "none" ? (
                  <label className="settings-field">
                    <span>{copy.onlineAsrApiKey}</span>
                    <input
                      aria-label={copy.onlineAsrApiKey}
                      autoComplete="off"
                      value={onlineAsrApiKeyValue(onlineAsrDraft)}
                      onChange={(event) =>
                        updateOnlineAsrDraft(onlineAsrApiKeyUpdate(onlineAsrDraft.provider, event.target.value))
                      }
                      placeholder={onlineAsrApiKeyPreview(onlineAsrDraft) ? copy.modelApiKeyHint : copy.apiKeyOptionalHint}
                    />
                    <small>
                      {onlineAsrDraft.provider === "custom" ? copy.onlineAsrCustomHelp : copy.onlineAsrPresetHelp}
                    </small>
                  </label>
                ) : null}
              </>
            ) : null}
          </div>
        ) : null}
        <div className="settings-subhead">
          <span>{isAsrScope ? copy.asrModelProfileLibrary : copy.modelProfileLibrary}</span>
          <button type="button" className="secondary-action" onClick={onAddProfile}>
            {copy.addModelProfile}
          </button>
        </div>
        <label className="settings-field">
          <span>{copy.activeModelProfile}</span>
          <select
            value={selectedProfile?.id ?? ""}
            onChange={(event) => onDraftChange({ ...draft, active_profile_id: event.target.value })}
          >
            {profileOptions}
          </select>
        </label>
        <label className="settings-field">
          <span>{copy.providerType}</span>
          <select
            value={selectedProfile?.provider_type ?? "openai"}
            onChange={(event) => updateProviderType(event.target.value as ModelProviderType)}
          >
            <option value="openai">{copy.providerOpenAI}</option>
            <option value="anthropic">{copy.providerAnthropic}</option>
          </select>
        </label>
        <label className="settings-field">
          <span>{copy.profileName}</span>
          <input
            value={selectedProfile?.name ?? ""}
            onChange={(event) => updateSelectedProfile({ name: event.target.value })}
          />
        </label>
        <label className="settings-field">
          <span>{copy.modelBaseUrl}</span>
          <input
            value={selectedProfile?.base_url ?? ""}
            onChange={(event) => updateSelectedProfile({ base_url: event.target.value })}
            placeholder={baseUrlPlaceholder}
          />
        </label>
        <label className="settings-field">
          <span>{copy.modelName}</span>
          <input
            list="course-navigator-model-options"
            value={selectedProfile?.model ?? ""}
            onChange={(event) => updateSelectedProfile({ model: event.target.value })}
          />
          <datalist id="course-navigator-model-options">
            {modelOptions.map((model) => (
              <option value={model} key={model} />
            ))}
          </datalist>
        </label>
        <div className="settings-fetch-row">
          <button type="button" className="secondary-action" onClick={handleFetchModels} disabled={modelsBusy || !selectedProfile?.base_url.trim()}>
            {modelsBusy ? <Loader2 className="spin" size={14} /> : null}
            {modelsBusy ? copy.fetchingModels : copy.fetchModels}
          </button>
          {modelsMessage ? <span>{modelsMessage}</span> : null}
        </div>
        {filteredModelOptions.length ? (
          <div className="model-candidates" aria-label={copy.modelName}>
            {filteredModelOptions.map((model) => (
              <button type="button" key={model} onClick={() => updateSelectedProfile({ model })}>
                {model}
              </button>
            ))}
          </div>
        ) : null}
        <div className="settings-advanced">
          <button
            type="button"
            className="settings-advanced-toggle"
            aria-expanded={advancedOpen}
            onClick={() => setAdvancedOpen((value) => !value)}
          >
            <ChevronRight size={16} className={advancedOpen ? "rotate" : ""} />
            {copy.advancedModelSettings}
          </button>
          {advancedOpen ? (
            <>
              <p>{copy.advancedModelSettingsHelp}</p>
              <h3 className="settings-mini-title">{copy.modelCapabilitySettings}</h3>
              <div className="settings-grid compact-settings-grid">
                <label className="settings-field">
                  <span>{copy.contextWindow}</span>
                  <input
                    inputMode="numeric"
                    value={selectedProfile?.context_window ?? ""}
                    onChange={(event) => updateSelectedProfile({ context_window: event.target.value })}
                  />
                </label>
                <label className="settings-field">
                  <span>{copy.maxTokens}</span>
                  <input
                    inputMode="numeric"
                    value={selectedProfile?.max_tokens ?? ""}
                    onChange={(event) => updateSelectedProfile({ max_tokens: event.target.value })}
                  />
                </label>
              </div>
              <div className="task-parameters-head">
                <h3 className="settings-mini-title">{copy.taskStrategySettings}</h3>
                <p>{copy.taskStrategyHelp}</p>
              </div>
              <div className="task-parameter-grid">
                <div className="task-parameter-grid-head" aria-hidden="true">
                  <span />
                  <span>Temperature</span>
                  <span>{copy.taskMaxTokens}</span>
                </div>
                {taskParameterKeys.map((key) => {
                  const label = taskParameterLabel(key, copy);
                  return (
                    <div className="task-parameter-row" key={key}>
                      <span>{label}</span>
                      <input
                        aria-label={`${label} Temperature`}
                        inputMode="decimal"
                        value={draft.task_parameters[key].temperature}
                        onChange={(event) => updateTaskParameter(key, "temperature", event.target.value)}
                      />
                      <input
                        aria-label={`${label} ${copy.taskMaxTokens}`}
                        inputMode="numeric"
                        value={draft.task_parameters[key].max_tokens}
                        onChange={(event) => updateTaskParameter(key, "max_tokens", event.target.value)}
                      />
                    </div>
                  );
                })}
              </div>
            </>
          ) : null}
        </div>
        <label className="settings-field">
          <span>{copy.modelApiKey}</span>
          <input
            autoComplete="off"
            value={selectedProfile?.api_key ?? ""}
            onChange={(event) => updateSelectedProfile({ api_key: event.target.value })}
            placeholder={selectedProfile?.api_key_preview ? copy.modelApiKeyHint : copy.apiKeyOptionalHint}
          />
        </label>
        <div className="modal-actions">
          {message ? <span>{message}</span> : null}
          <button onClick={onSave} disabled={busy}>
            {busy ? <Loader2 className="spin" size={15} /> : null}
            {isAsrScope ? copy.saveAsrSettings : copy.saveSettings}
          </button>
        </div>
      </section>
    </div>
  );
}

function Player({
  item,
  seekTime,
  sourceMode,
  onProgress,
  copy,
  translatedTranscript,
  textDisplayMode,
  captionPlacement,
  fullscreenRequestId,
  allowBilibiliEmbed,
  onForceBilibiliEmbed,
}: {
  item: CourseItem | null;
  seekTime: number;
  sourceMode: SourceMode;
  onProgress: (seconds: number) => void;
  copy: (typeof COPY)[UiLanguage];
  translatedTranscript: TranscriptSegment[];
  textDisplayMode: CaptionDisplayMode;
  captionPlacement: CaptionPlacement;
  fullscreenRequestId: number;
  allowBilibiliEmbed: boolean;
  onForceBilibiliEmbed: (itemId: string) => void;
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const shellRef = useRef<HTMLDivElement | null>(null);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const youtubePlayerRef = useRef<YouTubePlayer | null>(null);
  const fullscreenHintTimerRef = useRef<number | undefined>(undefined);
  const pendingSeekTimeRef = useRef(0);
  const [localTime, setLocalTime] = useState(0);
  const [embedTime, setEmbedTime] = useState(0);
  const [isShellFullscreen, setIsShellFullscreen] = useState(false);
  const [showFullscreenHint, setShowFullscreenHint] = useState(false);
  const [nativeCaptionTrackUrl, setNativeCaptionTrackUrl] = useState<string | null>(null);
  const lastFullscreenRequestRef = useRef(fullscreenRequestId);
  const youtubeId = item ? getYouTubeVideoId(item.source_url) : null;
  const bilibiliId = useMemo(() => {
    if (!item) return null;
    const directId = getBilibiliVideoId(item.source_url) ?? getBilibiliVideoId(item.metadata?.webpage_url ?? "");
    if (directId) return directId;
    const extractor = item.metadata?.extractor?.toLowerCase() ?? "";
    return extractor.includes("bilibili") && item.metadata?.id?.startsWith("BV") ? item.metadata.id : null;
  }, [item]);
  const streamUrl = item?.metadata?.stream_url ?? null;
  const nativeVideoSrc =
    sourceMode === "local" && item?.local_video_path
      ? itemVideoPath(item.id)
      : sourceMode === "embed" && !youtubeId && !bilibiliId && streamUrl
        ? streamUrl
        : null;
  const youtubeEmbedSrc = useMemo(() => {
    if (!youtubeId) return null;
    const params = new URLSearchParams({
      enablejsapi: "1",
      origin: window.location.origin,
      rel: "0",
      modestbranding: "1",
      playsinline: "1",
      cc_load_policy: "0",
      fs: "0",
      iv_load_policy: "3",
    });
    return `https://www.youtube.com/embed/${youtubeId}?${params.toString()}`;
  }, [youtubeId]);
  const bilibiliEmbedSrc = useMemo(() => {
    if (!bilibiliId || !allowBilibiliEmbed) return null;
    const nextTime = Math.max(0, Math.floor(seekTime));
    const params = new URLSearchParams({
      bvid: bilibiliId,
      autoplay: nextTime > 0 ? "1" : "0",
      high_quality: "1",
      quality: "120",
      as_wide: "1",
      isOutside: "true",
      danmaku: "0",
    });
    if (nextTime > 0) {
      params.set("t", String(nextTime));
    }
    return `https://player.bilibili.com/player.html?${params.toString()}`;
  }, [allowBilibiliEmbed, bilibiliId, seekTime]);
  const nativeCaptionSegments = useMemo(() => {
    if (!item || !nativeVideoSrc || textDisplayMode === "hidden") return [];
    return item.transcript
      .map((segment, index) => {
        const translated = translatedTranscript[index] ?? findSegmentByTime(translatedTranscript, segment.start);
        return {
          start: segment.start,
          end: segment.end,
          text: composeSegmentLines(segment, translated, textDisplayMode)
            .map((line) => line.text)
            .join("\n"),
        };
      })
      .filter((segment) => segment.text.trim().length > 0);
  }, [item, nativeVideoSrc, textDisplayMode, translatedTranscript]);

  useEffect(() => {
    if (!nativeCaptionSegments.length) {
      setNativeCaptionTrackUrl(null);
      return undefined;
    }
    const url = URL.createObjectURL(new Blob([buildWebVttTrack(nativeCaptionSegments)], { type: "text/vtt" }));
    setNativeCaptionTrackUrl(url);
    return () => {
      URL.revokeObjectURL(url);
    };
  }, [nativeCaptionSegments]);

  useEffect(() => {
    if (nativeVideoSrc && videoRef.current) {
      videoRef.current.currentTime = seekTime;
      setLocalTime(seekTime);
      if (seekTime > 0) {
        void videoRef.current.play().catch(() => undefined);
      }
    }
  }, [nativeVideoSrc, seekTime]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return undefined;
    const syncNativeTrackMode = () => {
      const shouldShowNativeTrack = Boolean(nativeCaptionTrackUrl && document.fullscreenElement === video);
      for (const track of Array.from(video.textTracks)) {
        track.mode = shouldShowNativeTrack ? "showing" : "disabled";
      }
    };
    syncNativeTrackMode();
    document.addEventListener("fullscreenchange", syncNativeTrackMode);
    video.addEventListener("loadedmetadata", syncNativeTrackMode);
    return () => {
      document.removeEventListener("fullscreenchange", syncNativeTrackMode);
      video.removeEventListener("loadedmetadata", syncNativeTrackMode);
    };
  }, [nativeCaptionTrackUrl]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !nativeVideoSrc || !nativeVideoSrc.includes(".m3u8")) return;
    if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = nativeVideoSrc;
      return;
    }
    let cancelled = false;
    let hls: { destroy: () => void } | null = null;
    void import("hls.js").then(({ default: Hls }) => {
      if (cancelled || !Hls.isSupported()) return;
      const instance = new Hls();
      instance.loadSource(nativeVideoSrc);
      instance.attachMedia(video);
      hls = instance;
    });
    return () => {
      cancelled = true;
      hls?.destroy();
    };
  }, [nativeVideoSrc]);

  useEffect(() => {
    if (sourceMode !== "embed") return;
    const nextTime = Math.max(0, seekTime);
    pendingSeekTimeRef.current = nextTime;
    setEmbedTime(nextTime);
    const player = youtubePlayerRef.current;
    if (player?.seekTo) {
      player.seekTo(nextTime, true);
      if (nextTime > 0) {
        player.playVideo?.();
      }
    }
  }, [bilibiliEmbedSrc, seekTime, sourceMode, youtubeEmbedSrc]);

  useEffect(() => {
    if (sourceMode !== "embed" || !youtubeEmbedSrc || !iframeRef.current) return;

    let cancelled = false;
    let poller: number | undefined;
    youtubePlayerRef.current = null;

    void loadYouTubeIframeApi().then(() => {
      if (cancelled || !iframeRef.current || !window.YT?.Player) return;
      let player: YouTubePlayer | null = null;
      player = new window.YT.Player(iframeRef.current, {
        events: {
          onReady: () => {
            suppressYouTubeCaptions(player);
            const startAt = pendingSeekTimeRef.current;
            if (startAt > 0) {
              player?.seekTo?.(startAt, true);
              player?.playVideo?.();
            }
            setEmbedTime(startAt);
            poller = window.setInterval(() => {
              const seconds = safeGetYouTubeTime(player);
              if (seconds === null) return;
              setEmbedTime(seconds);
              onProgress(seconds);
            }, 250);
          },
          onStateChange: () => {
            suppressYouTubeCaptions(player);
            const seconds = safeGetYouTubeTime(player);
            if (seconds === null) return;
            setEmbedTime(seconds);
            onProgress(seconds);
          },
        },
      });
      youtubePlayerRef.current = player;
    });

    return () => {
      cancelled = true;
      if (poller) {
        window.clearInterval(poller);
      }
      youtubePlayerRef.current = null;
    };
  }, [youtubeEmbedSrc, onProgress, sourceMode]);

  useEffect(() => () => {
    if (fullscreenHintTimerRef.current) {
      window.clearTimeout(fullscreenHintTimerRef.current);
    }
  }, []);

  useEffect(() => {
    const handleFullscreenChange = () => {
      const fullscreenElement = document.fullscreenElement;
      const isFullscreen = Boolean(fullscreenElement && shellRef.current?.contains(fullscreenElement));
      setIsShellFullscreen(isFullscreen);
      if (fullscreenHintTimerRef.current) {
        window.clearTimeout(fullscreenHintTimerRef.current);
      }
      if (isFullscreen && sourceMode === "embed") {
        setShowFullscreenHint(true);
        fullscreenHintTimerRef.current = window.setTimeout(() => setShowFullscreenHint(false), 1200);
      } else {
        setShowFullscreenHint(false);
        fullscreenHintTimerRef.current = undefined;
      }
    };
    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => {
      document.removeEventListener("fullscreenchange", handleFullscreenChange);
    };
  }, [sourceMode]);

  function toggleShellFullscreen() {
    const shell = shellRef.current;
    if (!shell) return;
    if (document.fullscreenElement && shell.contains(document.fullscreenElement)) {
      void document.exitFullscreen().catch(() => undefined);
      return;
    }
    void shell.requestFullscreen?.().catch(() => undefined);
  }

  useEffect(() => {
    if (fullscreenRequestId === lastFullscreenRequestRef.current) return;
    lastFullscreenRequestRef.current = fullscreenRequestId;
    toggleShellFullscreen();
  }, [fullscreenRequestId]);

  if (!item) {
    return (
      <div className="player-empty">
        <Play size={28} />
        <span>{copy.noVideo}</span>
      </div>
    );
  }

  if (nativeVideoSrc) {
    const showOverlay = captionPlacement === "overlay" || isShellFullscreen;
    return (
      <div className="local-player-shell" ref={shellRef}>
        <video
          ref={videoRef}
          className="player-frame"
          src={nativeVideoSrc.includes(".m3u8") ? undefined : nativeVideoSrc}
          controls
          onTimeUpdate={(event) => {
            setLocalTime(event.currentTarget.currentTime);
            onProgress(event.currentTarget.currentTime);
          }}
        >
          {nativeCaptionTrackUrl ? (
            <track key={nativeCaptionTrackUrl} kind="subtitles" src={nativeCaptionTrackUrl} label={copy.videoCaption} default />
          ) : null}
        </video>
        <button
          className="player-fullscreen-button"
          aria-label={isShellFullscreen ? copy.exitFullscreen : copy.fullscreenVideo}
          title={isShellFullscreen ? copy.exitFullscreen : copy.fullscreenVideo}
          onClick={toggleShellFullscreen}
        >
          {isShellFullscreen ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
        </button>
        {showFullscreenHint ? <div className="fullscreen-hint">{copy.fullscreenEscHint}</div> : null}
        {showOverlay ? (
          <CaptionOverlay
            sourceSegments={item.transcript}
            translatedSegments={translatedTranscript}
            currentTime={localTime}
            mode={textDisplayMode}
            copy={copy}
          />
        ) : null}
      </div>
    );
  }

  if (sourceMode === "embed" && bilibiliId && !allowBilibiliEmbed) {
    return (
      <div className="player-empty bilibili-embed-gate">
        <FileText size={28} />
        <span>{copy.bilibiliEmbedUnavailable}</span>
        <button className="force-stream-button" type="button" onClick={() => onForceBilibiliEmbed(item.id)}>
          {copy.forceStream}
        </button>
      </div>
    );
  }

  const iframeSrc = youtubeEmbedSrc ?? bilibiliEmbedSrc;
  if (iframeSrc) {
    const showOverlay = Boolean(youtubeEmbedSrc) && (captionPlacement === "overlay" || isShellFullscreen);
    return (
      <div className="player-shell" ref={shellRef}>
        <iframe
          ref={iframeRef}
          className="player-frame"
          src={iframeSrc}
          title={item.title}
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share; fullscreen"
          allowFullScreen
        />
        <button
          className="player-fullscreen-button"
          aria-label={isShellFullscreen ? copy.exitFullscreen : copy.fullscreenVideo}
          title={isShellFullscreen ? copy.exitFullscreen : copy.fullscreenVideo}
          onClick={toggleShellFullscreen}
        >
          {isShellFullscreen ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
        </button>
        {showFullscreenHint ? <div className="fullscreen-hint">{copy.fullscreenEscHint}</div> : null}
        {showOverlay ? (
          <CaptionOverlay
            sourceSegments={item.transcript}
            translatedSegments={translatedTranscript}
            currentTime={embedTime}
            mode={textDisplayMode}
            copy={copy}
            shieldNative={Boolean(youtubeEmbedSrc)}
          />
        ) : null}
      </div>
    );
  }

  return (
    <div className="player-empty">
      <FileText size={28} />
      <span>{copy.notEmbeddable}</span>
    </div>
  );
}

function CaptionOverlay({
  sourceSegments,
  translatedSegments,
  currentTime,
  mode,
  copy,
  shieldNative = false,
}: {
  sourceSegments: TranscriptSegment[];
  translatedSegments: TranscriptSegment[];
  currentTime: number;
  mode: CaptionDisplayMode;
  copy: (typeof COPY)[UiLanguage];
  shieldNative?: boolean;
}) {
  const source = findActiveSegment(sourceSegments, currentTime);
  const translated = findActiveSegment(translatedSegments, currentTime);
  const lines = composeSegmentLines(source, translated, mode);
  if (!lines.length) return null;
  return (
    <>
      {shieldNative ? <div className="caption-native-shield" /> : null}
      <div className="caption-overlay">
        {lines.map((line) => (
          <span className={line.kind === "target" ? "caption-target" : "caption-source"} key={line.key}>
            {mode === "bilingual" ? <small>{line.kind === "target" ? copy.targetLabel : copy.sourceLabel}</small> : null}
            {line.text}
          </span>
        ))}
      </div>
    </>
  );
}

function VideoCaptionDock({
  copy,
  sourceSegments,
  translatedSegments,
  currentTime,
  mode,
  placement,
  captionControlsAvailable,
  onModeChange,
  onPlacementChange,
  onFullscreen,
}: {
  copy: (typeof COPY)[UiLanguage];
  sourceSegments: TranscriptSegment[];
  translatedSegments: TranscriptSegment[];
  currentTime: number;
  mode: CaptionDisplayMode;
  placement: CaptionPlacement;
  captionControlsAvailable: boolean;
  onModeChange: (value: CaptionDisplayMode) => void;
  onPlacementChange: (value: CaptionPlacement) => void;
  onFullscreen: () => void;
}) {
  const source = findActiveSegment(sourceSegments, currentTime);
  const translated = findActiveSegment(translatedSegments, currentTime);
  const lines = composeSegmentLines(source, translated, mode);
  const captionsHidden = mode === "hidden";

  return (
    <div className="video-caption-dock">
      <div className="video-caption-toolbar">
        <span>{copy.videoCaption}</span>
        {captionControlsAvailable ? (
          <>
            <DisplayModeControls
              copy={copy}
              scopeLabel={copy.videoCaption}
              value={mode}
              onChange={onModeChange}
              allowHidden
            />
            <div className="caption-placement-controls" role="group" aria-label={copy.videoCaption}>
              <button
                className={placement === "overlay" ? "mode-chip active" : "mode-chip"}
                aria-label={copy.captionOverlay}
                title={copy.captionOverlay}
                onClick={() => onPlacementChange("overlay")}
              >
                <span className="mode-glyph">浮</span>
              </button>
              <button
                className={placement === "panel" ? "mode-chip active" : "mode-chip"}
                aria-label={copy.captionPanel}
                title={copy.captionPanel}
                onClick={() => onPlacementChange("panel")}
              >
                <span className="mode-glyph">栏</span>
              </button>
            </div>
          </>
        ) : (
          <span className="caption-dock-note">{copy.bilibiliEmbedUnavailable}</span>
        )}
        <button className="caption-fullscreen-button" type="button" onClick={onFullscreen}>
          <Maximize2 size={14} />
          <span>{copy.fullscreenVideo}</span>
        </button>
      </div>
      {captionControlsAvailable && placement === "panel" && !captionsHidden ? (
        <div className="video-caption-panel">
          {lines.length ? (
            lines.map((line) => (
              <p className={line.kind === "target" ? "caption-panel-target" : "caption-panel-source"} key={line.key}>
                {mode === "bilingual" ? <small>{line.kind === "target" ? copy.targetLabel : copy.sourceLabel}</small> : null}
                {line.text}
              </p>
            ))
          ) : (
            <p className="empty">{copy.noTranscript}</p>
          )}
        </div>
      ) : null}
    </div>
  );
}

function Transcript({
  item,
  translatedTranscript,
  textDisplayMode,
  copy,
  currentTime,
  onSeek,
  emptyLabel,
}: {
  item: CourseItem | null;
  translatedTranscript: TranscriptSegment[];
  textDisplayMode: TextDisplayMode;
  copy: (typeof COPY)[UiLanguage];
  currentTime: number;
  onSeek: (seconds: number) => void;
  emptyLabel: string;
}) {
  const rowRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const activeIndex = item ? findActiveSegmentIndex(item.transcript, currentTime) : -1;

  useEffect(() => {
    if (activeIndex < 0) return;
    scrollIntoViewIfPossible(rowRefs.current[activeIndex]);
  }, [activeIndex]);

  if (!item?.transcript.length) {
    return <p className="empty">{emptyLabel}</p>;
  }
  return (
    <div className="transcript-list">
      {item.transcript.map((segment, index) => {
        const translated = translatedTranscript[index] ?? findSegmentByTime(translatedTranscript, segment.start);
        const lines = composeSegmentLines(segment, translated, textDisplayMode);
        return (
          <button
            className={index === activeIndex ? "transcript-row active" : "transcript-row"}
            key={`${segment.start}-${index}`}
            onClick={() => onSeek(segment.start)}
            ref={(element) => {
              rowRefs.current[index] = element;
            }}
          >
            <time>{formatTime(segment.start)}</time>
            <span className="text-stack">
              {lines.map((line) => (
                <span className={line.kind === "target" ? "target-text" : "source-text"} key={line.key}>
                  {textDisplayMode === "bilingual" ? <small>{line.kind === "target" ? copy.targetLabel : copy.sourceLabel}</small> : null}
                  {line.text}
                </span>
              ))}
            </span>
          </button>
        );
      })}
    </div>
  );
}

function TimeMap({
  study,
  currentTime,
  onSeek,
  emptyLabel,
}: {
  study: StudyMaterial | null;
  currentTime: number;
  onSeek: (seconds: number) => void;
  emptyLabel: string;
}) {
  const ranges = study?.time_map ?? [];
  if (!ranges.length) {
    return <p className="empty">{emptyLabel}</p>;
  }
  return (
    <div className="time-map">
      {ranges.map((range, index) => {
        return (
          <button
            className={isTimeRangeActive(range, currentTime) ? "time-map-row active" : "time-map-row"}
            key={`${range.start}-${range.title}-${index}`}
            onClick={() => onSeek(range.start)}
          >
            <time>
              {formatTime(range.start)}-{formatTime(range.end)}
            </time>
            <span className="text-stack compact">
              <span className="target-text">{range.title}</span>
              {range.summary ? <span className="source-text">{range.summary}</span> : null}
            </span>
          </button>
        );
      })}
    </div>
  );
}

function StudyView({
  tab,
  item,
  currentTime,
  onSeek,
  copy,
  busy,
  onGenerateStudy,
}: {
  tab: AiTab;
  item: CourseItem | null;
  currentTime: number;
  onSeek: (seconds: number) => void;
  copy: (typeof COPY)[UiLanguage];
  busy: boolean;
  onGenerateStudy: () => void;
}) {
  if (!item) {
    return <p className="empty padded">{copy.selectFirst}</p>;
  }
  if (!item.transcript.length) {
    return (
      <div className="empty-state">
        <Captions size={24} />
        <p>{copy.noTranscriptForStudy}</p>
      </div>
    );
  }
  if (!hasStudyMaterial(item.study)) {
    return (
      <div className="empty-state">
        <BookOpen size={24} />
        <button
          className="study-primary-action empty-study-action"
          onClick={onGenerateStudy}
          disabled={busy || !item.transcript.length}
        >
          {copy.generateStudy}
        </button>
        <p>{copy.noStudy}</p>
      </div>
    );
  }
  const study = item.study;
  if (!study) return null;

  if (tab === "guide") {
    return (
      <div className="study-scroll">
        <section className="guide-lead">
          <h2 title={study.one_line}>{compactGuideSummary(study.one_line)}</h2>
        </section>
        <InfoList title={copy.prerequisites} items={study.prerequisites} fallback={copy.noPrerequisites} />
        <InfoList title={copy.thoughtPrompts} items={study.thought_prompts} fallback={copy.noPrompts} />
        <InfoList title={copy.reviewSuggestions} items={study.review_suggestions} fallback={copy.noReviews} />
      </div>
    );
  }

  if (tab === "outline") {
    return <OutlineStudy copy={copy} nodes={study.outline} currentTime={currentTime} onSeek={onSeek} />;
  }

  if (tab === "detailed") {
    return <TextStudy text={study.detailed_notes} currentTime={currentTime} onSeek={onSeek} />;
  }

  return <TextStudy text={study.high_fidelity_text} currentTime={currentTime} onSeek={onSeek} />;
}

function OutlineStudy({
  copy,
  nodes,
  currentTime,
  onSeek,
}: {
  copy: (typeof COPY)[UiLanguage];
  nodes: OutlineNode[];
  currentTime: number;
  onSeek: (seconds: number) => void;
}) {
  const [openIds, setOpenIds] = useState<Set<string>>(() => collectOutlineOpenIds(nodes, 2));
  const nodeRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const maxDepth = getOutlineMaxDepth(nodes);
  const activeNodeId = findVisibleActiveOutlineNodeId(nodes, currentTime, openIds);

  useEffect(() => {
    setOpenIds(collectOutlineOpenIds(nodes, 2));
  }, [nodes]);

  useEffect(() => {
    if (!activeNodeId) return;
    scrollIntoViewIfPossible(nodeRefs.current.get(activeNodeId));
  }, [activeNodeId]);

  function setDepth(depth: number) {
    setOpenIds(collectOutlineOpenIds(nodes, depth));
  }

  function toggleNode(id: string) {
    setOpenIds((current) => {
      const next = new Set(current);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  return (
    <div className="study-scroll outline-study">
      <div className="outline-controls" aria-label="大纲层级">
        <button onClick={() => setDepth(1)}>{copy.outlineLevel1}</button>
        <button onClick={() => setDepth(2)}>{copy.outlineLevel2}</button>
        {maxDepth > 2 ? (
          <button onClick={() => setDepth(Number.POSITIVE_INFINITY)}>{copy.outlineExpandAll}</button>
        ) : null}
      </div>
      {nodes.map((node) => (
        <OutlineTree
          key={node.id}
          node={node}
          onSeek={onSeek}
          openIds={openIds}
          activeNodeId={activeNodeId}
          nodeRefs={nodeRefs}
          onToggle={toggleNode}
        />
      ))}
    </div>
  );
}

function InfoList({ title, items, fallback }: { title: string; items: string[]; fallback: string }) {
  return (
    <section className="info-list">
      <h3>{title}</h3>
      {items.length ? (
        <ul>
          {items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : (
        <p>{fallback}</p>
      )}
    </section>
  );
}

function OutlineTree({
  node,
  onSeek,
  openIds,
  activeNodeId,
  nodeRefs,
  onToggle,
}: {
  node: OutlineNode;
  onSeek: (seconds: number) => void;
  openIds: Set<string>;
  activeNodeId: string | null;
  nodeRefs: MutableRefObject<Map<string, HTMLDivElement>>;
  onToggle: (id: string) => void;
}) {
  const open = openIds.has(node.id);
  const hasChildren = node.children.length > 0;
  const active = node.id === activeNodeId;
  return (
    <div
      className={active ? "outline-node active" : "outline-node"}
      ref={(element) => {
        if (element) {
          nodeRefs.current.set(node.id, element);
        } else {
          nodeRefs.current.delete(node.id);
        }
      }}
    >
      <div className="outline-head">
        {hasChildren ? (
          <button className="disclosure" onClick={() => onToggle(node.id)}>
            {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>
        ) : (
          <span className="disclosure-spacer" />
        )}
        <button className="outline-title" onClick={() => onSeek(node.start)}>
          <time>{formatTime(node.start)}</time>
          <span>{node.title}</span>
        </button>
      </div>
      {open ? (
        <div className="outline-body">
          <p>{node.summary}</p>
          {node.children.map((child) => (
            <OutlineTree
              key={child.id}
              node={child}
              onSeek={onSeek}
              openIds={openIds}
              activeNodeId={activeNodeId}
              nodeRefs={nodeRefs}
              onToggle={onToggle}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function TextStudy({ text, currentTime, onSeek }: { text: string; currentTime: number; onSeek: (seconds: number) => void }) {
  const sections = parseTextStudySections(text);
  const sectionRefs = useRef<Array<HTMLElement | null>>([]);
  const activeIndex = findActiveStudySectionIndex(sections, currentTime);

  useEffect(() => {
    if (activeIndex < 0) return;
    scrollIntoViewIfPossible(sectionRefs.current[activeIndex]);
  }, [activeIndex]);

  return (
    <div className="study-scroll prose">
      {sections.map((section, index) => (
        <section
          className={index === activeIndex ? "study-section active" : "study-section"}
          key={`${section.label}-${index}`}
          ref={(element) => {
            sectionRefs.current[index] = element;
          }}
        >
          {section.label ? (
            <button className="study-section-head" onClick={() => onSeek(section.seconds)}>
              <time>{section.label}</time>
              <span>{renderInlineMarkdown(section.title || "\u00a0")}</span>
            </button>
          ) : null}
          <div className="study-section-body">
            {section.body.map((line, lineIndex) => (
              <MarkdownBlock line={line} key={`${line}-${lineIndex}`} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function MarkdownBlock({ line }: { line: string }) {
  if (!line.trim()) {
    return <p className="blank-line">&nbsp;</p>;
  }
  const heading = line.match(/^(#{1,3})\s+(.+)$/);
  if (heading) {
    return <h3 className="md-heading">{renderInlineMarkdown(heading[2])}</h3>;
  }
  const listItem = line.match(/^\s*[-*]\s+(.+)$/);
  if (listItem) {
    return (
      <p className="md-list-item">
        <span>•</span>
        <span>{renderInlineMarkdown(listItem[1])}</span>
      </p>
    );
  }
  return <p>{renderInlineMarkdown(line)}</p>;
}

function renderInlineMarkdown(text: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={`${part}-${index}`}>{part.slice(2, -2)}</strong>;
    }
    return <span key={`${part}-${index}`}>{part}</span>;
  });
}

function parseTextStudySections(text: string): Array<{ label: string; seconds: number; title: string; body: string[] }> {
  const sections: Array<{ label: string; seconds: number; title: string; body: string[] }> = [];
  for (const line of text.split("\n")) {
    const parsed = parseTimestampLine(line);
    if (parsed) {
      sections.push({ label: parsed.label, seconds: parsed.seconds, title: parsed.text, body: [] });
      continue;
    }
    if (!sections.length) {
      sections.push({ label: "", seconds: 0, title: "", body: [] });
    }
    sections[sections.length - 1].body.push(line);
  }
  return sections;
}

function findActiveStudySectionIndex(
  sections: Array<{ seconds: number }>,
  currentTime: number,
): number {
  if (!sections.length) return -1;
  for (let index = sections.length - 1; index >= 0; index -= 1) {
    const section = sections[index];
    if (currentTime >= section.seconds) {
      return index;
    }
  }
  return -1;
}

function parseTimestampLine(line: string): { label: string; seconds: number; text: string } | null {
  const bracketMatch = line.match(/^\[(\d{2}:\d{2}(?::\d{2})?)-[^\]]+\]\s*(.*)$/);
  if (bracketMatch) {
    return {
      label: bracketMatch[1],
      seconds: displayTimeToSeconds(bracketMatch[1]),
      text: bracketMatch[2],
    };
  }

  const rangeMatch = line.match(/^(\d{2}:\d{2}(?::\d{2})?)-\d{2}:\d{2}(?::\d{2})?\s+(.*)$/);
  if (rangeMatch) {
    return {
      label: rangeMatch[1],
      seconds: displayTimeToSeconds(rangeMatch[1]),
      text: rangeMatch[2],
    };
  }

  return null;
}

function displayTimeToSeconds(value: string): number {
  const parts = value.split(":").map((part) => Number.parseInt(part, 10));
  if (parts.length === 3) {
    return parts[0] * 3600 + parts[1] * 60 + parts[2];
  }
  return parts[0] * 60 + parts[1];
}

function maskedSecretValue(preview: string | null | undefined): string {
  return preview ?? "";
}

function secretInputValue(value: string, preview: string | null | undefined): string | undefined {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  return preview && trimmed === preview.trim() ? undefined : trimmed;
}

function draftFromOnlineAsrSettings(settings: OnlineAsrSettings): OnlineAsrDraft {
  return {
    provider: settings.provider,
    openai_api_key: maskedSecretValue(settings.openai.api_key_preview),
    openai_api_key_preview: settings.openai.api_key_preview,
    groq_api_key: maskedSecretValue(settings.groq.api_key_preview),
    groq_api_key_preview: settings.groq.api_key_preview,
    xai_api_key: maskedSecretValue(settings.xai.api_key_preview),
    xai_api_key_preview: settings.xai.api_key_preview,
    custom_base_url: settings.custom.base_url ?? "",
    custom_model: settings.custom.model ?? "",
    custom_api_key: maskedSecretValue(settings.custom.api_key_preview),
    custom_api_key_preview: settings.custom.api_key_preview,
  };
}

function onlineAsrDraftToInput(draft: OnlineAsrDraft): OnlineAsrSettingsInput {
  const openaiApiKey = secretInputValue(draft.openai_api_key, draft.openai_api_key_preview);
  const groqApiKey = secretInputValue(draft.groq_api_key, draft.groq_api_key_preview);
  const xaiApiKey = secretInputValue(draft.xai_api_key, draft.xai_api_key_preview);
  const customApiKey = secretInputValue(draft.custom_api_key, draft.custom_api_key_preview);
  return {
    provider: draft.provider,
    openai: openaiApiKey ? { api_key: openaiApiKey } : {},
    groq: groqApiKey ? { api_key: groqApiKey } : {},
    xai: xaiApiKey ? { api_key: xaiApiKey } : {},
    custom: {
      base_url: draft.custom_base_url.trim() || null,
      model: draft.custom_model.trim() || null,
      ...(customApiKey ? { api_key: customApiKey } : {}),
    },
  };
}

function onlineAsrApiKeyValue(draft: OnlineAsrDraft): string {
  return {
    none: "",
    openai: draft.openai_api_key,
    groq: draft.groq_api_key,
    xai: draft.xai_api_key,
    custom: draft.custom_api_key,
  }[draft.provider];
}

function onlineAsrApiKeyPreview(draft: OnlineAsrDraft): string | null {
  return {
    none: null,
    openai: draft.openai_api_key_preview,
    groq: draft.groq_api_key_preview,
    xai: draft.xai_api_key_preview,
    custom: draft.custom_api_key_preview,
  }[draft.provider];
}

function onlineAsrApiKeyUpdate(provider: OnlineAsrProvider, value: string): Partial<OnlineAsrDraft> {
  return {
    none: {},
    openai: { openai_api_key: value },
    groq: { groq_api_key: value },
    xai: { xai_api_key: value },
    custom: { custom_api_key: value },
  }[provider];
}

function searchDraftToConfig(draft: AsrSearchDraft): AsrCorrectionSearchConfig {
  const apiKey = secretInputValue(draft.api_key, draft.api_key_preview);
  return {
    enabled: draft.enabled,
    provider: draft.provider,
    api_key: apiKey,
    base_url: draft.base_url.trim() || undefined,
    result_limit: parsePositiveIntegerInput(draft.result_limit) ?? 5,
  };
}

function settingsToSearchDraft(settings: AsrSearchSettings): AsrSearchDraft {
  const service = settings[settings.provider];
  return {
    enabled: settings.enabled,
    provider: settings.provider,
    api_key: maskedSecretValue(service.api_key_preview),
    api_key_preview: service.api_key_preview,
    base_url: settings.provider === "firecrawl" ? settings.firecrawl.base_url ?? "" : "",
    result_limit: String(settings.result_limit || 5),
  };
}

function searchDraftToSettingsInput(draft: AsrSearchDraft): AsrSearchSettingsInput {
  const resultLimit = parsePositiveIntegerInput(draft.result_limit) ?? 5;
  const apiKey = secretInputValue(draft.api_key, draft.api_key_preview);
  const input: AsrSearchSettingsInput = {
    enabled: draft.enabled,
    provider: draft.provider,
    result_limit: resultLimit,
  };
  if (draft.provider === "firecrawl") {
    input.firecrawl = {
      base_url: draft.base_url.trim() || null,
      ...(apiKey ? { api_key: apiKey } : {}),
    };
  } else if (apiKey) {
    input.tavily = { api_key: apiKey };
  }
  return input;
}

function suggestionCounts(suggestions: AsrCorrectionSuggestion[]): Record<"pending" | "accepted" | "rejected", number> {
  return suggestions.reduce(
    (counts, suggestion) => {
      counts[suggestion.status] += 1;
      return counts;
    },
    { pending: 0, accepted: 0, rejected: 0 },
  );
}

function isPreviewItem(item: CourseItem): boolean {
  return item.id.startsWith("preview-");
}

function isBilibiliItem(item: CourseItem): boolean {
  const extractor = item.metadata?.extractor?.toLowerCase() ?? "";
  return Boolean(
    getBilibiliVideoId(item.source_url) ||
      getBilibiliVideoId(item.metadata?.webpage_url ?? "") ||
      extractor.includes("bilibili"),
  );
}

function formatCourseDuration(item: CourseItem): string | null {
  const duration =
    item.duration ??
    item.metadata?.duration ??
    (item.transcript.length ? Math.max(...item.transcript.map((segment) => segment.end)) : null);
  return duration && duration > 0 ? formatTime(duration) : null;
}

function formatCourseIndexInput(value: number | null | undefined): string {
  if (value === null || value === undefined) return "";
  return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(2)));
}

function parseCourseIndex(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function parseNullableNumberInput(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatNullableNumberInput(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

function parsePositiveIntegerInput(value: string): number | null {
  const parsed = parseNullableNumberInput(value);
  if (parsed === null) return null;
  return parsed > 0 ? Math.round(parsed) : null;
}

function displayCourseNumber(item: CourseItem): string | null {
  if (item.course_index === null || item.course_index === undefined) return null;
  return formatCourseIndexInput(item.course_index);
}

function groupCourseItems(
  items: CourseItem[],
  fallbackTitle: string,
  extraCollections: string[] = [],
  collectionOrder: string[] = [],
): LibraryCollectionGroup[] {
  const groups = new Map<string, LibraryCollectionGroup>();
  for (const item of sortCourseItems(items)) {
    const value = item.collection_title?.trim() ?? "";
    const key = collectionStorageKey(value);
    const existing = groups.get(key);
    if (existing) {
      existing.items.push(item);
    } else {
      groups.set(key, {
        key,
        title: value || fallbackTitle,
        value,
        items: [item],
      });
    }
  }
  for (const collection of extraCollections) {
    const value = collection.trim();
    const key = collectionStorageKey(value);
    if (value && !groups.has(key)) {
      groups.set(key, { key, title: value, value, items: [] });
    }
  }
  const orderIndex = new Map(collectionOrder.map((key, index) => [key, index]));
  return [...groups.values()].sort((left, right) => {
    const leftIndex = orderIndex.get(left.key);
    const rightIndex = orderIndex.get(right.key);
    if (leftIndex !== undefined || rightIndex !== undefined) {
      if (leftIndex === undefined) return 1;
      if (rightIndex === undefined) return -1;
      return leftIndex - rightIndex;
    }
    return left.title.localeCompare(right.title, undefined, { sensitivity: "base", numeric: true });
  });
}

function collectionNames(
  items: CourseItem[],
  extraCollections: string[],
  fallbackTitle: string,
): Array<{ value: string; label: string }> {
  const names = mergeCollectionNames([
    "",
    ...items.map((item) => item.collection_title ?? ""),
    ...extraCollections,
  ]);
  return names.map((name) => ({
    value: name,
    label: name || fallbackTitle,
  }));
}

function mergeCollectionNames(names: string[]): string[] {
  const seen = new Set<string>();
  const merged: string[] = [];
  for (const rawName of names) {
    const name = rawName.trim();
    const key = name.toLocaleLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    merged.push(name);
  }
  return merged;
}

function loadManualCollections(): string[] {
  return loadStoredStrings(MANUAL_COLLECTIONS_STORAGE_KEY);
}

function loadStoredStrings(key: string): string[] {
  try {
    const raw = window.localStorage.getItem(key);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? mergeCollectionNames(parsed.filter((value): value is string => typeof value === "string")) : [];
  } catch {
    return [];
  }
}

function saveStoredStrings(key: string, values: string[]) {
  try {
    window.localStorage.setItem(key, JSON.stringify(values));
  } catch {
    // Storage is a convenience layer. Losing it should not block the current edit.
  }
}

function loadBooleanPreference(key: string, fallback: boolean): boolean {
  try {
    const raw = window.localStorage.getItem(key);
    if (raw === "true") return true;
    if (raw === "false") return false;
  } catch {
    return fallback;
  }
  return fallback;
}

function saveBooleanPreference(key: string, value: boolean) {
  try {
    window.localStorage.setItem(key, String(value));
  } catch {
    // Local storage is optional; the in-memory state already changed.
  }
}

function downloadJsonFile(payload: unknown, fileName: string) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function coursePackageFileName(items: CourseSharePackage["items"]): string {
  const firstTitle = items[0]?.title ?? "course-navigator";
  const slug = firstTitle
    .trim()
    .toLocaleLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fa5]+/gi, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
  return `${slug || "course-navigator"}${items.length > 1 ? `-${items.length}` : ""}.course-nav.json`;
}

function initialSelectedCourse(items: CourseItem[]): CourseItem | null {
  const selectedId = loadSelectedCourseId();
  return (selectedId ? items.find((item) => item.id === selectedId) : null) ?? items[0] ?? null;
}

function loadSelectedCourseId(): string | null {
  try {
    return window.localStorage.getItem(SELECTED_COURSE_STORAGE_KEY);
  } catch {
    return null;
  }
}

function saveSelectedCourseId(itemId: string) {
  try {
    window.localStorage.setItem(SELECTED_COURSE_STORAGE_KEY, itemId);
  } catch {
    // Remembering the last selected course is a convenience only.
  }
}

function mergeStringKeys(keys: string[]): string[] {
  return [...new Set(keys.filter(Boolean))];
}

function collectionStorageKey(value: string | null | undefined): string {
  const normalized = (value ?? "").trim().toLocaleLowerCase();
  return normalized ? `collection:${normalized}` : "collection:";
}

function sortCourseItems(items: CourseItem[]): CourseItem[] {
  return [...items].sort(compareCourseItems);
}

function compareCourseItems(left: CourseItem, right: CourseItem): number {
  const collectionCompare = (left.collection_title ?? "").localeCompare(right.collection_title ?? "", undefined, {
    sensitivity: "base",
    numeric: true,
  });
  if (collectionCompare !== 0) return collectionCompare;
  const leftHasIndex = left.course_index !== null && left.course_index !== undefined;
  const rightHasIndex = right.course_index !== null && right.course_index !== undefined;
  if (leftHasIndex !== rightHasIndex) return leftHasIndex ? -1 : 1;
  const leftOrder = left.course_index ?? left.sort_order;
  const rightOrder = right.course_index ?? right.sort_order;
  if (leftOrder !== null && leftOrder !== undefined && rightOrder !== null && rightOrder !== undefined && leftOrder !== rightOrder) {
    return leftOrder - rightOrder;
  }
  const dateCompare = Date.parse(right.created_at) - Date.parse(left.created_at);
  if (Number.isFinite(dateCompare) && dateCompare !== 0) return dateCompare;
  return left.title.localeCompare(right.title, undefined, { sensitivity: "base", numeric: true });
}

function courseGroupForItem(items: CourseItem[], item: CourseItem): CourseItem[] {
  const collectionKey = item.collection_title ?? "";
  return sortCourseItems(items.filter((entry) => (entry.collection_title ?? "") === collectionKey));
}

function canMoveCourse(items: CourseItem[], item: CourseItem, direction: -1 | 1): boolean {
  const group = courseGroupForItem(items, item);
  const index = group.findIndex((entry) => entry.id === item.id);
  return index >= 0 && Boolean(group[index + direction]);
}

function scrollIntoViewIfPossible(element: Element | null | undefined) {
  if (typeof element?.scrollIntoView === "function") {
    element.scrollIntoView({ block: "center", behavior: "smooth" });
  }
}

function findExistingItemForUrl(items: CourseItem[], sourceUrl: string): CourseItem | null {
  const sourceKey = canonicalSourceKey(sourceUrl);
  return items.find((item) => canonicalSourceKey(item.source_url) === sourceKey) ?? null;
}

function firstWords(text: string, count: number): string {
  const words = text.split(/\s+/).filter(Boolean);
  if (words.length <= count) return text;
  return `${words.slice(0, count).join(" ")}...`;
}

function compactGuideSummary(text: string): string {
  const normalized = text.replace(/\s+/g, " ").trim();
  const zhMatch = normalized.match(/(\d+\s*个学习块)[：:]\s*(.+)$/);
  if (zhMatch) {
    return `${zhMatch[1]}：${firstCompleteSentence(zhMatch[2], "zh-CN")}`;
  }
  const jaMatch = normalized.match(/(\d+\s*個の学習ブロック)[：:]\s*(.+)$/);
  if (jaMatch) {
    return `${jaMatch[1]}：${firstCompleteSentence(jaMatch[2], "ja")}`;
  }
  const enMatch = normalized.match(/(\d+\s*learning blocks)[：:]\s*(.+)$/i);
  if (enMatch) {
    return `${enMatch[1]}: ${firstCompleteSentence(enMatch[2], "en")}`;
  }
  return firstCompleteSentence(normalized, "zh-CN");
}

function hasStudyMaterial(study: StudyMaterial | null): boolean {
  if (!study) return false;
  return Boolean(
    study.time_map.length ||
      study.outline.length ||
      study.detailed_notes.trim() ||
      study.high_fidelity_text.trim() ||
      study.prerequisites.length ||
      study.thought_prompts.length ||
      study.review_suggestions.length,
  );
}

function regenerateLabelForTab(tab: StudySection, copy: (typeof COPY)[UiLanguage]): string {
  if (tab === "outline") return copy.regenerateOutline;
  if (tab === "detailed") return copy.regenerateDetailed;
  if (tab === "high") return copy.regenerateHigh;
  return copy.regenerateGuide;
}

function firstCompleteSentence(text: string, language: OutputLanguage): string {
  const normalized = text.trim();
  const sentenceMatch = normalized.match(/^(.+?[。.!?？])\s*/);
  const sentence = sentenceMatch?.[1] ?? normalized;
  const softLimit = language === "en" ? 110 : 78;
  if (sentence.length <= softLimit) return sentence;
  const clauses = sentence.split(/([，,；;、])/);
  let result = "";
  for (let index = 0; index < clauses.length; index += 2) {
    const chunk = `${clauses[index] ?? ""}${clauses[index + 1] ?? ""}`;
    if (!chunk.trim()) continue;
    if (result && result.length + chunk.length > softLimit) break;
    result += chunk;
  }
  return result.trim() || sentence;
}

function findActiveSegment(segments: TranscriptSegment[], currentTime: number): TranscriptSegment | undefined {
  const index = findActiveSegmentIndex(segments, currentTime);
  return index >= 0 ? segments[index] : undefined;
}

function findActiveSegmentIndex(segments: TranscriptSegment[], currentTime: number): number {
  return segments.findIndex(
    (segment) => currentTime >= segment.start && currentTime < Math.max(segment.end, segment.start + 0.8),
  );
}

function findSegmentByTime(segments: TranscriptSegment[], start: number): TranscriptSegment | undefined {
  return segments.find((segment) => Math.abs(segment.start - start) < 0.4);
}

function canonicalSourceKey(sourceUrl: string): string {
  const youtubeId = getYouTubeVideoId(sourceUrl);
  if (youtubeId) return `youtube:${youtubeId}`;
  try {
    const parsed = new URL(sourceUrl);
    parsed.hash = "";
    parsed.search = "";
    return parsed.toString().replace(/\/$/, "");
  } catch {
    return sourceUrl.trim();
  }
}

function isTimeRangeActive(range: StudyMaterial["time_map"][number], currentTime: number): boolean {
  return currentTime >= range.start && currentTime < Math.max(range.end, range.start + 0.8);
}

function findVisibleActiveOutlineNodeId(
  nodes: OutlineNode[],
  currentTime: number,
  openIds: Set<string>,
): string | null {
  for (const node of nodes) {
    if (!isOutlineNodeActive(node, currentTime)) continue;
    if (openIds.has(node.id)) {
      const activeChild = findVisibleActiveOutlineNodeId(node.children, currentTime, openIds);
      if (activeChild) return activeChild;
    }
    return node.id;
  }
  return null;
}

function isOutlineNodeActive(node: OutlineNode, currentTime: number): boolean {
  return currentTime >= node.start && currentTime < Math.max(node.end, node.start + 0.8);
}

function composeSegmentLines(
  source: TranscriptSegment | undefined,
  target: TranscriptSegment | undefined,
  mode: CaptionDisplayMode,
): Array<{ kind: "source" | "target"; key: string; text: string }> {
  if (mode === "hidden") {
    return [];
  }
  if (mode === "source") {
    return source ? [{ kind: "source", key: "source", text: source.text }] : [];
  }
  if (mode === "target") {
    const segment = target ?? source;
    return segment ? [{ kind: target ? "target" : "source", key: "target", text: segment.text }] : [];
  }
  const lines: Array<{ kind: "source" | "target"; key: string; text: string }> = [];
  if (target?.text && target.text !== source?.text) {
    lines.push({ kind: "target", key: "target", text: target.text });
  }
  if (source?.text) {
    lines.push({ kind: "source", key: "source", text: source.text });
  }
  return lines;
}

function TabButton({
  active,
  children,
  onClick,
}: {
  active: boolean;
  children: ReactNode;
  onClick: () => void;
}) {
  return (
    <button className={active ? "tab active" : "tab"} onClick={onClick}>
      {children}
    </button>
  );
}

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error) {
    return error.message;
  }
  return fallback;
}

function asrProgressInfo(status: StudyJobStatus, copy: (typeof COPY)[UiLanguage]) {
  const now = Date.now();
  const startedAt = status.started_at ? Date.parse(status.started_at) : Number.NaN;
  const updatedAt = status.updated_at ? Date.parse(status.updated_at) : Number.NaN;
  const elapsedMs = Number.isFinite(startedAt) ? Math.max(0, now - startedAt) : 0;
  const staleMs = Number.isFinite(updatedAt) ? Math.max(0, now - updatedAt) : 0;
  return {
    phaseLabel: asrPhaseLabel(status.phase, copy),
    elapsed: formatShortDuration(elapsedMs),
    lastUpdate: Number.isFinite(updatedAt) ? formatShortDuration(staleMs) : "-",
    stale: status.status === "running" && staleMs > 30000,
  };
}

function asrPhaseLabel(phase: string, copy: (typeof COPY)[UiLanguage]): string {
  return {
    queued: copy.asrPhaseQueued,
    preparing: copy.asrPhasePreparing,
    candidate: copy.asrPhaseCandidate,
    search: copy.asrPhaseSearch,
    background: copy.asrPhaseBackground,
    review: copy.asrPhaseReview,
    model_request: copy.asrPhaseModelRequest,
    model_wait: copy.asrPhaseModelWait,
    model_parse: copy.asrPhaseModelParse,
    finalizing: copy.asrPhaseFinalizing,
    complete: copy.asrPhaseComplete,
    failed: copy.asrPhaseFailed,
  }[phase] ?? phase;
}

function formatShortDuration(ms: number): string {
  const totalSeconds = Math.max(0, Math.round(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes ? `${minutes}m ${seconds}s` : `${seconds}s`;
}

function asrCorrectionErrorMessage(error: unknown, copy: (typeof COPY)[UiLanguage]): string {
  const message = errorMessage(error, copy.unknownError);
  return message.trim().toLowerCase() === "not found" ? copy.asrCorrectionApiUnavailable : message;
}

function extractionErrorMessage(
  error: unknown,
  mode: ExtractMode,
  browser: string,
  fallback: string,
): string {
  const message = errorMessage(error, fallback);
  if (message.startsWith("yt-dlp 已按浏览器 Cookie 来源") || message.startsWith("yt-dlp 已使用 --cookies")) {
    return message;
  }
  if (!message.includes("Sign in to confirm")) {
    return message;
  }
  if (mode === "browser") {
    return `yt-dlp 已按浏览器 Cookie 来源 ${browser || "chrome"} 调用，但 YouTube 仍要求登录验证。请确认该来源对应已登录 YouTube 的浏览器配置，例如 chrome:Default 或 chrome:Profile 1；也可以切到 Cookies 文件模式。`;
  }
  if (mode === "cookies") {
    return "yt-dlp 已按 Cookies 文件模式执行，但 YouTube 仍要求登录验证。请确认 cookies.txt 来自已登录 YouTube 的浏览器且没有过期。";
  }
  return "YouTube 要求登录验证。请把“提取登录”改为“浏览器 Cookie”或“Cookies 文件”后再提取字幕。";
}

function loadYouTubeIframeApi(): Promise<void> {
  if (window.YT?.Player) {
    return Promise.resolve();
  }
  if (youtubeApiPromise) {
    return youtubeApiPromise;
  }
  youtubeApiPromise = new Promise((resolve) => {
    const previousReady = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => {
      previousReady?.();
      resolve();
    };
    if (!document.querySelector('script[src="https://www.youtube.com/iframe_api"]')) {
      const script = document.createElement("script");
      script.src = "https://www.youtube.com/iframe_api";
      script.async = true;
      document.head.appendChild(script);
    }
  });
  return youtubeApiPromise;
}

function safeGetYouTubeTime(player: YouTubePlayer | null): number | null {
  try {
    const seconds = player?.getCurrentTime?.();
    return typeof seconds === "number" && Number.isFinite(seconds) ? seconds : null;
  } catch {
    return null;
  }
}

function suppressYouTubeCaptions(player: YouTubePlayer | null): void {
  try {
    player?.setOption?.("captions", "track", {});
    player?.setOption?.("cc", "track", {});
    player?.unloadModule?.("captions");
    player?.unloadModule?.("cc");
  } catch {
    // YouTube's iframe API exposes caption controls inconsistently across embeds.
  }
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, milliseconds);
  });
}

function collectOutlineOpenIds(nodes: OutlineNode[], depth: number): Set<string> {
  const ids = new Set<string>();
  function visit(node: OutlineNode, currentDepth: number) {
    if (currentDepth < depth && node.children.length) {
      ids.add(node.id);
      node.children.forEach((child) => visit(child, currentDepth + 1));
    }
  }
  nodes.forEach((node) => visit(node, 1));
  return ids;
}

function getOutlineMaxDepth(nodes: OutlineNode[]): number {
  if (!nodes.length) return 0;
  return Math.max(
    ...nodes.map((node) => 1 + getOutlineMaxDepth(node.children)),
  );
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function normalizedConfidenceThreshold(value: string): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 95;
  return clamp(parsed, 0, 100);
}

function playerHeightMinimum(placement: CaptionPlacement): number {
  return placement === "panel" ? MIN_PLAYER_HEIGHT_PANEL : MIN_PLAYER_HEIGHT_OVERLAY;
}
