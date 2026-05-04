import {
  ArrowDown,
  ArrowUp,
  BookOpen,
  Captions,
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  Download,
  FileText,
  FolderPlus,
  Languages,
  Loader2,
  Maximize2,
  Minimize2,
  Pencil,
  Play,
  Settings as SettingsIcon,
  Trash2,
  X,
} from "lucide-react";
import type { CSSProperties, MutableRefObject, PointerEvent as ReactPointerEvent, ReactNode } from "react";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  deleteCourse,
  deleteLocalVideo,
  extractCourse,
  getModelSettings,
  getStudyJob,
  itemVideoPath,
  listItems,
  listAvailableModels,
  previewCourse,
  saveModelSettings,
  startDownloadJob,
  startStudyJob,
  startTranslationJob,
  updateCourseItem,
} from "./api";
import type {
  CourseItem,
  ExtractMode,
  ModelProfile,
  ModelProfileInput,
  ModelProviderType,
  ModelSettings,
  ModelSettingsInput,
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
  study_detail_level: StudyDetailLevel;
  task_parameters: Record<TaskParameterKey, TaskParameterDraft>;
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
    extractSubtitles: "提取字幕",
    translateSubtitles: "翻译字幕",
    subtitleSource: "字幕来源",
    subtitleSourceOriginal: "原字幕优先",
    subtitleSourceAsr: "本地 ASR",
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
    modelProfileLibrary: "模型档案",
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
    advancedModelSettings: "高级调用参数",
    advancedModelSettingsHelp: "留空使用代码默认值。这里覆盖具体任务调用；不熟悉模型参数时建议保持默认。",
    modelCapabilitySettings: "模型能力覆盖",
    taskStrategySettings: "任务策略覆盖",
    taskStrategyHelp: "按任务分别覆盖 Temperature 和最大输出。错误设置可能导致输出变短、JSON 解析失败、成本上升或结果不稳定。",
    titleTranslationTask: "标题翻译",
    subtitleTranslationTask: "字幕翻译",
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
    modelConfigured: "已配置",
    modelNotConfigured: "未配置",
    closeSettings: "关闭设置",
    saveSettings: "保存档案",
    settingsSaved: "档案已保存",
    modelRolesSaving: "正在保存模型选择",
    modelRolesSaved: "模型选择已保存",
    modelRolesSaveFailed: "模型选择保存失败",
    analyze: "提取字幕",
    previewing: "正在打开视频预览",
    extracting: "正在提取字幕",
    generating: "正在生成学习地图",
    caching: "正在缓存本地视频",
    library: "课程库",
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
    saveCollection: "保存专辑",
    cancelCollectionEdit: "取消编辑专辑",
    collectionTitle: "专辑名称",
    collectionTitleRequired: "专辑名称不能为空。",
    courseIndex: "课程序号",
    courseTitleRequired: "课程标题不能为空。",
    moveCourseUp: "上移课程",
    moveCourseDown: "下移课程",
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
    extractSubtitles: "Extract subtitles",
    translateSubtitles: "Translate subtitles",
    subtitleSource: "Subtitle source",
    subtitleSourceOriginal: "Source first",
    subtitleSourceAsr: "Local ASR",
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
    modelProfileLibrary: "Model profiles",
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
    advancedModelSettings: "Advanced call parameters",
    advancedModelSettingsHelp: "Blank fields use code defaults. These values override individual task calls.",
    modelCapabilitySettings: "Model capability overrides",
    taskStrategySettings: "Task strategy overrides",
    taskStrategyHelp: "Override temperature and max output per task. Bad values can shorten output, break JSON, raise cost, or reduce stability.",
    titleTranslationTask: "Title translation",
    subtitleTranslationTask: "Subtitle translation",
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
    modelConfigured: "Configured",
    modelNotConfigured: "Not configured",
    closeSettings: "Close settings",
    saveSettings: "Save profile",
    settingsSaved: "Profile saved",
    modelRolesSaving: "Saving model selection",
    modelRolesSaved: "Model selection saved",
    modelRolesSaveFailed: "Failed to save model selection",
    analyze: "Extract subtitles",
    previewing: "Opening video preview",
    extracting: "Extracting subtitles",
    generating: "Generating study map",
    caching: "Caching video locally",
    library: "Library",
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
    saveCollection: "Save collection",
    cancelCollectionEdit: "Cancel collection edit",
    collectionTitle: "Collection name",
    collectionTitleRequired: "Collection name is required.",
    courseIndex: "Course no.",
    courseTitleRequired: "Course title is required.",
    moveCourseUp: "Move course up",
    moveCourseDown: "Move course down",
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
const MIN_PLAYER_HEIGHT_OVERLAY = 390;
const MIN_PLAYER_HEIGHT_PANEL = 500;
const MANUAL_COLLECTIONS_STORAGE_KEY = "course-navigator-manual-collections";
const COLLAPSED_COLLECTIONS_STORAGE_KEY = "course-navigator-collapsed-collections";
const TIME_MAP_AUTO_OPEN_STORAGE_KEY = "course-navigator-time-map-auto-open";
const TASK_PARAMETER_KEYS: TaskParameterKey[] = [
  "title_translation",
  "subtitle_translation",
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
  study_detail_level: "faithful",
  task_parameters: emptyTaskParameterDrafts(),
};

export function App() {
  const [url, setUrl] = useState("");
  const [mode, setMode] = useState<ExtractMode>("browser");
  const [browser, setBrowser] = useState("chrome");
  const [cookiesPath, setCookiesPath] = useState("");
  const [subtitleSource, setSubtitleSource] = useState<TranscriptSource>("subtitles");
  const [uiLanguage, setUiLanguage] = useState<UiLanguage>("zh-CN");
  const [outputLanguage, setOutputLanguage] = useState<OutputLanguage>("zh-CN");
  const [videoCaptionDisplayMode, setVideoCaptionDisplayMode] = useState<CaptionDisplayMode>("bilingual");
  const [videoCaptionPlacement, setVideoCaptionPlacement] = useState<CaptionPlacement>("overlay");
  const [transcriptDisplayMode, setTranscriptDisplayMode] = useState<TextDisplayMode>("bilingual");
  const [fullscreenRequestId, setFullscreenRequestId] = useState(0);
  const [items, setItems] = useState<CourseItem[]>([]);
  const [selected, setSelected] = useState<CourseItem | null>(null);
  const [forcedBilibiliEmbedIds, setForcedBilibiliEmbedIds] = useState<string[]>([]);
  const [activeTab, setActiveTab] = useState<AiTab>("guide");
  const [sourceMode, setSourceMode] = useState<SourceMode>("embed");
  const [seekTime, setSeekTime] = useState(0);
  const [playheadTime, setPlayheadTime] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<StudyJobStatus | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [modelSettings, setModelSettings] = useState<ModelSettings | null>(null);
  const [settingsDraft, setSettingsDraft] = useState<SettingsDraft>(EMPTY_SETTINGS_DRAFT);
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
  const [timeMapAutoOpen, setTimeMapAutoOpen] = useState(() =>
    loadBooleanPreference(TIME_MAP_AUTO_OPEN_STORAGE_KEY, true),
  );
  const [editingCollectionKey, setEditingCollectionKey] = useState<string | null>(null);
  const [editingCollectionDraft, setEditingCollectionDraft] = useState("");
  const [savingCollectionKey, setSavingCollectionKey] = useState<string | null>(null);
  const [savingTitleId, setSavingTitleId] = useState<string | null>(null);
  const [activeJobKind, setActiveJobKind] = useState<"study" | "translation" | "download" | null>(null);
  const workspaceRef = useRef<HTMLElement | null>(null);
  const mainColumnRef = useRef<HTMLElement | null>(null);
  const dragCleanupRef = useRef<(() => void) | null>(null);
  const copy = COPY[uiLanguage];

  useEffect(() => {
    listItems()
      .then((loaded) => {
        setItems(loaded);
        selectCourse(loaded[0] ?? null);
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
    () => groupCourseItems(items, copy.courseCollectionFallback, manualCollections),
    [items, copy.courseCollectionFallback, manualCollections],
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
      await extractUrlToItem(normalizedUrl);
    } catch (err) {
      setError(extractionErrorMessage(err, mode, browser, copy.unknownError));
    } finally {
      setBusy(null);
      setJobStatus(null);
      setActiveJobKind(null);
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
        selectCourse(loaded[0] ?? null);
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
      cancelEditingCollection();
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
      subtitle_source: subtitleSource,
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
      subtitle_source: subtitleSource,
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
        study_detail_level: "faithful",
        task_parameters: taskParameterDraftsToInput(settingsDraft.task_parameters),
      });
      setModelSettings(next);
      setSettingsDraft(draftFromModelSettings(next, settingsDraft.active_profile_id));
      setSettingsMessage(copy.settingsSaved);
    } catch (err) {
      setSettingsMessage(errorMessage(err, copy.unknownError));
    } finally {
      setSettingsBusy(false);
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
        study_detail_level: "faithful",
        task_parameters: current.task_parameters,
      };
    });
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
              onChange={(event) => setSubtitleSource(event.target.value as TranscriptSource)}
            >
              <option value="subtitles">{copy.subtitleSourceOriginal}</option>
              <option value="asr">{copy.subtitleSourceAsr}</option>
            </select>
          </label>
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
          }}
          onAddProfile={handleAddModelProfile}
          onDraftChange={setSettingsDraft}
          onRoleChange={handleSaveModelRole}
          onSave={handleSaveSettings}
        />
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
              <button
                aria-label={copy.addCollection}
                className="panel-icon-button"
                title={copy.addCollection}
                onClick={handleAddCollection}
              >
                <FolderPlus size={14} />
              </button>
            </div>
            <div className="library-list">
              {groupedItems.map((group) => {
                const collectionCollapsed = collapsedCollectionKeys.has(group.key);
                const collectionEditing = editingCollectionKey === group.key;
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
                      <button
                        aria-label={`${copy.editCollection} ${group.title}`}
                        className="library-collection-edit"
                        title={copy.editCollection}
                        onClick={() => startEditingCollection(group)}
                      >
                        <Pencil size={13} />
                      </button>
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
              <DisplayModeControls
                copy={copy}
                scopeLabel={copy.transcript}
                value={transcriptDisplayMode}
                onChange={(value) => {
                  if (value !== "hidden") setTranscriptDisplayMode(value);
                }}
              />
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

function draftFromModelSettings(settings: ModelSettings, preferredActiveProfileId?: string): SettingsDraft {
  const profiles =
    settings.profiles.length > 0
      ? settings.profiles.map((profile) => ({
          ...profile,
          context_window: formatNullableNumberInput(profile.context_window),
          max_tokens: formatNullableNumberInput(profile.max_tokens),
          api_key: "",
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
    api_key: profile.api_key || undefined,
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
    semantic_segmentation: copy.semanticSegmentationTask,
    guide: copy.guideTask,
    outline: copy.outlineTask,
    interpretation: copy.interpretationTask,
    high_fidelity: copy.highFidelityTask,
  }[key];
}

function SettingsModal({
  copy,
  draft,
  modelSettings,
  busy,
  message,
  roleBusy,
  roleMessage,
  onClose,
  onAddProfile,
  onDraftChange,
  onRoleChange,
  onSave,
}: {
  copy: (typeof COPY)[UiLanguage];
  draft: SettingsDraft;
  modelSettings: ModelSettings | null;
  busy: boolean;
  message: string | null;
  roleBusy: boolean;
  roleMessage: string | null;
  onClose: () => void;
  onAddProfile: () => void;
  onDraftChange: (draft: SettingsDraft) => void;
  onRoleChange: (role: ModelRoleKey, profileId: string) => void;
  onSave: () => void;
}) {
  const selectedProfile = draft.profiles.find((profile) => profile.id === draft.active_profile_id) ?? draft.profiles[0];
  const [modelOptions, setModelOptions] = useState<string[]>([]);
  const [modelsBusy, setModelsBusy] = useState(false);
  const [modelsMessage, setModelsMessage] = useState<string | null>(null);
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
        api_key: selectedProfile.api_key || undefined,
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

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="settings-modal" role="dialog" aria-modal="true" aria-labelledby="settings-title">
        <div className="modal-head">
          <div>
            <h2 id="settings-title">{copy.modelSettingsTitle}</h2>
            <p>
              {configuredCount ? `${copy.modelConfigured} · ${configuredCount}` : copy.modelNotConfigured}
              {selectedProfile?.api_key_preview ? ` · ${selectedProfile.api_key_preview}` : ""}
            </p>
          </div>
          <button className="icon-only" aria-label={copy.closeSettings} onClick={onClose}>
            <X size={18} />
          </button>
        </div>
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
        {roleMessage ? (
          <div className="settings-role-status" aria-live="polite">
            {roleBusy ? <Loader2 className="spin" size={13} /> : null}
            <span>{roleMessage}</span>
          </div>
        ) : null}
        <div className="settings-subhead">
          <span>{copy.modelProfileLibrary}</span>
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
                {TASK_PARAMETER_KEYS.map((key) => {
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
            type="password"
            value={selectedProfile?.api_key ?? ""}
            onChange={(event) => updateSelectedProfile({ api_key: event.target.value })}
            placeholder={copy.modelApiKeyHint}
          />
        </label>
        <div className="modal-actions">
          {message ? <span>{message}</span> : null}
          <button onClick={onSave} disabled={busy}>
            {busy ? <Loader2 className="spin" size={15} /> : null}
            {copy.saveSettings}
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
  return [...groups.values()];
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

function playerHeightMinimum(placement: CaptionPlacement): number {
  return placement === "panel" ? MIN_PLAYER_HEIGHT_PANEL : MIN_PLAYER_HEIGHT_OVERLAY;
}
