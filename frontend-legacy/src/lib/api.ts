import axios from "axios";

import type {
  AccountReportResponse,
  AgentRun,
  AnalyticsCommentInsight,
  AnalyticsHotTopic,
  AnalyticsReportResponse,
  AnalyticsTopContent,
  AuthPayload,
  AutoTask,
  AutoTaskCreatePayload,
  AutoTaskRunResult,
  AutoTaskRunStart,
  AutoTaskUpdatePayload,
  BatchCreateDraftsPayload,
  BatchCreateDraftsResponse,
  BatchTagNotesPayload,
  BatchTagNotesResponse,
  ComposeImagePayload,
  CreateDraftPayload,
  CreationSkill,
  DashboardOverview,
  DescribeImagePayload,
  Draft,
  GenerateCoverPayload,
  GeneratedImageAsset,
  GenerateImagePayload,
  GenerateImageResult,
  GenerateNotePayload,
  GenerateTagsPayload,
  GenerateTitlePayload,
  ImageUtilityFile,
  KeywordGroup,
  KeywordGroupDetail,
  KeywordGroupPayload,
  ModelConfig,
  ModelConfigPayload,
  MonitoringRefreshResponse,
  MonitoringSnapshot,
  MonitoringTarget,
  MonitoringTargetPayload,
  NoteAsset,
  NoteComment,
  NoteDiagnosis,
  NotesExportPayload,
  NotesExportResponse,
  Paginated,
  PlatformAccount,
  PlatformId,
  PlatformMeta,
  PlatformUser,
  PublishAsset,
  PublishJob,
  PublishJobUpdatePayload,
  ResizeImagePayload,
  RewriteDraftPayload,
  RunDueTasksResponse,
  SavedNote,
  SaveNotesResponse,
  SchedulerStatus,
  SendDraftToPublishPayload,
  Tag,
  TagPayload,
  TaskRecord,
  UserImageFile,
  ViralAnalysisResponse,
  ViralTemplate,
  ViralTemplateListResponse,
  XhsCreatorBridgeResult,
  XhsDataCrawlPayload,
  XhsDataCrawlResponse,
  XhsHotAccountResponse,
  XhsHotListResponse,
  XhsNoteSearchResponse,
  XhsProviderStatus,
  XhsQrLoginSession,
  XhsRedfoxBalance,
  XhsRedfoxStatus,
  XhsRedfoxUsage,
  XhsSearchNote,
  XhsSensitiveWordResult,
  XhsTrendMeta,
  XhsTrendResponse,
  XhsTrendUserResponse,
  XhsViralInsightsResponse,
} from "../types";

// ===========================================================================
// HTTP 层
// ===========================================================================

export const http = axios.create({ baseURL: "/api", timeout: 120000 });

export const REFRESH_TOKEN_KEY = "spider_xhs_refresh_token";
export const AUTH_EXPIRED_EVENT = "xhs:auth-expired";

let accessToken: string | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function hasRefreshToken(): boolean {
  return Boolean(window.localStorage.getItem(REFRESH_TOKEN_KEY));
}

function readRefreshToken(): string | null {
  return window.localStorage.getItem(REFRESH_TOKEN_KEY);
}

function setAccessToken(token: string | null): void {
  accessToken = token;
}

function storeAuthTokens(payload: AuthPayload): AuthPayload {
  setAccessToken(payload.access_token);
  if (payload.refresh_token) {
    window.localStorage.setItem(REFRESH_TOKEN_KEY, payload.refresh_token);
  }
  return payload;
}

export function clearAuthTokens(): void {
  setAccessToken(null);
  window.localStorage.removeItem(REFRESH_TOKEN_KEY);
}

function notifyAuthExpired(): void {
  window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
}

http.interceptors.request.use((config) => {
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`;
  }
  return config;
});

type RetryableConfig = { _authRetry?: boolean; headers: Record<string, unknown> };

http.interceptors.response.use(
  (response) => response,
  async (error) => {
    const config = error.config as (typeof error.config & RetryableConfig) | undefined;
    const isAuthRequest = String(config?.url || "").startsWith("/auth/");
    const shouldRetry =
      error.response?.status === 401 &&
      config &&
      !config._authRetry &&
      !isAuthRequest &&
      readRefreshToken();
    if (!shouldRetry) {
      if (error.response?.status === 401 && !isAuthRequest) {
        clearAuthTokens();
        notifyAuthExpired();
      }
      return Promise.reject(error);
    }
    (config as RetryableConfig)._authRetry = true;
    try {
      const token = await refreshAccessToken();
      (config as RetryableConfig).headers.Authorization = `Bearer ${token}`;
      return http(config);
    } catch (refreshError) {
      clearAuthTokens();
      notifyAuthExpired();
      return Promise.reject(refreshError);
    }
  },
);

// ===========================================================================
// 类型（api 专用，不在 types/index.ts 里）
// ===========================================================================

export type AuthCredentials = { username: string; password: string };

export type SkillAlignmentCheck = {
  key: string;
  label: string;
  status: "pass" | "warn" | string;
  detail: string;
};

export type UserVideoFile = {
  file_name: string;
  name?: string;
  size?: number;
  modified_at?: string | null;
  download_url?: string;
  url?: string;
  [key: string]: unknown;
};

// 从 types 转出，供 `import { X } from lib/api` 的调用方使用
export type {
  AgentRun,
  XhsTrendInfo,
  AppNotification,
  CreationSkill,
  Draft,
  PlatformAccount,
  PublishJob,
  SavedNote,
  Tag,
  TaskRecord,
  ViralTemplate,
} from "../types";

// Agent 相关类型定义在后端 services/agent_service.py，不在 types/index.ts
export type AgentToolItem = {
  tool: string;
  label: string;
  description: string;
};

export type AgentCapabilityGroup = {
  key: string;
  label: string;
  description: string;
  examples: string[];
  primary: boolean;
  items: AgentToolItem[];
};

export type AgentCapabilities = {
  groups: AgentCapabilityGroup[];
  safety: string[];
  steps_limit: number;
};

export type AgentOverviewCounts = {
  accounts: number;
  notes: number;
  drafts: number;
  pending_drafts: number;
  pending_publishes: number;
  [key: string]: number;
};

export type AgentOverviewJob = {
  id: number;
  completed: number;
  failed: number;
  status: string;
  [key: string]: unknown;
};

export type AgentOverview = {
  counts: AgentOverviewCounts;
  recent_extract_jobs: AgentOverviewJob[];
  [key: string]: unknown;
};

export type AgentPlanStep = {
  tool: string;
  args: Record<string, unknown>;
  [key: string]: unknown;
};

// runAgent 的响应比 AgentRun 多包一层（run / job），供前端取嵌套字段
export type AgentRunResponse = import("../types").AgentRun & {
  run?: import("../types").AgentRun;
  job?: Record<string, unknown>;
};

export type StyleProfileSummary = {
  id: number;
  name: string;
  status: string;
  source: string;
  account_id: number | null;
  builtin_key: string | null;
  works_count: number;
  char_count: number;
  engine: string;
  created_at: string | null;
  updated_at: string | null;
  fallback_reason?: string;
  summary: {
    positioning?: string;
    tone?: string;
    audience?: string;
    hooks?: { label: string; count: number; examples?: string[] }[];
    avg_sentence_chars?: number;
    top_phrases?: { phrase: string; count: number }[];
    [key: string]: unknown;
  };
};

export type StyleProfileDetail = StyleProfileSummary & {
  skill_md: string;
  profile: Record<string, unknown>;
};

export type StyleConvertResult = {
  profile_id: number;
  job_id: number;
  account_id: number;
  created: number;
  failed: number;
  skipped: number;
  drafts: { draft_id: number; work_id: string; title: string; body_preview: string }[];
  failures: { work_id: string; error: string; skipped?: boolean }[];
  message: string;
};

export type SkillField = {
  key: string;
  label: string;
  value: string;
  status: "confirmed" | "assumed" | "missing";
  editable: boolean;
  required?: boolean;
  source?: string;
};

export type SkillGateStep = {
  index: number;
  title: string;
  criterion: string;
  checkable: boolean;
  status: "passed" | "failed" | "unverifiable";
  reason: string;
  result: string;
};

export type SkillGate = {
  steps: SkillGateStep[];
  passed: number;
  failed: number;
  unverifiable: number;
  completion: number;
  status: "passed" | "failed" | "partial";
};

export type SkillLibraryModule = {
  key?: string;
  module: string;
  label: string;
  count: number;
  enabled: number;
  total?: number;
  enabled_count?: number;
  feature?: string;
  description?: string;
  /** Whether this module's Skills are spliced into a generation prompt.
   *
   * False for persona/benchmark/schedule: their screens either have no model
   * call or produce a decision artifact when the Skill is run explicitly. The
   * library says which, so "auto-injected" is never implied where it is false.
   */
  auto_injected?: boolean;
};

export type SkillLibraryItem = {
  id: number;
  slug: string;
  name: string;
  description: string;
  module: string;
  module_label: string;
  triggers: string[];
  source: string;
  license: string;
  enabled: boolean;
  sort_order: number;
  content_chars: number;
  updated_at: string | null;
  account_enabled: boolean;
  priority: number;
  has_account_override: boolean;
  content_md?: string;
};

export type SkillLibraryTryResult = {
  text: string;
  artifact: string;
  fields: SkillField[];
  field_summary: { confirmed: number; assumed: number; missing: number };
  gate: SkillGate | null;
  open_questions: string[];
  skill: { slug: string; name: string; module: string; module_label: string };
  module: string;
  module_label: string;
  skills: string[];
  routed: boolean;
  step_count: number;
};

export type SkillRouteResult = {
  module: string;
  module_label?: string;
  items: {
    id?: number;
    slug: string;
    name: string;
    module: string;
    module_label?: string;
    score: number;
    reasons: string[];
    content_chars?: number;
  }[];
  total: number;
  candidate_count?: number;
  hint: string;
};

export type SkillEvolutionReport = {
  skill?: { id: number; name: string; version: string };
  report?: SkillEvolutionReport;
  scope?: string;
  sample_size?: number;
  baseline_engagement?: number;
  confidence?: string;
  format_distribution?: [string, number][];
  dimension_correlation?: Record<string, number | null>;
  weights_before?: Record<string, number>;
  weights_after?: Record<string, number>;
  weight_multipliers_before?: Record<string, number>;
  weight_multipliers_after?: Record<string, number>;
  changes?: string[];
  top_title_patterns?: [string, number][];
  top_cta_patterns?: [string, number][];
  note?: string;
  [key: string]: unknown;
};

export type TitleScoreResult = {
  score: number;
  grade: string;
  dimensions: { key: string; name: string; score: number; max: number; advice: string }[];
  suggestions: string[];
  skill_alignment?: SkillAlignmentCheck[];
};

export type NoteScoreResult = {
  score: number;
  grade: string;
  dimensions: { key: string; name: string; score: number; max: number; advice: string }[];
  suggestions: string[];
  skill_alignment?: SkillAlignmentCheck[];
};

export type ScoreDimension = {
  key: string;
  name: string;
  score: number;
  max: number;
  advice: string;
};

export type ScoreBlock = {
  applicable: boolean;
  total: number | null;
  grade: string;
  dimensions: ScoreDimension[];
  suggestions: string[];
  coverage: number;
  reason: string;
};

export type SkillScoreCraft = Omit<ScoreBlock, "total"> & { total: number };

export type SkillScoreResult = {
  draft_id?: number;
  note_id?: number;
  skill: { id: number; name: string; version: string; account_id: number | null } | null;
  format: string;
  format_label: string;
  fit: SkillScoreCraft;
  craft: SkillScoreCraft;
  total: number | null;
  grade: string;
  dimensions: ScoreDimension[];
  suggestions: string[];
  summary: string;
  skill_alignment: SkillAlignmentCheck[];
};

export type SimilarAccountItem = {
  user_id: string;
  nickname: string;
  fans: number;
  notes: number;
  likes: number;
  collects?: number;
  reason: string;
  avatar?: string;
  account_id?: string;
  fans_ratio?: number;
  avg_engagement?: number;
  [key: string]: unknown;
};

export type SimilarAccountsResult = {
  peer: SimilarAccountItem[];
  benchmark: SimilarAccountItem[];
  keyword?: string;
  note?: string;
  total?: number;
};

export type BatchRewriteResult = {
  created?: number;
  failed?: number;
  created_count?: number;
  failed_count?: number;
  items: {
    note_id: number;
    source_note_id?: number;
    status: string;
    draft_id?: number;
    draft?: { id: number; title: string } | null;
    note?: { id: number; title?: string; [key: string]: unknown } | null;
    preflight?: {
      summary?: string;
      errors?: { code?: string; label?: string; level?: string; message?: string }[];
      warnings?: { code?: string; label?: string; level?: string; message?: string }[];
      [key: string]: unknown;
    } | null;
    warnings?: string[];
    warning?: string;
    similarity?: number;
    error?: string;
  }[];
};

export type BatchScheduleResult = {
  scheduled?: number;
  failed?: number;
  created_count?: number;
  failed_count?: number;
  items: {
    draft_id: number;
    status: string;
    job_id?: number;
    job?: { id: number; status: string } | null;
    draft?: { id: number; title: string } | null;
    preflight?: {
      summary?: string;
      errors?: { code?: string; label?: string; level?: string; message?: string }[];
      warnings?: { code?: string; label?: string; level?: string; message?: string }[];
      [key: string]: unknown;
    } | null;
    warnings?: string[];
    scheduled_at?: string | null;
    error?: string;
  }[];
};

export type MatrixDraftResult = {
  created_count: number;
  failed_count: number;
  items: {
    account_id: number;
    account_name?: string;
    draft_id?: number;
    title?: string;
    body?: string;
    body_preview?: string;
    direction?: string;
    similarity?: number;
    warning?: string;
    error?: string;
    status?: string;
    preflight?: Record<string, unknown> | null;
  }[];
};

export type ReviewWritebackResult = {
  updated?: number;
  memories?: number;
  message?: string;
  note_count?: number;
  publish_success_rate?: number | null;
  refresh_rate?: number | null;
  next_actions?: string[];
  top_notes?: { title?: string; engagement?: number; likes?: number; [key: string]: unknown }[];
  /** Always false now: reviews are read-only. Kept so older shapes still type. */
  memory_written?: boolean;
  /** Explains that nothing was persisted, so the screen can say so. */
  memory_note?: string;
  memory_key?: string;
  persona_updated?: boolean;
  [key: string]: unknown;
};

export type LoopMetricsBucket = {
  key?: string;
  label?: string;
  count?: number;
  engagement?: number;
  [key: string]: unknown;
};

export type LoopMetrics = {
  period_days?: number;
  window_days?: number;
  publish_success_rate?: number | null;
  closed_loop_count?: number;
  drafts_created?: number;
  drafts_reviewed?: number;
  drafts_published?: number;
  notes_refreshed?: number;
  jobs_created?: number;
  jobs_published?: number;
  by_origin?: LoopMetricsBucket[];
  by_skill_version?: LoopMetricsBucket[];
  by_pillar?: LoopMetricsBucket[];
  by_experiment?: LoopMetricsBucket[];
  items?: {
    draft_id?: number;
    title?: string;
    published_at?: string | null;
    likes?: number;
    collects?: number;
    comments?: number;
    engagement?: number;
    [key: string]: unknown;
  }[];
  totals?: Record<string, number>;
  [key: string]: unknown;
};

export type PublishPreflight = {
  ok: boolean;
  errors: { code: string; label: string; level: string; message: string }[];
  warnings: { code: string; label: string; level: string; message: string }[];
  checks: { code: string; label: string; level: string; message: string }[];
  warning_count?: number;
  error_count?: number;
  summary?: string;
};

export type DraftAsset = {
  id: number;
  draft_id?: number;
  asset_type?: string;
  url?: string;
  local_path?: string;
  sort_order?: number;
  file_name?: string;
  download_url?: string;
  [key: string]: unknown;
};

export type DraftVersionRecord = {
  id: number;
  draft_id?: number;
  version_no?: number;
  title: string;
  body: string;
  tags: string[];
  created_at: string | null;
  origin?: string;
  [key: string]: unknown;
};

export type DraftChatResponse = {
  message?: string;
  reply?: string;
  changes?: string[];
  score?: SkillScoreResult | null;
  assistant_message_id?: number;
  patch?: {
    title?: string;
    body?: string;
    tags?: string[];
    [key: string]: unknown;
  } | null;
  version?: (DraftVersionRecord & { version_no?: number }) | null;
  draft?: Draft | null;
  [key: string]: unknown;
};

export type RiskControls = {
  auto_ops_enabled: boolean;
  competitor_rewrite_enabled: boolean;
  copy_source_images_enabled: boolean;
  auto_create_publish_job_enabled: boolean;
  auto_publish_enabled: boolean;
  auto_engagement_enabled: boolean;
  matrix_mode_enabled: boolean;
  batch_repost_enabled: boolean;
  updated_at: string;
  reserved_fields: string[];
  labels: Record<string, string>;
};

export type SystemSettings = Record<string, unknown>;

export type SavedTopic = {
  id: number;
  title: string;
  type: string;
  type_label: string;
  growth_task: string;
  need: string;
  why: string;
  source: string;
  status: string;
  scheduled_for: string | null;
  platform_account_id: number | null;
  created_at: string | null;
  updated_at: string | null;
};

export type XhsTopicRecommendation = {
  title: string;
  reason: string;
  source?: string;
  type?: string;
  type_label?: string;
  need?: string;
  growth_task?: string;
  why?: string;
  score?: number;
  hot_text?: string;
  matched_terms?: string[];
  [key: string]: unknown;
};

export type TopicBankItem = {
  title: string;
  type: string;
  type_label: string;
  growth_task: string;
  need: string;
  why: string;
  source: string;
};

export type TopicBankResult = {
  items: TopicBankItem[];
  total: number;
  count?: number;
  saved?: number;
  skill_text?: string;
  note?: string;
  topic_id?: number;
  topic_status?: string;
  growth_tasks?: { key?: string; label?: string; count?: number }[];
  [key: string]: unknown;
};

export type DouyinExtractMeta = {
  source_types?: string[];
  statuses?: string[];
  work_statuses?: string[];
  transcript_sources?: string[];
  ffmpeg_ready?: boolean;
  asr_ready?: boolean;
  engine?: string;
  model_size?: string;
  [key: string]: unknown;
};

export type DouyinExtractWork = {
  id: number;
  job_id: number;
  work_id: string;
  work_type: string;
  url: string;
  title: string;
  author_name: string;
  status: string;
  transcript_source: string;
  transcript_chars: number;
  duration_seconds: number | null;
  image_count: number;
  media_path: string;
  error: string | null;
  transcript?: string;
  srt?: string;
};

export type DouyinExtractJob = {
  id: number;
  source_type: string;
  account_name: string;
  status: string;
  stage: string;
  total: number;
  completed: number;
  failed: number;
  skipped: number;
  no_speech: number;
  limit_count: number;
  output_dir: string;
  error: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  running: boolean;
};

export type DouyinExtractJobDetail = DouyinExtractJob & {
  works: DouyinExtractWork[];
  source_preview: string;
  engine?: string;
  audit_text?: string;
  files?: { name: string; path: string; size?: number }[];
};

export type CreatorPublishedNote = {
  note_id: string;
  title: string;
  likes: number;
  collects: number;
  comments: number;
  shares: number;
  published_at: string | null;
  imported: boolean;
  note_url: string;
};

export type VisualBriefPrompt = {
  prompt?: string;
  negative_prompt?: string;
  ratio?: string;
  text_overlay?: string;
  [key: string]: unknown;
};

export type VisualBriefExpert = {
  key: string;
  label: string;
  purpose?: string;
  reason?: string;
};

export type VisualBrief = {
  draft_id: number;
  brief: string;
  style?: string;
  sequence?: string[];
  experts?: VisualBriefExpert[];
  requires_exact_title?: boolean;
  cover?: VisualBriefPrompt | null;
  illustration?: VisualBriefPrompt | null;
  pages?: (VisualBriefPrompt & { [key: string]: unknown })[];
  imagegen?: string;
  status?: string;
  router?: {
    boundaries?: string[];
    experts?: VisualBriefExpert[];
    [key: string]: unknown;
  };
  [key: string]: unknown;
};

export type BatchRewritePayload = { note_ids: number[]; account_id?: number | null };

// ===========================================================================
// Auth
// ===========================================================================

export async function login(credentials: AuthCredentials): Promise<AuthPayload> {
  const response = await http.post<AuthPayload>("/auth/login", credentials);
  return storeAuthTokens(response.data);
}

export async function register(credentials: AuthCredentials): Promise<AuthPayload> {
  const response = await http.post<AuthPayload>("/auth/register", credentials);
  return storeAuthTokens(response.data);
}

let refreshPromise: Promise<string> | null = null;

export function refreshAccessToken(): Promise<string> {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      const token = readRefreshToken();
      if (!token) {
        throw new Error("Missing refresh token");
      }
      const response = await http.post<{ access_token: string }>("/auth/refresh", {
        refresh_token: token,
      });
      setAccessToken(response.data.access_token);
      return response.data.access_token;
    })().finally(() => {
      // Allow a later 401 to retry after this attempt settles.
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

export async function fetchCurrentUser(): Promise<PlatformUser> {
  const response = await http.get<PlatformUser>("/auth/me");
  return response.data;
}

export async function bootstrapAuth(): Promise<PlatformUser | null> {
  if (!getAccessToken() && hasRefreshToken()) {
    await refreshAccessToken();
  }
  return getAccessToken() ? fetchCurrentUser() : null;
}

export async function logout(): Promise<void> {
  try {
    await http.post("/auth/logout");
  } finally {
    clearAuthTokens();
  }
}

// ===========================================================================
// Platforms / Accounts
// ===========================================================================

export async function fetchPlatforms(): Promise<PlatformMeta[]> {
  try {
    const response = await http.get<{ items: PlatformMeta[] }>("/platforms");
    return response.data.items;
  } catch {
    return [];
  }
}

export async function fetchAccounts(platform: PlatformId | string = "xhs"): Promise<PlatformAccount[]> {
  const items: PlatformAccount[] = [];
  for (let page = 1; page <= 20; page += 1) {
    const response = await http.get<Paginated<PlatformAccount>>("/accounts", {
      params: { platform, page, page_size: 100 },
    });
    items.push(...response.data.items);
    if (items.length >= (response.data.total ?? 0) || response.data.items.length === 0) {
      break;
    }
  }
  return items;
}

export async function importXhsCookieAccount(payload: Record<string, unknown>): Promise<PlatformAccount> {
  const response = await http.post<PlatformAccount>("/accounts/import-cookie", {
    platform: "xhs",
    ...payload,
  });
  return response.data;
}

export async function checkAccount(
  accountId: number,
  payload?: Record<string, unknown>,
): Promise<PlatformAccount> {
  const response = await http.post<PlatformAccount>(
    `/accounts/${accountId}/check`,
    payload ?? {},
  );
  return response.data;
}

export async function deleteAccount(accountId: number): Promise<{ deleted: boolean }> {
  const response = await http.delete<{ deleted: boolean }>(`/accounts/${accountId}`);
  return response.data;
}

export async function checkCreatorBridge(accountId: number): Promise<XhsCreatorBridgeResult> {
  const response = await http.post<XhsCreatorBridgeResult>(
    `/xhs/pc/accounts/${accountId}/creator-bridge`,
  );
  return response.data;
}

// ===========================================================================
// Notes
// ===========================================================================

export async function fetchSavedNoteIds(platform: PlatformId | string = "xhs"): Promise<number[]> {
  const response = await http.get<{ items: number[] }>("/notes/ids", { params: { platform } });
  return response.data.items;
}

export type SavedNotesQuery =
  | (PlatformId | string)
  | {
      platform?: PlatformId | string;
      q?: string;
      tag_id?: number;
      has_assets?: boolean;
      has_comments?: boolean;
      source?: string;
      max_fans?: number;
      min_likes?: number;
      min_like_fan_ratio?: number;
      sort_by?: string;
      page?: number;
      page_size?: number;
    };

export async function fetchSavedNotes(
  query: SavedNotesQuery | Record<string, unknown> = "xhs",
): Promise<Paginated<SavedNote>> {
  const params =
    typeof query === "string"
      ? { platform: query }
      : {
          platform: query.platform ?? "xhs",
          q: query.q || undefined,
          tag_id: query.tag_id,
          has_assets: query.has_assets,
          has_comments: query.has_comments,
          source: query.source,
          max_fans: query.max_fans,
          min_likes: query.min_likes,
          min_like_fan_ratio: query.min_like_fan_ratio,
          sort_by: query.sort_by,
          page: query.page,
          page_size: query.page_size,
        };
  const response = await http.get<Paginated<SavedNote>>("/notes", { params });
  return response.data;
}

export async function fetchSavedNote(noteId: number, silent = false): Promise<SavedNote> {
  const response = await http.get<SavedNote>(`/notes/${noteId}`, { _silent: silent } as never);
  return response.data;
}

export async function fetchSavedNoteAssets(noteId: number): Promise<{ items: NoteAsset[] }> {
  const response = await http.get<{ items: NoteAsset[] }>(`/notes/${noteId}/assets`);
  return response.data;
}

export async function addNoteAsset(
  noteId: number,
  payload: { asset_type: "image" | "video"; url: string },
): Promise<NoteAsset> {
  const response = await http.post<NoteAsset>(`/notes/${noteId}/assets`, {
    ...payload,
    local_path: "",
  });
  return response.data;
}

export async function deleteNoteAsset(
  noteId: number,
  assetId: number,
): Promise<{ deleted: boolean }> {
  const response = await http.delete<{ deleted: boolean }>(
    `/notes/${noteId}/assets/${assetId}`,
  );
  return response.data;
}

export async function reorderNoteAssets(
  noteId: number,
  assetIds: number[],
): Promise<{ ok: boolean }> {
  const response = await http.put<{ ok: boolean }>(
    `/notes/${noteId}/assets/reorder`,
    { asset_ids: assetIds },
  );
  return response.data;
}

export async function fetchSavedNoteComments(
  noteId: number,
  page = 1,
): Promise<{ items: NoteComment[]; total?: number }> {
  const response = await http.get<{ items: NoteComment[]; total?: number }>(
    `/notes/${noteId}/comments`,
    { params: { page, page_size: 50 } },
  );
  return response.data;
}

export async function deleteSavedNote(noteId: number): Promise<{ deleted: boolean }> {
  const response = await http.delete<{ deleted: boolean }>(`/notes/${noteId}`);
  return response.data;
}

export async function saveXhsNotesToLibrary(payload: {
  platform?: string;
  notes: Record<string, unknown>[];
  account_id?: number | null;
  [key: string]: unknown;
}): Promise<SaveNotesResponse> {
  const response = await http.post<SaveNotesResponse>("/notes/batch-save", payload);
  return response.data;
}

export async function batchCreateDraftsFromNotes(
  payload: BatchCreateDraftsPayload & { [key: string]: unknown },
): Promise<BatchCreateDraftsResponse> {
  const response = await http.post<BatchCreateDraftsResponse>("/notes/batch-create-drafts", payload);
  return response.data;
}

export async function batchRewriteNotes(
  payload: BatchRewritePayload & { instruction?: string; [key: string]: unknown },
): Promise<BatchRewriteResult> {
  const response = await http.post<BatchRewriteResult>("/notes/batch-rewrite-drafts", payload, {
    timeout: 300000,
  });
  return response.data;
}

export async function refreshNoteMetrics(
  noteIds: number[] = [],
  onlyOwn = false,
): Promise<Record<string, unknown>> {
  const response = await http.post<Record<string, unknown>>(
    "/notes/refresh-metrics",
    { note_ids: noteIds, only_own: onlyOwn, limit: Math.min(Math.max(noteIds.length || 10, 1), 10) },
    { timeout: 300000 },
  );
  return response.data;
}

export async function exportSavedNotes(payload: NotesExportPayload): Promise<NotesExportResponse> {
  const response = await http.post<NotesExportResponse>("/notes/export", payload);
  return response.data;
}

export async function batchTagNotes(payload: BatchTagNotesPayload): Promise<BatchTagNotesResponse> {
  const response = await http.post<BatchTagNotesResponse>("/notes/batch-tag", payload);
  return response.data;
}

// ===========================================================================
// Drafts
// ===========================================================================

export async function createDraft(payload: CreateDraftPayload): Promise<Draft> {
  const response = await http.post<Draft>("/drafts", payload);
  return response.data as Draft;
}

export async function fetchDrafts(
  platform: PlatformId | string = "xhs",
  query?: Record<string, unknown>,
): Promise<Paginated<Draft>> {
  const response = await http.get<Paginated<Draft>>("/drafts", {
    params: { platform, ...(query ?? {}) },
  });
  return response.data;
}

export async function fetchAllDrafts(platform: PlatformId | string = "xhs"): Promise<Draft[]> {
  const items: Draft[] = [];
  for (let page = 1; page <= 20; page += 1) {
    const response = await http.get<Paginated<Draft>>("/drafts", {
      params: { platform, page, page_size: 100 },
    });
    items.push(...response.data.items);
    if (items.length >= (response.data.total ?? 0) || response.data.items.length === 0) {
      break;
    }
  }
  return items;
}

export async function updateDraft(
  draftId: number,
  payload: Record<string, unknown> | string,
): Promise<Draft> {
  const body = typeof payload === "string" ? { title: payload } : payload;
  const response = await http.patch<Draft>(`/drafts/${draftId}`, body);
  return response.data;
}

export async function deleteDraft(draftId: number): Promise<{ deleted: boolean }> {
  const response = await http.delete<{ deleted: boolean }>(`/drafts/${draftId}`);
  return response.data;
}

export async function fetchDraftAssets(draftId: number): Promise<{ items: DraftAsset[] }> {
  const response = await http.get<{ items: DraftAsset[] }>(`/drafts/${draftId}/assets`);
  return response.data;
}

export async function addDraftAsset(
  draftId: number,
  payload: {
    asset_type?: string;
    url?: string;
    local_path?: string;
    file_name?: string;
    download_url?: string;
    [key: string]: unknown;
  },
): Promise<DraftAsset & { file_name?: string; download_url?: string }> {
  const response = await http.post<DraftAsset & { file_name?: string; download_url?: string }>(
    `/drafts/${draftId}/assets`,
    payload,
  );
  return response.data;
}

export async function deleteDraftAsset(
  draftId: number,
  assetId: number | string,
): Promise<{ deleted: boolean }> {
  const response = await http.delete<{ deleted: boolean }>(`/drafts/${draftId}/assets/${assetId}`);
  return response.data;
}

export async function updateDraftAsset(
  draftId: number,
  assetId: number | string,
  payload: Record<string, unknown>,
): Promise<DraftAsset> {
  const response = await http.patch<DraftAsset>(`/drafts/${draftId}/assets/${assetId}`, payload);
  return response.data;
}

export async function reorderDraftAssets(
  draftId: number,
  assetIds: number[],
): Promise<{ items: DraftAsset[] }> {
  const response = await http.put<{ items: DraftAsset[] }>(`/drafts/${draftId}/assets/reorder`, {
    asset_ids: assetIds,
  });
  return response.data;
}

export async function buildDraftVisualBrief(
  draftId: number,
  brief: string | Record<string, unknown> = "",
): Promise<VisualBrief & Record<string, unknown>> {
  const body = typeof brief === "string" ? { brief } : brief;
  const response = await http.post<VisualBrief & Record<string, unknown>>(
    `/drafts/${draftId}/visual-brief`,
    body,
  );
  return response.data;
}

export async function reviewDraft(
  draftId: number,
  payload: Record<string, unknown> | string,
): Promise<Draft> {
  const body = typeof payload === "string" ? { review_status: payload } : payload;
  const response = await http.patch<Draft>(`/drafts/${draftId}/review`, body);
  return response.data;
}

export async function sendDraftToPublish(
  draftId: number,
  payload: SendDraftToPublishPayload,
): Promise<PublishJob> {
  const response = await http.post<PublishJob>(`/drafts/${draftId}/send-to-publish`, payload);
  return response.data;
}

export async function batchSendDraftsToPublish(payload: {
  draft_ids: number[];
  platform_account_id: number;
  scheduled_at?: string | null;
  start_at?: string | null;
  [key: string]: unknown;
}): Promise<BatchScheduleResult> {
  const response = await http.post<BatchScheduleResult>("/drafts/batch-send-to-publish", payload);
  return response.data;
}

export async function fetchDraftPreflight(draftId: number, accountId?: number | null): Promise<PublishPreflight> {
  const response = await http.get<PublishPreflight>(`/drafts/${draftId}/preflight`, {
    params: accountId ? { account_id: accountId } : undefined,
  });
  return response.data;
}

export async function createDraftFromNote(payload: {
  platform?: string;
  source_note_id: number;
  intent?: string;
  account_id?: number | null;
  [key: string]: unknown;
}): Promise<Draft> {
  const response = await http.post<Draft>("/drafts", payload);
  return response.data as Draft;
}


// ===========================================================================
// AI
// ===========================================================================

export async function generateNoteWithAi(payload: GenerateNotePayload): Promise<Record<string, unknown>> {
  const response = await http.post<Record<string, unknown>>("/ai/generate-note", payload);
  return response.data;
}

export async function generateFromImages(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
  const response = await http.post<Record<string, unknown>>("/ai/generate-from-images", payload, {
    timeout: 240000,
  });
  return response.data;
}

export async function generateTitleOptions(payload: GenerateTitlePayload): Promise<{ items: string[] }> {
  const response = await http.post<{ items: string[] }>("/ai/generate-title", payload);
  return response.data;
}

export async function generateTagOptions(payload: GenerateTagsPayload): Promise<{ items: string[] }> {
  const response = await http.post<{ items: string[] }>("/ai/generate-tags", payload);
  return response.data;
}

export async function rewriteDraftWithAi(payload: RewriteDraftPayload): Promise<Record<string, unknown>> {
  const response = await http.post<Record<string, unknown>>("/ai/rewrite-note", payload);
  return response.data;
}

export async function draftChat(payload: {
  draft_id: number;
  message: string;
  account_id?: number | null;
  history?: unknown[];
  style_prompt?: string;
  [key: string]: unknown;
}): Promise<DraftChatResponse> {
  const response = await http.post<DraftChatResponse>("/ai/draft-chat", payload, { timeout: 120000 });
  return response.data;
}

export type DraftChatMessage = {
  id?: number;
  role: string;
  content: string;
  patch?: {
    title?: string;
    body?: string;
    tags?: string[];
    [key: string]: unknown;
  } | null;
  score?: SkillScoreResult | null;
  created_at?: string | null;
};

export async function fetchDraftChat(
  draftId: number,
): Promise<{ items: DraftChatMessage[]; total?: number }> {
  const response = await http.get<{ items: DraftChatMessage[]; total?: number }>(
    `/ai/draft-chat/${draftId}`,
    { timeout: 30000 },
  );
  return response.data;
}

export type ApplyDraftChatResult = {
  draft: Draft;
  version: DraftVersionRecord & { version_no: number };
};

export async function applyDraftChat(payload: {
  draft_id: number;
  message_id: number | null;
  patch?: Record<string, unknown> | null;
  history?: unknown[];
}): Promise<ApplyDraftChatResult> {
  const response = await http.post<ApplyDraftChatResult>("/ai/draft-chat/apply", payload, {
    timeout: 30000,
  });
  return response.data;
}

export async function fetchDraftVersions(draftId: number): Promise<{ items: DraftVersionRecord[] }> {
  const response = await http.get<{ items: DraftVersionRecord[] }>(`/ai/drafts/${draftId}/versions`, {
    timeout: 30000,
  });
  return response.data;
}

export async function restoreDraftVersion(
  draftId: number,
  versionId: number,
): Promise<Draft & { version_no?: number; version?: DraftVersionRecord }> {
  const response = await http.post<Draft & { version_no?: number; version?: DraftVersionRecord }>(
    `/ai/drafts/${draftId}/versions/${versionId}/restore`,
    {},
    { timeout: 30000 },
  );
  return response.data;
}

export async function generateImageWithAi(
  payload: GenerateImagePayload,
): Promise<GenerateImageResult & { model?: string; [key: string]: unknown }> {
  const response = await http.post<GenerateImageResult & { model?: string }>(
    "/ai/images/generate",
    payload,
    { timeout: 180000 },
  );
  return response.data;
}

export async function generateCardBackground(payload: GenerateCoverPayload): Promise<GenerateImageResult> {
  const response = await http.post<GenerateImageResult>("/ai/images/card-background", payload);
  return response.data;
}

export async function describeImageWithAi(
  payload: DescribeImagePayload,
): Promise<{ description: string; text?: string }> {
  const response = await http.post<{ description: string; text?: string }>(
    "/ai/images/describe",
    payload,
  );
  return response.data;
}

export async function fetchGeneratedImageAssets(): Promise<{ items: GeneratedImageAsset[] }> {
  const response = await http.get<{ items: GeneratedImageAsset[] }>("/ai/images/assets");
  return response.data;
}

export async function deleteGeneratedImageAsset(assetId: number): Promise<{ deleted: boolean }> {
  const response = await http.delete<{ deleted: boolean }>(`/ai/images/assets/${assetId}`);
  return response.data;
}

export async function registerImageAsset(payload: {
  file_name: string;
  prompt: string;
  [key: string]: unknown;
}): Promise<GeneratedImageAsset> {
  const response = await http.post<GeneratedImageAsset>("/ai/images/assets/register", payload);
  return response.data;
}

// ===========================================================================
// Agent
// ===========================================================================

export async function fetchAgentCapabilities(): Promise<AgentCapabilities> {
  const response = await http.get<AgentCapabilities>("/agent/capabilities");
  return response.data;
}

export async function fetchAgentOverview(): Promise<AgentOverview> {
  const response = await http.get<AgentOverview>("/agent/overview");
  return response.data;
}

export type AgentPlanResult = {
  summary?: string;
  steps?: AgentPlanStep[];
  [key: string]: unknown;
};

export async function planAgent(
  goal: string | Record<string, unknown>,
  accountId?: number | null,
  context?: Record<string, unknown>,
): Promise<AgentPlanResult> {
  const body = typeof goal === "string"
    ? { goal, account_id: accountId ?? null, context: context ?? {} }
    : goal;
  const response = await http.post<AgentPlanResult>("/agent/plan", body, {
    timeout: 180000,
  });
  return response.data;
}

export async function runAgent(
  goal: string | Record<string, unknown>,
  accountId?: number | null,
  options?: Record<string, unknown>,
): Promise<AgentRunResponse> {
  const body = typeof goal === "string"
    ? { goal, account_id: accountId ?? null, ...(options ?? {}) }
    : { ...goal, ...(options ?? {}) };
  const response = await http.post<AgentRun>("/agent/runs", body, { timeout: 240000 });
  return response.data;
}

export async function fetchAgentRuns(
  limit = 20,
): Promise<{ items: AgentRunResponse[]; total: number }> {
  const response = await http.get<{ items: AgentRunResponse[]; total: number }>("/agent/runs", {
    params: { limit },
  });
  return response.data;
}

export async function fetchAgentRun(runId: number): Promise<AgentRunResponse> {
  const response = await http.get<AgentRunResponse>(`/agent/runs/${runId}`);
  return response.data;
}

export async function cancelAgentRun(runId: number): Promise<AgentRunResponse> {
  const response = await http.post<AgentRunResponse>(`/agent/runs/${runId}/cancel`);
  return response.data;
}

export async function confirmAgentPublish(runId: number): Promise<{
  run: AgentRun;
  job: { id: number; status: string; [key: string]: unknown };
}> {
  const response = await http.post<{
    run: AgentRun;
    job: { id: number; status: string };
  }>(`/agent/runs/${runId}/confirm-publish`);
  return response.data as {
    run: AgentRun;
    job: { id: number; status: string; [key: string]: unknown };
  };
}

// ===========================================================================
// Auto tasks
// ===========================================================================

export async function fetchAutoTasks(): Promise<{ items: AutoTask[]; total: number }> {
  const response = await http.get<{ items: AutoTask[]; total: number }>("/auto-tasks");
  return response.data;
}

export async function createAutoTask(payload: AutoTaskCreatePayload): Promise<AutoTask> {
  const response = await http.post<AutoTask>("/auto-tasks", payload);
  return response.data;
}

export async function updateAutoTask(taskId: number, payload: AutoTaskUpdatePayload): Promise<AutoTask> {
  const response = await http.patch<AutoTask>(`/auto-tasks/${taskId}`, payload);
  return response.data;
}

export async function deleteAutoTask(taskId: number): Promise<{ deleted: boolean }> {
  const response = await http.delete<{ deleted: boolean }>(`/auto-tasks/${taskId}`);
  return response.data;
}

export async function runAutoTask(taskId: number): Promise<AutoTaskRunResult> {
  const response = await http.post<AutoTaskRunStart>(`/auto-tasks/${taskId}/run-async`);
  const start = response.data;

  // The request returns as soon as the tracking row is committed. Poll the
  // existing task endpoint so the long search/rewrite work never occupies a
  // request thread.
  const deadline = Date.now() + 10 * 60 * 1000;
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    const task = await fetchTask(start.task_id);
    if (task.status === "completed") {
      const result = task.payload?.result;
      if (!result) {
        throw new Error("后台任务已完成但没有返回结果");
      }
      return result as AutoTaskRunResult;
    }
    if (["failed", "cancelled", "exhausted"].includes(task.status)) {
      const detail = task.payload?.error;
      throw new Error(typeof detail === "string" && detail ? detail : "自动任务执行失败");
    }
  }
  throw new Error("自动任务执行超时，请到任务中心查看");
}

// ===========================================================================
// Douyin capture tokens (browser extension)
// ===========================================================================

export type CaptureToken = {
  id: number;
  name: string;
  token_prefix: string;
  created_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
  active: boolean;
  /** Only returned once, by createCaptureToken. */
  token?: string;
};

export async function fetchCaptureTokens(): Promise<{ items: CaptureToken[]; total: number }> {
  const response = await http.get<{ items: CaptureToken[]; total: number }>("/capture-tokens");
  return response.data;
}

export async function createCaptureToken(name = ""): Promise<CaptureToken> {
  const response = await http.post<CaptureToken>("/capture-tokens", { name });
  return response.data;
}

export async function revokeCaptureToken(tokenId: number): Promise<{ id: number; revoked: boolean }> {
  const response = await http.delete<{ id: number; revoked: boolean }>(`/capture-tokens/${tokenId}`);
  return response.data;
}

export type DouyinCaptureExtension = {
  exists: boolean;
  path: string;
  name: string;
  version: string;
};

export async function fetchDouyinCaptureExtension(): Promise<DouyinCaptureExtension> {
  const response = await http.get<DouyinCaptureExtension>("/douyin/capture/extension");
  return response.data;
}

export async function openDouyinCaptureExtension(): Promise<{ ok: boolean; path: string }> {
  const response = await http.post<{ ok: boolean; path: string }>("/douyin/capture/extension/open");
  return response.data;
}

// ===========================================================================
// Douyin extract
// ===========================================================================

export async function fetchDouyinExtractMeta(): Promise<DouyinExtractMeta> {
  const response = await http.get<DouyinExtractMeta>("/douyin/extract/meta");
  return response.data;
}

export async function createDouyinExtractJob(payload: Record<string, unknown>): Promise<DouyinExtractJob> {
  const response = await http.post<DouyinExtractJob>("/douyin/extract/jobs", payload);
  return response.data;
}

export async function fetchDouyinExtractJobs(
  page = 1,
  pageSize = 50,
): Promise<{ items: DouyinExtractJob[]; total: number }> {
  const response = await http.get<{ items: DouyinExtractJob[]; total: number }>(
    "/douyin/extract/jobs",
    { params: { page, page_size: pageSize } },
  );
  return response.data;
}

export async function fetchDouyinExtractJob(jobId: number): Promise<DouyinExtractJobDetail> {
  const response = await http.get<DouyinExtractJobDetail>(`/douyin/extract/jobs/${jobId}`);
  return response.data;
}

export async function runDouyinExtractJob(jobId: number, retryFailed = false): Promise<DouyinExtractJobDetail> {
  const response = await http.post<DouyinExtractJobDetail>(
    `/douyin/extract/jobs/${jobId}/run`,
    {},
    { params: { retry_failed: retryFailed } },
  );
  return response.data;
}

export async function pauseDouyinExtractJob(jobId: number): Promise<DouyinExtractJob> {
  const response = await http.post<DouyinExtractJob>(`/douyin/extract/jobs/${jobId}/pause`);
  return response.data;
}

export async function openDouyinExtractFolder(jobId: number): Promise<{ ok: boolean; path: string }> {
  const response = await http.post<{ ok: boolean; path: string }>(
    `/douyin/extract/jobs/${jobId}/open-folder`,
  );
  return response.data;
}

export interface DouyinCorpusImportResult {
  set_id: number;
  set_name: string;
  genre: string;
  role: string;
  imported: number;
  new_notes: number;
  new_members: number;
  missing: string[];
  author: string;
}

export async function importDouyinJobCorpus(
  jobId: number,
  payload: { name?: string; genre?: string; role?: string },
): Promise<DouyinCorpusImportResult> {
  const response = await http.post<DouyinCorpusImportResult>(
    `/douyin/extract/jobs/${jobId}/corpus`,
    payload,
  );
  return response.data;
}

export async function downloadDouyinExtractFile(jobId: number, path: string): Promise<Blob> {
  const response = await http.get(`/douyin/extract/jobs/${jobId}/file`, {
    params: { path },
    responseType: "blob",
  });
  return response.data;
}

// ===========================================================================
// Tags / Files
// ===========================================================================

export async function fetchTags(): Promise<{ items: Tag[] }> {
  const response = await http.get<{ items: Tag[] }>("/tags");
  return response.data;
}

export async function createTag(payload: TagPayload): Promise<Tag> {
  const response = await http.post<Tag>("/tags", payload);
  return response.data;
}

export async function updateTag(
  tagId: number,
  payload: Partial<TagPayload>,
): Promise<Tag> {
  const response = await http.patch<Tag>(`/tags/${tagId}`, payload);
  return response.data;
}

export async function deleteTag(tagId: number): Promise<{ id: number; status: string }> {
  const response = await http.delete<{ id: number; status: string }>(`/tags/${tagId}`);
  return response.data;
}

export async function uploadAssetFile(
  file: File,
): Promise<{
  file_name: string;
  download_url: string;
  asset_type?: string;
  url?: string;
  size?: number;
}> {
  const form = new FormData();
  form.append("file", file);
  const response = await http.post<{
    file_name: string;
    download_url: string;
    asset_type?: string;
    url?: string;
  }>("/files/upload", form, { timeout: 120000 });
  return response.data;
}

export async function fetchUserImages(): Promise<{ items: UserImageFile[] }> {
  const response = await http.get<{ items: UserImageFile[] }>("/files/images");
  return response.data;
}

export async function deleteUserImage(fileName: string): Promise<{ deleted: boolean }> {
  const response = await http.delete<{ deleted: boolean }>(`/files/images/${fileName}`);
  return response.data;
}

export async function fetchUserVideos(): Promise<{ items: UserVideoFile[] }> {
  const response = await http.get<{ items: UserVideoFile[] }>("/files/videos");
  return response.data;
}

export async function deleteUserVideo(fileName: string): Promise<{ deleted: boolean }> {
  const response = await http.delete<{ deleted: boolean }>(`/files/videos/${fileName}`);
  return response.data;
}

export async function composeImage(payload: ComposeImagePayload): Promise<ImageUtilityFile> {
  const response = await http.post<ImageUtilityFile>("/files/images/compose", payload);
  return response.data;
}

export async function resizeImage(payload: ResizeImagePayload): Promise<ImageUtilityFile> {
  const response = await http.post<ImageUtilityFile>("/files/images/resize", payload);
  return response.data;
}

export async function downloadExportFile(downloadUrl: string, fileName: string): Promise<void> {
  const path = downloadUrl.startsWith("/api") ? downloadUrl.slice(4) : downloadUrl;
  const response = await http.get(path, { responseType: "blob" });
  const url = window.URL.createObjectURL(response.data);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  window.URL.revokeObjectURL(url);
}

// ===========================================================================
// Tasks
// ===========================================================================

export async function fetchTasks(
  platform: PlatformId | string = "xhs",
  taskType?: string,
): Promise<Paginated<TaskRecord>> {
  const response = await http.get<Paginated<TaskRecord>>("/tasks", {
    params: { platform, task_type: taskType },
  });
  return response.data;
}

export async function fetchTask(taskId: number): Promise<TaskRecord> {
  const response = await http.get<TaskRecord>(`/tasks/${taskId}`);
  return response.data;
}

export async function fetchSchedulerStatus(): Promise<SchedulerStatus> {
  const response = await http.get<SchedulerStatus>("/tasks/scheduler/status");
  return response.data;
}

export async function cancelTask(taskId: number): Promise<TaskRecord> {
  const response = await http.post<TaskRecord>(`/tasks/${taskId}/cancel`);
  return response.data;
}

export async function retryTask(taskId: number): Promise<TaskRecord> {
  const response = await http.post<TaskRecord>(`/tasks/${taskId}/retry`);
  return response.data;
}

export async function runDueTasks(platform: PlatformId | string = "xhs"): Promise<RunDueTasksResponse> {
  const response = await http.post<RunDueTasksResponse>("/tasks/run-due", { platform });
  return response.data;
}

// ===========================================================================
// Publish
// ===========================================================================

export async function fetchPublishJobs(
  platform: PlatformId | string = "xhs",
  query?: Record<string, unknown>,
): Promise<Paginated<PublishJob>> {
  const response = await http.get<Paginated<PublishJob>>("/publish/jobs", {
    params: { platform, ...(query ?? {}) },
  });
  return response.data;
}

export async function fetchAllPublishJobs(
  platform: PlatformId | string = "xhs",
): Promise<PublishJob[]> {
  const items: PublishJob[] = [];
  for (let page = 1; page <= 20; page += 1) {
    const response = await http.get<Paginated<PublishJob>>("/publish/jobs", {
      params: { platform, page, page_size: 100 },
    });
    items.push(...response.data.items);
    if (items.length >= (response.data.total ?? 0) || response.data.items.length === 0) {
      break;
    }
  }
  return items;
}

export async function fetchPublishJob(jobId: number): Promise<PublishJob> {
  const response = await http.get<PublishJob>(`/publish/jobs/${jobId}`);
  return response.data;
}

export async function fetchPublishPreflight(jobId: number): Promise<PublishPreflight> {
  const response = await http.get<PublishPreflight>(`/publish/jobs/${jobId}/preflight`);
  return response.data;
}

export async function updatePublishJob(
  jobId: number,
  payload: PublishJobUpdatePayload,
): Promise<PublishJob> {
  const response = await http.patch<PublishJob>(`/publish/jobs/${jobId}`, payload);
  return response.data;
}

export async function publishJobToCreator(jobId: number): Promise<PublishJob> {
  const response = await http.post<PublishJob>(`/publish/jobs/${jobId}/publish`, {}, {
    timeout: 900000,
  });
  return response.data;
}

export async function retryPublishJob(jobId: number): Promise<PublishJob> {
  const response = await http.post<PublishJob>(`/publish/jobs/${jobId}/retry`, {}, {
    timeout: 900000,
  });
  return response.data;
}

export async function cancelPublishJob(jobId: number): Promise<PublishJob> {
  const response = await http.post<PublishJob>(`/publish/jobs/${jobId}/cancel`);
  return response.data;
}

export async function deletePublishJob(jobId: number): Promise<{ deleted: boolean }> {
  const response = await http.delete<{ deleted: boolean }>(`/publish/jobs/${jobId}`);
  return response.data;
}

export async function fetchPublishAssets(jobId: number): Promise<{ items: PublishAsset[] }> {
  const response = await http.get<{ items: PublishAsset[] }>(`/publish/jobs/${jobId}/assets`);
  return response.data;
}

export async function addPublishAsset(
  jobId: number,
  payload: { asset_type: "image" | "video"; file_path: string },
): Promise<PublishAsset> {
  const response = await http.post<PublishAsset>(`/publish/jobs/${jobId}/assets`, payload);
  return response.data;
}

export async function deletePublishAsset(assetId: number): Promise<{ id: number; status: string }> {
  const response = await http.delete<{ id: number; status: string }>(`/publish/assets/${assetId}`);
  return response.data;
}

export async function uploadPublishAsset(assetId: number): Promise<PublishAsset> {
  // Creator 媒体上传是分片逐张进行的，和发布本身一样可能超过默认超时。
  const response = await http.post<PublishAsset>(`/publish/assets/${assetId}/upload`, {}, {
    timeout: 300000,
  });
  return response.data;
}

// ===========================================================================
// Monitoring / Notifications
// ===========================================================================

export async function fetchMonitoringTargets(): Promise<{ items: MonitoringTarget[]; total: number }> {
  const response = await http.get<{ items: MonitoringTarget[]; total: number }>(
    "/xhs/monitoring/targets",
  );
  return response.data;
}

export async function createMonitoringTarget(
  payload: MonitoringTargetPayload,
): Promise<MonitoringTarget> {
  const response = await http.post<MonitoringTarget>("/xhs/monitoring/targets", payload);
  return response.data;
}

export async function updateMonitoringTarget(
  targetId: number,
  payload: {
    name?: string;
    value?: string;
    status?: "active" | "paused";
    config?: Record<string, unknown>;
  },
): Promise<MonitoringTarget> {
  const response = await http.patch<MonitoringTarget>(
    `/xhs/monitoring/targets/${targetId}`,
    payload,
  );
  return response.data;
}

export async function deleteMonitoringTarget(targetId: number): Promise<{ deleted: boolean }> {
  const response = await http.delete<{ deleted: boolean }>(`/xhs/monitoring/targets/${targetId}`);
  return response.data;
}

export async function refreshMonitoringTarget(targetId: number): Promise<MonitoringRefreshResponse> {
  const response = await http.post<MonitoringRefreshResponse>(
    `/xhs/monitoring/targets/${targetId}/refresh`,
  );
  return response.data;
}

export async function fetchMonitoringSnapshots(
  targetId: number,
): Promise<{ items: MonitoringSnapshot[] }> {
  const response = await http.get<{ items: MonitoringSnapshot[] }>(
    `/xhs/monitoring/targets/${targetId}/snapshots`,
  );
  return response.data;
}

export async function fetchNotifications(params?: {
  page?: number;
  page_size?: number;
}): Promise<{ items: import("../types").AppNotification[]; total: number }> {
  const response = await http.get<{
    items: import("../types").AppNotification[];
    total: number;
  }>("/notifications", { params });
  return response.data;
}

export async function markNotificationRead(notificationId: number): Promise<{ ok: boolean }> {
  const response = await http.post<{ ok: boolean }>(`/notifications/${notificationId}/read`);
  return response.data;
}

export async function markAllNotificationsRead(): Promise<{ ok: boolean }> {
  const response = await http.post<{ ok: boolean }>("/notifications/read-all");
  return response.data;
}

// ===========================================================================
// Model configs / Keyword groups / Settings
// ===========================================================================

export async function fetchModelConfigs(
  modelType?: string,
): Promise<{ items: ModelConfig[]; total: number }> {
  const response = await http.get<{ items: ModelConfig[]; total: number }>("/model-configs", {
    params: modelType ? { model_type: modelType } : undefined,
  });
  return response.data;
}

export async function createModelConfig(payload: ModelConfigPayload): Promise<ModelConfig> {
  const response = await http.post<ModelConfig>("/model-configs", payload);
  return response.data;
}

export async function updateModelConfig(
  configId: number,
  payload: Partial<ModelConfigPayload>,
): Promise<ModelConfig> {
  const response = await http.patch<ModelConfig>(`/model-configs/${configId}`, payload);
  return response.data;
}

export async function setDefaultModelConfig(configId: number): Promise<ModelConfig> {
  const response = await http.post<ModelConfig>(`/model-configs/${configId}/set-default`);
  return response.data;
}

export async function testModelConfig(
  configId: number,
): Promise<{ ok: boolean; message: string; status: string; [key: string]: unknown }> {
  const response = await http.post<{
    ok: boolean;
    message: string;
    status: string;
  }>(`/model-configs/${configId}/test`);
  return response.data as { ok: boolean; message: string; status: string };
}

export async function deleteModelConfig(configId: number): Promise<{ deleted: boolean }> {
  const response = await http.delete<{ deleted: boolean }>(`/model-configs/${configId}`);
  return response.data;
}

export async function fetchKeywordGroups(
  params?: Record<string, unknown> | string,
): Promise<{ items: KeywordGroup[]; total: number }> {
  const query = typeof params === "string" ? { platform: params } : params;
  const response = await http.get<{ items: KeywordGroup[]; total: number }>("/keyword-groups", {
    params: query,
  });
  return response.data;
}

export async function createKeywordGroup(payload: KeywordGroupPayload): Promise<KeywordGroup> {
  const response = await http.post<KeywordGroup>("/keyword-groups", payload);
  return response.data;
}

export async function fetchKeywordGroup(groupId: number): Promise<KeywordGroupDetail> {
  const response = await http.get<KeywordGroupDetail>(`/keyword-groups/${groupId}`);
  return response.data;
}

export async function updateKeywordGroup(
  groupId: number,
  payload: Partial<KeywordGroupPayload>,
): Promise<KeywordGroup> {
  const response = await http.patch<KeywordGroup>(`/keyword-groups/${groupId}`, payload);
  return response.data;
}

export async function deleteKeywordGroup(groupId: number): Promise<{ deleted: boolean }> {
  const response = await http.delete<{ deleted: boolean }>(`/keyword-groups/${groupId}`);
  return response.data;
}

export async function fetchRiskControls(): Promise<RiskControls> {
  const response = await http.get<RiskControls>("/settings/risk-controls");
  return response.data;
}

export async function updateRiskControls(payload: Partial<RiskControls> & { acknowledge_risk?: boolean }): Promise<RiskControls> {
  const response = await http.put<RiskControls>("/settings/risk-controls", payload);
  return response.data;
}

export async function fetchSystemSettings(params?: Record<string, unknown>): Promise<SystemSettings> {
  const response = await http.get<SystemSettings>("/system/settings", { params });
  return response.data;
}

export async function saveSystemSettings(payload: SystemSettings): Promise<SystemSettings> {
  const response = await http.put<SystemSettings>("/system/settings", payload);
  return response.data;
}

export type SystemDiagnostics = {
  window_days: number;
  since: string;
  summary: {
    api_errors: number;
    failed_tasks: number;
    account_issues: number;
    template_issues: number;
  };
  api_errors: Array<{
    id: number;
    endpoint: string;
    status: string;
    method: string | null;
    status_code: number | null;
    created_at: string;
  }>;
  failed_tasks: Array<{
    id: number;
    task_type: string;
    error_type: string | null;
    created_at: string;
    finished_at: string | null;
  }>;
  account_issues: Array<{
    id: number;
    nickname: string;
    sub_type: string;
    status: string;
  }>;
  template_issues: Array<{
    auto_task_id: number;
    name: string;
    template_id: number;
    reason: string;
  }>;
};

export async function fetchSystemDiagnostics(days = 7): Promise<SystemDiagnostics> {
  const response = await http.get<SystemDiagnostics>("/system/diagnostics", {
    params: { days },
  });
  return response.data;
}


// ===========================================================================
// XHS · Analytics
// ===========================================================================

export type AnalyticsSource = "all" | "own" | "library";

export async function fetchXhsOverview(filters?: {
  account_id?: number;
  note_id?: string;
}): Promise<DashboardOverview> {
  const response = await http.get<DashboardOverview>("/xhs/analytics/overview", { params: filters });
  return response.data;
}

export async function fetchXhsTopContent(
  source: AnalyticsSource = "all",
  filters?: { account_id?: number; note_id?: string },
): Promise<{ items: AnalyticsTopContent[] }> {
  const response = await http.get<{ items: AnalyticsTopContent[] }>("/xhs/analytics/top-content", {
    params: { source, ...(filters ?? {}) },
  });
  return response.data;
}

export async function fetchXhsHotTopics(
  source: AnalyticsSource = "all",
  filters?: { account_id?: number; note_id?: string },
): Promise<{ items: AnalyticsHotTopic[] }> {
  const response = await http.get<{ items: AnalyticsHotTopic[] }>("/xhs/analytics/hot-topics", {
    params: { source, ...(filters ?? {}) },
  });
  return response.data;
}

export async function fetchXhsCommentInsights(
  source: AnalyticsSource = "all",
  filters?: { account_id?: number; note_id?: string },
): Promise<AnalyticsCommentInsight> {
  const response = await http.get<AnalyticsCommentInsight>("/xhs/analytics/comment-insights", {
    params: { source, ...(filters ?? {}) },
  });
  return response.data;
}

export async function reviewXhsAnalytics(payload: Record<string, unknown>): Promise<ReviewWritebackResult> {
  const response = await http.post<ReviewWritebackResult>("/xhs/analytics/review", payload, {
    timeout: 120000,
  });
  return response.data;
}
export async function createXhsAnalyticsReport(
  payload: { format?: string } = { format: "json" },
): Promise<AnalyticsReportResponse> {
  const response = await http.post<AnalyticsReportResponse>("/xhs/analytics/reports", payload);
  return response.data;
}

export async function backfillAnalytics(): Promise<Record<string, unknown>> {
  const response = await http.post<Record<string, unknown>>("/xhs/analytics/backfill");
  return response.data;
}

export async function fetchNoteDiagnosis(
  noteId: string | number,
): Promise<NoteDiagnosis & Record<string, unknown>> {
  const response = await http.get<NoteDiagnosis & Record<string, unknown>>(
    `/xhs/analytics/diagnosis/note/${noteId}`,
  );
  return response.data;
}

export async function fetchXhsEngagement(source: AnalyticsSource = "all"): Promise<{
  items: { date: string; likes: number; collects: number; comments: number; shares: number; engagement: number }[];
}> {
  const response = await http.get("/xhs/analytics/engagement", { params: { source } });
  return response.data;
}

// ===========================================================================
// XHS · Insights
// ===========================================================================

export async function analyzeViralNote(payload: {
  note_db_id?: number;
  note_id?: number | string;
  save?: boolean;
  fetch_comments?: boolean;
  account_id?: number | null;
  [key: string]: unknown;
}): Promise<ViralAnalysisResponse> {
  const response = await http.post<ViralAnalysisResponse>("/xhs/insights/viral-analysis", payload);
  return response.data;
}

export async function createViralTemplate(
  payload: Record<string, unknown>,
): Promise<ViralTemplate> {
  const response = await http.post<ViralTemplate>("/xhs/insights/viral-templates", payload);
  return response.data;
}

export async function generateStructureTemplate(payload: {
  set_id: number;
  name?: string;
  genre?: string;
}): Promise<ViralTemplate> {
  const response = await http.post<ViralTemplate>(
    "/xhs/insights/viral-templates/from-corpus",
    payload,
  );
  return response.data;
}

export type StructureCheckPosition = {
  position: "opening" | "body" | "closing";
  detected: string;
  expected: string;
  alternatives: string[];
  strict_match: boolean;
  soft_match: boolean;
  confidence: number;
};

export type StructureCheckMiddleElement = {
  label: string;
  pct: number | null;
  present: boolean;
};

export type StructureCheckResult = {
  template_id: number;
  template_name: string;
  draft_id: number | null;
  coverage: number;
  soft_coverage: number;
  matched: number;
  soft_matched: number;
  total: number;
  positions: StructureCheckPosition[];
  actual_skeleton: string;
  expected_skeletons: string[];
  skeleton_match: boolean;
  middle_elements: StructureCheckMiddleElement[];
  middle_element_coverage: number | null;
};

export async function checkStructure(payload: {
  template_id: number;
  draft_id?: number;
  title?: string;
  body?: string;
}): Promise<StructureCheckResult> {
  const response = await http.post<StructureCheckResult>("/xhs/insights/structure-check", payload);
  return response.data;
}

export async function fetchViralTemplates(): Promise<
  ViralTemplateListResponse & { items: ViralTemplate[]; total: number }
> {
  const response = await http.get<
    ViralTemplateListResponse & { items: ViralTemplate[]; total: number }
  >("/xhs/insights/viral-templates");
  return response.data;
}

export async function setViralTemplateActive(
  templateId: number,
  isActive: boolean,
): Promise<ViralTemplate> {
  const response = await http.patch<ViralTemplate>(
    `/xhs/insights/viral-templates/${templateId}`,
    { is_active: isActive },
  );
  return response.data;
}

export async function deleteViralTemplate(templateId: number): Promise<{ deleted: boolean }> {
  const response = await http.delete<{ deleted: boolean }>(
    `/xhs/insights/viral-templates/${templateId}`,
  );
  return response.data;
}

export async function refineViralTemplate(
  templateId: number,
  payload?: Record<string, unknown>,
): Promise<ViralTemplate> {
  const response = await http.post<ViralTemplate>(
    `/xhs/insights/viral-templates/${templateId}/refine`,
    payload ?? {},
    { timeout: 180000 },
  );
  return response.data;
}

export async function scoreXhsTitle(payload: { title: string; body?: string }): Promise<TitleScoreResult> {
  const response = await http.post<TitleScoreResult>("/xhs/insights/title-score", payload);
  return response.data;
}

export async function scoreXhsNote(payload: {
  title: string;
  body: string;
  tags?: string[];
}): Promise<NoteScoreResult> {
  const response = await http.post<NoteScoreResult>("/xhs/insights/note-score", payload);
  return response.data;
}

export async function scoreDraftWithSkill(
  payload: number | Record<string, unknown>,
): Promise<SkillScoreResult> {
  const body = typeof payload === "number" ? { draft_id: payload } : payload;
  const response = await http.post<SkillScoreResult>("/xhs/insights/draft-skill-score", body);
  return response.data;
}

export async function scoreNoteWithSkill(
  payload: number | Record<string, unknown>,
  accountId?: number | null,
): Promise<SkillScoreResult> {
  const body = typeof payload === "number" ? { note_id: payload } : payload;
  const response = await http.post<SkillScoreResult>("/xhs/insights/note-skill-score", body, {
    params: accountId ? { account_id: accountId } : undefined,
  });
  return response.data;
}

export async function findSimilarAccounts(payload: {
  keyword?: string;
  account_id?: number | null;
  seed_fans?: number;
  [key: string]: unknown;
}): Promise<SimilarAccountsResult> {
  const response = await http.post<SimilarAccountsResult>("/xhs/insights/similar-accounts", payload, {
    timeout: 180000,
  });
  return response.data;
}

export async function distillAuthorStyle(payload: {
  author_id: string;
  author_name: string;
  keyword?: string;
  [key: string]: unknown;
}): Promise<
  StyleProfileDetail & { collected_notes?: number; skipped_notes?: number }
> {
  const response = await http.post<StyleProfileDetail>("/xhs/insights/author-style", payload, {
    timeout: 300000,
  });
  return response.data;
}

export async function generateAccountReport(payload: {
  account_id: number;
  users: string[];
  month?: string | null;
  max_pages?: number;
}): Promise<AccountReportResponse> {
  const response = await http.post<AccountReportResponse>("/xhs/insights/account-report", payload);
  return response.data;
}

export async function fetchLoopMetrics(
  days = 7,
  accountId?: number | null | { account_id: number },
): Promise<LoopMetrics> {
  const accountParam =
    typeof accountId === "object" && accountId !== null ? accountId.account_id : accountId;
  const response = await http.get<LoopMetrics>("/xhs/insights/loop-metrics", {
    params: { days, account_id: accountParam ?? undefined },
  });
  return response.data;
}

// ===========================================================================
// XHS · Creation skills
// ===========================================================================

export async function fetchCreationSkills(accountId?: number | null): Promise<{
  items: CreationSkill[];
  total: number;
}> {
  const response = await http.get<{ items: CreationSkill[]; total: number }>("/xhs/creation-skills", {
    params: accountId ? { account_id: accountId } : undefined,
  });
  return response.data;
}

export async function fetchCurrentCreationSkill(accountId?: number | null): Promise<{ skill: CreationSkill | null }> {
  const response = await http.get<{ skill: CreationSkill | null }>("/xhs/creation-skills/current", {
    params: accountId ? { account_id: accountId } : undefined,
  });
  return response.data;
}

export async function createCreationSkill(payload: {
  account_id: number;
  name: string;
  version: string;
  content_md: string;
  source?: string;
  [key: string]: unknown;
}): Promise<CreationSkill> {
  const response = await http.post<CreationSkill>("/xhs/creation-skills", payload);
  return response.data;
}

export async function updateCreationSkill(
  skillId: number,
  payload: Record<string, unknown>,
): Promise<CreationSkill> {
  const response = await http.put<CreationSkill>(`/xhs/creation-skills/${skillId}`, payload);
  return response.data;
}

export async function activateCreationSkill(skillId: number): Promise<CreationSkill> {
  const response = await http.post<CreationSkill>(`/xhs/creation-skills/${skillId}/activate`);
  return response.data;
}

export async function evolveCreationSkill(
  skillId: number,
  accountId?: number | null,
): Promise<SkillEvolutionReport> {
  const response = await http.post<SkillEvolutionReport>(
    `/xhs/creation-skills/${skillId}/evolve`,
    null,
    { params: accountId ? { account_id: accountId } : undefined, timeout: 180000 },
  );
  return response.data;
}

// ===========================================================================
// XHS · Skill library
// ===========================================================================

export async function fetchSkillLibrary(
  accountId?: number | null,
  _legacyAccountId?: number | null,
): Promise<{
  items: SkillLibraryItem[];
  total: number;
  modules: SkillLibraryModule[];
  account_id: number | null;
}> {
  const effective = accountId ?? _legacyAccountId ?? null;
  const response = await http.get<{
    items: SkillLibraryItem[];
    total: number;
    modules: SkillLibraryModule[];
    account_id: number | null;
  }>("/xhs/skill-library", { params: effective ? { account_id: effective } : {} });
  return response.data;
}

export async function importSkillPack(file: File): Promise<{
  imported?: number;
  created?: number;
  updated?: number;
  items: SkillLibraryItem[];
}> {
  const form = new FormData();
  form.append("file", file);
  const response = await http.post<{
    imported?: number;
    created?: number;
    updated?: number;
    items: SkillLibraryItem[];
  }>("/xhs/skill-library/import", form, { timeout: 120000 });
  return response.data;
}

export async function fetchSkillLibraryItem(itemId: number): Promise<SkillLibraryItem> {
  const response = await http.get<SkillLibraryItem>(`/xhs/skill-library/${itemId}`);
  return response.data;
}

export async function updateSkillLibraryItem(
  itemId: number,
  enabled: boolean | Record<string, unknown>,
): Promise<SkillLibraryItem> {
  const body = typeof enabled === "boolean" ? { enabled } : enabled;
  const response = await http.patch<SkillLibraryItem>(`/xhs/skill-library/${itemId}`, body);
  return response.data;
}

export async function updateAccountSkill(
  itemId: number,
  payload: { account_id: number; enabled?: boolean; priority?: number },
): Promise<Record<string, unknown>> {
  const response = await http.patch<Record<string, unknown>>(
    `/xhs/skill-library/${itemId}/account`,
    payload,
  );
  return response.data;
}

export async function trySkillLibrary(payload: {
  module: string;
  task: string;
  context?: string;
  account_id?: number | null;
  slug?: string;
}): Promise<SkillLibraryTryResult> {
  const response = await http.post<SkillLibraryTryResult>("/xhs/skill-library/try", payload, {
    timeout: 180000,
  });
  return response.data;
}

export async function routeSkillLibrary(payload: {
  task: string;
  module?: string;
  limit?: number;
  account_id?: number | null;
}): Promise<SkillRouteResult> {
  const response = await http.post<SkillRouteResult>("/xhs/skill-library/route", payload);
  return response.data;
}

// ===========================================================================
// XHS · Corpus（对标集）
// ===========================================================================

export type CorpusKind = "account" | "topic" | "baseline";

export type CorpusSet = {
  id: number;
  name: string;
  kind: CorpusKind;
  keyword: string;
  source_accounts: string[];
  status: string;
  note: string;
  total: number;
  collect: Record<string, number>;
  genres: Record<string, number>;
  roles: Record<string, number>;
  updated_at: string | null;
};

export type CorpusMember = {
  id: number;
  note_id: string;
  note_db_id: number | null;
  collect_status: string;
  collect_error: string;
  genre: string;
  genre_label: string;
  role: string;
  role_reason: string;
  published_at: string;
  title: string;
  author_name: string;
  likes: number;
  collects: number;
  engagement: number;
};

export type CorpusMeta = {
  kinds: string[];
  genres: { value: string; label: string }[];
  collect_statuses: string[];
  roles: string[];
  limits: { max_source_accounts: number; max_pages: number };
};

export async function fetchCorpusMeta(): Promise<CorpusMeta> {
  const response = await http.get<CorpusMeta>("/xhs/corpus/meta");
  return response.data;
}

export async function fetchCorpusSets(kind?: CorpusKind): Promise<{ items: CorpusSet[]; total: number }> {
  const response = await http.get<{ items: CorpusSet[]; total: number }>("/xhs/corpus", {
    params: kind ? { kind } : undefined,
  });
  return response.data;
}

export async function createCorpusSet(payload: {
  name: string;
  kind: CorpusKind;
  source_accounts?: string[];
  keyword?: string;
  platform_account_id?: number | null;
}): Promise<CorpusSet> {
  const response = await http.post<CorpusSet>("/xhs/corpus", payload);
  return response.data;
}

export async function fetchCorpusSet(
  setId: number,
  filters?: { collect_status?: string; genre?: string },
): Promise<{ set: CorpusSet; items: CorpusMember[] }> {
  const response = await http.get<{ set: CorpusSet; items: CorpusMember[] }>(
    `/xhs/corpus/${setId}`,
    { params: filters },
  );
  return response.data;
}

export async function collectCorpusSet(
  setId: number,
  payload?: { max_pages?: number; save_to_library?: boolean },
): Promise<{ set: CorpusSet; saved: number; failed: number; stopped_reason: string }> {
  const response = await http.post<{
    set: CorpusSet;
    saved: number;
    failed: number;
    stopped_reason: string;
  }>(`/xhs/corpus/${setId}/collect`, payload ?? {}, { timeout: 600000 });
  return response.data;
}

/**
 * Fill in bodies for notes collected from a listing page.
 *
 * A profile listing returns titles only, so a freshly collected set is mostly
 * `pending_body`. Each call is bounded (≤60) because bodies cost one detail
 * call each at 3/min — a single call covering hundreds would take hours.
 */
export async function collectCorpusBodies(
  setId: number,
  limit = 20,
): Promise<{
  ok: number;
  throttled: number;
  deleted: number;
  empty_body: number;
  remaining: number;
  stopped_reason: string;
  cooldown_minutes: number;
  message: string;
}> {
  const response = await http.post<{
    ok: number;
    throttled: number;
    deleted: number;
    empty_body: number;
    remaining: number;
    stopped_reason: string;
    cooldown_minutes: number;
    message: string;
  }>(`/xhs/corpus/${setId}/collect-bodies`, { limit }, { timeout: 1800000 });
  return response.data;
}

export async function labelCorpusMembers(
  setId: number,
  memberIds: number[],
  genre: string,
): Promise<{ updated: number; set: CorpusSet }> {
  const response = await http.post<{ updated: number; set: CorpusSet }>(
    `/xhs/corpus/${setId}/label`,
    { member_ids: memberIds, genre },
  );
  return response.data;
}

export type CorpusHomogeneity = {
  total: number;
  prefix_share: number;
  top_prefix?: string;
  event_recruit_share: number;
  list_share: number;
  median_length?: number;
  homogeneous: boolean;
  reason: string;
};

export type LabelAllCorpusResult = {
  updated: number;
  would_update: number;
  homogeneity: CorpusHomogeneity;
  dry_run: boolean;
  set?: CorpusSet;
};

export async function fetchCorpusHomogeneity(
  setId: number,
): Promise<CorpusHomogeneity> {
  const response = await http.get<CorpusHomogeneity>(
    `/xhs/corpus/${setId}/homogeneity`,
  );
  return response.data;
}

export async function labelAllCorpusMembers(
  setId: number,
  genre: string,
  confirm = false,
): Promise<LabelAllCorpusResult> {
  const response = await http.post<LabelAllCorpusResult>(
    `/xhs/corpus/${setId}/label-all`,
    { genre, confirm },
  );
  return response.data;
}

export async function assignCorpusRoles(setId: number): Promise<{
  set_id: number;
  genres: Record<string, Record<string, unknown>>;
  skipped_unclassified: number;
  skipped_uncollected: number;
  set: CorpusSet;
}> {
  const response = await http.post<{
    set_id: number;
    genres: Record<string, Record<string, unknown>>;
    skipped_unclassified: number;
    skipped_uncollected: number;
    set: CorpusSet;
  }>(`/xhs/corpus/${setId}/assign-roles`, {});
  return response.data;
}

// ===========================================================================
// XHS · Account positioning（账号定位）
// ===========================================================================

export type AccountPositioning = {
  account_id: number | null;
  positioning: string;
  audience: string;
  promise: string;
  main_topics: string[];
  taboos: string[];
  language_samples: string[];
  source: string;
  missing: string[];
  is_empty: boolean;
  updated_at: string | null;
};

export type AccountPositioningPayload = {
  positioning?: string;
  audience?: string;
  promise?: string;
  main_topics?: string[] | string;
  taboos?: string[] | string;
  language_samples?: string[] | string;
};

export async function fetchAccountPositioning(accountId?: number | null): Promise<AccountPositioning> {
  const response = await http.get<AccountPositioning>("/xhs/account-positioning", {
    params: accountId ? { account_id: accountId } : undefined,
  });
  return response.data;
}

export async function saveAccountPositioning(
  payload: AccountPositioningPayload,
  accountId?: number | null,
): Promise<AccountPositioning> {
  const response = await http.put<AccountPositioning>("/xhs/account-positioning", payload, {
    params: accountId ? { account_id: accountId } : undefined,
  });
  return response.data;
}

export async function fetchPositioningPromptBlock(
  accountId?: number | null,
): Promise<{ account_id: number | null; prompt_block: string; chars: number }> {
  const response = await http.get<{
    account_id: number | null;
    prompt_block: string;
    chars: number;
  }>("/xhs/account-positioning/prompt-block", {
    params: accountId ? { account_id: accountId } : undefined,
  });
  return response.data;
}

// ===========================================================================
// XHS · Style distill（风格蒸馏）
// ===========================================================================

export async function distillStyleProfile(
  jobId: number,
  name = "",
  useLlm = true,
): Promise<StyleProfileDetail> {
  const response = await http.post<StyleProfileDetail>("/xhs/style-distill", {
    job_id: jobId,
    name,
    use_llm: useLlm,
  });
  return response.data;
}

export async function distillStyleFromLibrary(
  noteIds: number[],
  name = "",
  useLlm = true,
): Promise<StyleProfileDetail> {
  const response = await http.post<StyleProfileDetail>("/xhs/style-distill/from-library", {
    note_ids: noteIds,
    name,
    use_llm: useLlm,
  });
  return response.data;
}

export async function saveStyleFromArtifact(payload: {
  name: string;
  artifact_md: string;
  fields: SkillField[];
  values: Record<string, string>;
  skill_slug?: string;
  account_id?: number | null;
}): Promise<StyleProfileDetail> {
  const response = await http.post<StyleProfileDetail>("/xhs/style-distill/from-artifact", payload, {
    timeout: 60000,
  });
  return response.data;
}

export async function fetchStyleProfiles(): Promise<{ items: StyleProfileSummary[]; total: number }> {
  const response = await http.get<{ items: StyleProfileSummary[]; total: number }>(
    "/xhs/style-distill",
  );
  return response.data;
}

export async function fetchStyleProfile(profileId: number): Promise<StyleProfileDetail> {
  const response = await http.get<StyleProfileDetail>(`/xhs/style-distill/${profileId}`);
  return response.data;
}

export async function applyStyleProfile(
  profileId: number,
  accountId: number,
): Promise<{ skill_id: number; skill_version: string; message: string }> {
  const response = await http.post<{ skill_id: number; skill_version: string; message: string }>(
    `/xhs/style-distill/${profileId}/apply`,
    { account_id: accountId },
  );
  return response.data;
}

export async function unapplyStyleProfile(
  profileId: number,
  accountId: number,
): Promise<{ skill_id: number; skill_status: string; account_id: number | null; message: string }> {
  const response = await http.post<{
    skill_id: number;
    skill_status: string;
    account_id: number | null;
    message: string;
  }>(`/xhs/style-distill/${profileId}/unapply`, { account_id: accountId });
  return response.data;
}

export async function deleteStyleProfile(profileId: number): Promise<{ id: number; deleted: boolean }> {
  const response = await http.delete<{ id: number; deleted: boolean }>(
    `/xhs/style-distill/${profileId}`,
  );
  return response.data;
}

export async function convertStyleProfile(
  profileId: number,
  accountId: number,
  limit = 3,
): Promise<StyleConvertResult> {
  const response = await http.post<StyleConvertResult>(
    `/xhs/style-distill/${profileId}/convert`,
    { account_id: accountId, limit },
  );
  return response.data;
}

// ===========================================================================
// XHS · Evidence distill（证据蒸馏：假设 → 取证 → 判定）
// ===========================================================================

export type EvidenceReportItem = {
  key: string;
  claim: string;
  source: "theory" | "corpus";
  dimension: string;
  verdict: "hard_rule" | "tendency" | "preference" | "design_choice" | "insufficient";
  coverage: number;
  support: number;
  total: number;
  reason: string;
  rule: string;
  counter_rule: string;
  note: string;
  samples: string[];
  counter_examples: string[];
  /** 对照组的覆盖率（有对照组时才有）。 */
  control_coverage?: number;
  control_total?: number;
  /** 对照比较的精确检验 p 值（有对照组时才有）。 */
  control_p?: number;
  /** `low` = 对照样本小或 p 接近 0.10，偏好只作探索性结论。 */
  preference_confidence?: "low" | "medium";
  /** 两批复现：只有 confirmed 才注入。 */
  preference_status?: "confirmed" | "candidate" | "";
  discovery_coverage?: number;
  confirmation_coverage?: number;
  /** 两边都成立 → 体裁共性，不注入。 */
  genre_convention?: boolean;
};

export type EvidenceProfile = {
  id: number;
  name: string;
  status: string;
  source: string;
  engine: string;
  works_count: number;
  char_count: number;
  created_at: string | null;
  summary: Record<string, number>;
  corpus: Record<string, number>;
  items: EvidenceReportItem[];
  thresholds: { hard?: number; tendency?: number };
  injectable_rules: string[];
  /** 语料里的作者规模。「多人混合」时无法产出可注入规则。 */
  author_mix?: {
    authors?: number;
    posts?: number;
    top_share?: number;
    single_author?: boolean;
  };
  /** 没有产出规则时的原因说明（目前只在多作者语料时给）。 */
  corpus_warning?: string;
  /** 这次用的是哪套假设：spoken（口播 8 条）/ text（文字 19 条）。 */
  hypothesis_set?: "text" | "spoken" | "spoken_structure" | "excel";
  /** 这次蒸馏用的对标集。 */
  corpus_set_id?: number | null;
  /** 对照组的语料信息（有对照组时才有）。 */
  genre_baseline?: {
    label?: string;
    corpus?: Record<string, number>;
    thresholds?: { coverage?: number; gap?: number };
  };
  /** 两批复现的批次信息。 */
  batch_plan?: {
    mode?: "single" | "two_batch" | "insufficient_batches";
    batches?: Array<{ job_id: number; docs: number }>;
    discovery_job_id?: number;
    discovery_docs?: number;
    confirmation_job_id?: number;
    confirmation_docs?: number;
    needed_confirmation_docs?: number;
    note?: string;
  };
  skill_md: string;
  injection_block: string;
};

export type HypothesisMeta = {
  key: string;
  claim: string;
  source: string;
  dimension: string;
  detector: string;
  rule: string;
  counter_rule: string;
  note: string;
  tags: string[];
};

export async function fetchDistillMeta(): Promise<{
  hypotheses: HypothesisMeta[];
  thresholds: { hard: number; tendency: number };
  verdict_labels: Record<string, string>;
  min_documents: number;
}> {
  const response = await http.get("/xhs/evidence-distill/meta");
  return response.data;
}

export async function runEvidenceDistill(payload: {
  set_id: number;
  name?: string;
  account_id?: number | null;
  control_set_id?: number | null;
  hypothesis_set?: "auto" | "text" | "spoken" | "spoken_structure" | "excel";
}): Promise<EvidenceProfile> {
  const response = await http.post<EvidenceProfile>("/xhs/evidence-distill", payload, {
    timeout: 120000,
  });
  return response.data;
}

export async function fetchEvidenceProfiles(): Promise<{ items: EvidenceProfile[]; total: number }> {
  const response = await http.get<{ items: EvidenceProfile[]; total: number }>(
    "/xhs/evidence-distill/profiles",
  );
  return response.data;
}

export async function deleteEvidenceProfile(
  profileId: number,
): Promise<{ id: number; deleted: boolean }> {
  const response = await http.delete<{ id: number; deleted: boolean }>(
    `/xhs/evidence-distill/profiles/${profileId}`,
  );
  return response.data;
}

// ===========================================================================
// XHS · Topics
// ===========================================================================

export async function generateTopicBank(payload: {
  topic?: string;
  account_id?: number | null;
  count?: number;
  [key: string]: unknown;
}): Promise<TopicBankResult> {
  const response = await http.post<TopicBankResult>("/xhs/topics/generate", payload, {
    timeout: 180000,
  });
  return response.data;
}

export async function fetchSavedTopics(
  accountId?: number | null,
  statusValue?: string,
): Promise<{ items: SavedTopic[]; total: number }> {
  const response = await http.get<{ items: SavedTopic[]; total: number }>("/xhs/topics", {
    params: { account_id: accountId ?? undefined, status: statusValue ?? undefined },
  });
  return response.data;
}

export async function updateTopicStatus(
  topicId: number,
  payload: Record<string, unknown> | string,
): Promise<SavedTopic> {
  const body = typeof payload === "string" ? { status: payload } : payload;
  const response = await http.patch<SavedTopic>(`/xhs/topics/${topicId}`, body);
  return response.data;
}

export async function scheduleTopic(
  topicId: number,
  scheduledFor: string | null,
): Promise<SavedTopic> {
  const response = await http.patch<SavedTopic>(`/xhs/topics/${topicId}/schedule`, {
    scheduled_for: scheduledFor,
  });
  return response.data;
}

export async function createDraftFromTopic(
  topicId: number,
  templateId?: number | null,
): Promise<Draft> {
  const response = await http.post<Draft>(
    `/xhs/topics/${topicId}/draft`,
    { template_id: templateId ?? null },
    { timeout: 240000 },
  );
  return response.data;
}

// ===========================================================================
// XHS · PC provider / Trends / Redfox / Creator / Login sessions
// ===========================================================================

export async function searchXhsNotes(payload: Record<string, unknown>): Promise<XhsNoteSearchResponse> {
  const response = await http.post<XhsNoteSearchResponse>("/xhs/pc/search/notes", payload);
  return response.data;
}

export async function fetchXhsProviderStatus(): Promise<XhsProviderStatus> {
  const response = await http.get<XhsProviderStatus>("/xhs/pc/provider");
  return response.data;
}

export async function fetchXhsNoteDetail(
  payload: Record<string, unknown>,
): Promise<{
  content?: string;
  note?: Record<string, unknown>;
  note_url?: string;
  title?: string;
  [key: string]: unknown;
}> {
  const response = await http.post<Record<string, unknown>>("/xhs/pc/notes/detail", payload);
  return response.data;
}

export async function fetchXhsNoteComments(
  payload: Record<string, unknown>,
): Promise<{ items: NoteComment[]; total?: number }> {
  const response = await http.post<{ items: NoteComment[]; total?: number }>(
    "/xhs/pc/notes/comments",
    payload,
  );
  return response.data;
}

export async function fetchUserNotes(payload: {
  account_id: number;
  user_id: string;
  limit?: number;
}): Promise<{ items: XhsSearchNote[] }> {
  const response = await http.post<{ items: XhsSearchNote[] }>("/xhs/pc/users/notes", payload, {
    timeout: 120000,
  });
  return response.data;
}

export async function fetchXhsTrendsMeta(params?: Record<string, unknown>): Promise<XhsTrendMeta> {
  const response = await http.get<XhsTrendMeta>("/xhs/trends/meta", { params });
  return response.data;
}

export async function fetchXhsViralInsights(payload: Record<string, unknown>): Promise<XhsViralInsightsResponse> {
  const response = await http.post<XhsViralInsightsResponse>("/xhs/trends/viral-insights", payload);
  return response.data;
}

export async function fetchXhsLowFanRanking(payload: Record<string, unknown>): Promise<XhsTrendResponse> {
  const response = await http.post<XhsTrendResponse>("/xhs/trends/low-fan-ranking", payload);
  return response.data;
}

export async function fetchXhsRanking(payload: Record<string, unknown>): Promise<XhsTrendResponse> {
  const response = await http.post<XhsTrendResponse>("/xhs/trends/ranking", payload);
  return response.data;
}

export async function searchXhsTrendUsers(payload: Record<string, unknown>): Promise<XhsTrendUserResponse> {
  const response = await http.post<XhsTrendUserResponse>("/xhs/trends/search-users", payload);
  return response.data;
}

export async function fetchXhsHotAccounts(payload: Record<string, unknown>): Promise<XhsHotAccountResponse> {
  const response = await http.post<XhsHotAccountResponse>("/xhs/trends/hot-accounts", payload);
  return response.data;
}

export async function fetchXhsHotList(params?: Record<string, unknown>): Promise<XhsHotListResponse> {
  const response = await http.get<XhsHotListResponse>("/xhs/trends/hot-list", { params });
  return response.data;
}

export async function fetchXhsRedfoxBalance(): Promise<XhsRedfoxBalance> {
  const response = await http.get<XhsRedfoxBalance>("/xhs/redfox/balance");
  return response.data;
}

export async function fetchXhsRedfoxStatus(
  params?: Record<string, unknown>,
): Promise<XhsRedfoxStatus> {
  const response = await http.get<XhsRedfoxStatus>("/xhs/redfox/status", { params });
  return response.data;
}

export async function fetchXhsRedfoxUsage(params?: Record<string, unknown>): Promise<XhsRedfoxUsage> {
  const response = await http.get<XhsRedfoxUsage>("/xhs/redfox/usage", { params });
  return response.data;
}

export async function checkXhsSensitiveWords(content: string): Promise<XhsSensitiveWordResult> {
  const response = await http.post<XhsSensitiveWordResult>("/xhs/redfox/sensitive-words", {
    content,
  });
  return response.data;
}

export async function fetchCreatorPublished(
  params?: Record<string, unknown> | number,
): Promise<{ items: CreatorPublishedNote[]; total: number }> {
  const query = typeof params === "number" ? { account_id: params } : (params ?? {});
  const response = await http.get<{ items: CreatorPublishedNote[]; total: number }>(
    "/xhs/creator/published",
    { params: query, timeout: 120000 },
  );
  return response.data;
}

export async function importCreatorPublished(
  payload: Record<string, unknown> | number,
): Promise<{ imported?: number; updated?: number; [key: string]: unknown }> {
  const body = typeof payload === "number" ? { account_id: payload } : payload;
  const response = await http.post<{ imported?: number; updated?: number }>(
    "/xhs/creator/published/import",
    body,
    { timeout: 120000 },
  );
  return response.data;
}

export async function recommendXhsTopics(payload: Record<string, unknown>): Promise<{
  items: XhsTopicRecommendation[];
}> {
  const response = await http.post<{ items: XhsTopicRecommendation[] }>(
    "/xhs/creator/topic-recommendations",
    payload,
  );
  return response.data;
}

export async function createXhsPcQrLoginSession(payload?: {
  sync_creator?: boolean;
}): Promise<XhsQrLoginSession> {
  const response = await http.post<XhsQrLoginSession>(
    "/xhs/login-sessions/pc/qrcode",
    payload ?? {},
  );
  return response.data;
}

export async function createXhsCreatorQrLoginSession(): Promise<XhsQrLoginSession> {
  const response = await http.post<XhsQrLoginSession>("/xhs/login-sessions/creator/qrcode");
  return response.data;
}

export async function pollXhsLoginSession(sessionId: string | number): Promise<XhsQrLoginSession> {
  const response = await http.get<XhsQrLoginSession>(`/xhs/login-sessions/${sessionId}`);
  return response.data;
}

export async function sendXhsPhoneCode(payload: {
  sub_type: "pc" | "creator";
  session_id: string | number;
  phone: string;
  sync_creator?: boolean;
}): Promise<XhsQrLoginSession & { ok?: boolean; message?: string; session_id?: string | number }> {
  const response = await http.post<XhsQrLoginSession & { ok?: boolean; message?: string }>(
    `/xhs/login-sessions/${payload.sub_type}/phone/send-code`,
    { ...payload, session_id: String(payload.session_id) },
  );
  return response.data as XhsQrLoginSession & { ok?: boolean; message?: string };
}

export async function confirmXhsPhoneLogin(payload: {
  sub_type: "pc" | "creator";
  session_id: string | number;
  phone: string;
  code: string;
  sync_creator?: boolean;
}): Promise<XhsQrLoginSession> {
  const response = await http.post<XhsQrLoginSession>(
    `/xhs/login-sessions/${payload.sub_type}/phone/confirm`,
    { ...payload, session_id: String(payload.session_id) },
  );
  return response.data;
}

export async function generateMatrixDrafts(payload: Record<string, unknown>): Promise<MatrixDraftResult> {
  const response = await http.post<MatrixDraftResult>("/xhs/matrix/generate", payload, {
    timeout: 300000,
  });
  return response.data;
}

export async function suggestMatrixDirections(payload: Record<string, unknown>): Promise<{
  items: {
    account_id?: number;
    direction: string;
    reason: string;
    [key: string]: unknown;
  }[];
}> {
  const response = await http.post<{
    items: { account_id?: number; direction: string; reason: string }[];
  }>("/xhs/matrix/suggest-directions", payload, { timeout: 180000 });
  return response.data;
}

export async function crawlXhsDataStream(
  payload: XhsDataCrawlPayload,
  onEvent?: ((event: Record<string, unknown>) => void) | ((index: number, item: unknown) => void),
  onProgress?: (message: string) => void,
  _onDone?: (summary: unknown) => void,
  /** Called once when the server announces how many notes it will attempt. */
  onPlan?: (planned: number, pages: number) => void,
  /** Called for every finished item with the running count, for progress bars. */
  onCount?: (processed: number) => void,
): Promise<XhsDataCrawlResponse> {
  const response = await fetch("/api/xhs/crawl/data", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(getAccessToken() ? { Authorization: `Bearer ${getAccessToken()}` } : {}),
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok || !response.body) {
    throw new Error(`采集失败（HTTP ${response.status}）`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let summary: XhsDataCrawlResponse | null = null;
  let index = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() ?? "";
    for (const chunk of chunks) {
      const line = chunk.split("\n").find((item) => item.startsWith("data: "));
      if (!line) continue;
      try {
        const event = JSON.parse(line.slice(6)) as Record<string, unknown>;
        const kind = String(event?.type ?? "");
        // `plan` announces the denominator; `item` carries one finished note with
        // its running count. Only items belong in the result list — passing plan
        // through the item callback used to append a junk row.
        if (kind === "plan") {
          if (onPlan) onPlan(Number(event.planned) || 0, Number(event.pages) || 0);
          continue;
        }
        if (kind === "item") {
          if (onCount && event.processed !== undefined) {
            onCount(Number(event.processed) || 0);
          }
          if (onEvent) {
            (onEvent as (i: number, e: unknown) => void)(index, event);
            index += 1;
          }
          continue;
        }
        if (event?.saved_count !== undefined || kind === "summary" || kind === "done") {
          summary = event as unknown as XhsDataCrawlResponse;
        }
        if (event?.message && onProgress) {
          onProgress(String(event.message));
        }
      } catch {
        // 单条解析失败不影响整体
      }
    }
  }
  return summary ?? ({ saved_count: 0, result_count: 0, items: [] } as unknown as XhsDataCrawlResponse);
}

export async function writeReviewToMemory(payload: Record<string, unknown>): Promise<ReviewWritebackResult> {
  const response = await http.post<ReviewWritebackResult>("/xhs/analytics/review", payload, {
    timeout: 120000,
  });
  return response.data;
}
