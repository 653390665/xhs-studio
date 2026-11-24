export type PlatformId = "xhs" | "douyin" | "kuaishou" | "weibo" | "xianyu" | "taobao";

export type PlatformMeta = {
  id: PlatformId;
  name_cn: string;
  name_en: string;
  enabled: boolean;
  status: "enabled" | "coming_soon";
  accent_color: string;
  icon: string;
};

export type Paginated<T> = {
  total: number;
  page: number;
  page_size: number;
  items: T[];
  /** Notes the follower filter hid because their author was never measured.
   *
   * A filtered total on its own reads as "this is everything". When the server
   * skips samples it cannot judge, it says how many so the number stays honest.
   */
  unmeasured_fans?: number;
  filter_note?: string;
};

export type AgentMemoryRecord = {
  id: number;
  kind: string;
  key: string;
  value: Record<string, unknown>;
  confidence: number;
  source: string;
  updated_at?: string | null;
};

export type AgentStepRecord = {
  id: number;
  step_index: number;
  tool: string;
  args: Record<string, unknown>;
  status: string;
  output: Record<string, unknown>;
  error: string;
  created_at?: string | null;
  finished_at?: string | null;
};

export type AgentRun = {
  id: number;
  platform_account_id?: number | null;
  goal: string;
  status: string;
  summary: string;
  error: string;
  steps: AgentStepRecord[];
  created_at?: string | null;
  updated_at?: string | null;
};

export type DashboardOverview = {
  platform: "xhs";
  today_crawls: number;
  saved_notes: number;
  own_notes?: number;
  library_notes?: number;
  pending_publishes: number;
  healthy_accounts: number;
  at_risk_accounts: number;
  comment_count?: number;
  total_engagement?: number;
  own_total_engagement?: number;
  library_total_engagement?: number;
  hot_topics: Array<{ keyword: string; notes: number; engagement: number }>;
  recent_activity: Array<{ type: string; title: string; status: string }>;
};

export type PlatformUser = {
  id: number;
  username: string;
};

export type AuthTokens = {
  access_token: string;
  refresh_token?: string;
  token_type: "bearer";
};

export type AuthPayload = AuthTokens & {
  user: PlatformUser;
};

export type PlatformAccount = {
  id: number;
  platform: PlatformId;
  sub_type: "pc" | "creator" | null;
  external_user_id?: string;
  nickname: string;
  avatar_url?: string;
  status: "active" | "healthy" | "expired" | "risk" | "unknown" | string;
  status_message?: string;
  profile?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
  action?: "created" | "updated" | string;
};

export type XhsQrLoginSession = {
  session_id: number;
  status: "pending" | "scanned" | "confirmed" | "expired" | string;
  qr_url: string;
  qr_image_data_url?: string;
  account?: PlatformAccount | null;
  creator_account?: PlatformAccount | null;
};

export type XhsSearchNote = {
  note_id: string;
  note_url?: string;
  title: string;
  content: string;
  author_id: string;
  author_name: string;
  author_avatar: string;
  author_fans?: number;
  author_follows?: number;
  author_notes?: number;
  like_fan_ratio?: number;
  engagement_rate?: number;
  metrics_fetched_at?: string;
  metrics_error?: string;
  cover_url: string;
  likes: number;
  collects: number;
  comments: number;
  shares: number;
  type: string;
  timestamp?: number | string;
  image_urls?: string[];
  video_url?: string;
  video_addr?: string;
  tags?: string[];
  raw: Record<string, unknown>;
};

export type XhsSearchEnrichment = {
  candidate_authors: number;
  profiles_requested: number;
  profiles_fetched: number;
  profile_errors: number;
  profiles_cached: number;
};

export type XhsNoteSearchResponse = {
  total: number;
  raw_total?: number;
  filtered_total?: number;
  filtered_out?: number;
  page: number;
  page_size: number;
  has_more: boolean;
  items: XhsSearchNote[];
  enrichment?: XhsSearchEnrichment | null;
  raw: Record<string, unknown>;
};

export type XhsSearchOptions = {
  account_id: number;
  keyword: string;
  page?: number;
  sort_type_choice?: number;
  note_type?: number;
  note_time?: number;
  note_range?: number;
  pos_distance?: number;
  geo?: string;
  enrich_authors?: boolean;
  min_likes_for_profile?: number;
  max_profiles?: number;
  max_fans?: number;
  min_likes?: number;
  min_like_fan_ratio?: number;
  sort_by?: "default" | "likes" | "like_fan_ratio" | "engagement_rate";
};

export type XhsDataProvider = "pc" | "redfox";

export type XhsProviderStatus = {
  configured_provider: XhsDataProvider | string;
  effective_provider: XhsDataProvider | string;
  redfox_configured: boolean;
  redfox_api_base_url: string;
  redfox_daily_call_limit: number;
  redfox_usage: { day: string | null; count: number };
};

export type XhsTrendMeta = {
  provider: string;
  available: boolean;
  categories: string[];
  message: string;
  balance?: number | null;
  reason?: string;
  hot_list_available?: boolean;
  hot_list_source?: "redfox" | "free" | "none";
  features?: Record<string, boolean>;
};

export type XhsRedfoxStatus = {
  configured: boolean;
  available: boolean;
  balance: number | null;
  reason: string;
  message: string;
  usage?: { day: string; count: number };
};

export type XhsCreatorBridgeResult = {
  ok: boolean;
  keyword: string;
  creator_build: string;
  sample_topics: string[];
  error: string;
  account_id: number;
};

export type XhsTrendResponse = {
  items: XhsSearchNote[];
  total: number;
  empty: boolean;
  category?: string;
  rank_date?: string;
  period?: string;
};

export type XhsViralInsightsResponse = XhsTrendResponse & {
  page_num: number;
  page_size: number;
  hot_topics: Array<Record<string, unknown>>;
  related_searches: Array<{ keyword?: string; articleCount?: number }>;
};

export type XhsTrendUser = {
  user_id: string;
  account_id: string;
  nickname: string;
  avatar: string;
  desc: string;
  fans: number;
  notes: number;
  likes: number;
  collects: number;
  province?: string | null;
  city?: string | null;
};

export type XhsTrendUserResponse = {
  items: XhsTrendUser[];
  total: number;
  page: number;
  has_more: boolean;
  empty: boolean;
};

export type XhsHotAccount = {
  user_id: string;
  account_link: string;
  nickname: string;
  avatar: string;
  category: string;
  ranking: number;
  fans: number;
  fans_growth: number;
  likes_growth: number;
  collects_growth: number;
  comments_growth: number;
  shares_growth: number;
  new_notes: number;
  rank_date?: string | null;
};

export type XhsHotAccountResponse = {
  items: XhsHotAccount[];
  total: number;
  date_type: number;
  category: string;
  rank_date: string;
  empty: boolean;
};

export type XhsRedfoxBalance = {
  available: number;
  free: number;
  paid: number;
};

export type XhsRedfoxUsageItem = {
  points: number;
  reason: string;
  reason_desc: string;
  created_at: string;
};

export type XhsRedfoxUsage = {
  items: XhsRedfoxUsageItem[];
  total: number;
  pages: number;
  page: number;
  page_size: number;
};

export type XhsSensitiveWordHit = {
  word: string;
  kind: string;
};

export type XhsSensitiveWordResult = {
  highlighted: string;
  original: string;
  hits: XhsSensitiveWordHit[];
  hit_count: number;
  types: string[];
  clean: boolean;
  source?: string;
};

export type XhsTrendInfo = {
  direction: "up" | "down" | "flat" | "new";
  delta_pct: number;
  points: number[];
  days: number;
  first_text?: string;
  last_text?: string;
};

export type XhsHotListItem = {
  rank: number;
  title: string;
  hot_score: number;
  hot_text: string;
  url: string;
  updated_at: string;
  word_type?: string;
  trend?: XhsTrendInfo;
};

export type XhsHotListResponse = {
  items: XhsHotListItem[];
  total: number;
  platform: number;
  start_date: string;
  end_date: string;
  empty: boolean;
  source?: "redfox" | "free";
  provider?: string;
  fallback_reason?: string;
};

export type XhsDataCrawlMode = "note_urls" | "search" | "comments";

export type XhsDataCrawlPayload = {
  account_id: number;
  mode: XhsDataCrawlMode;
  urls?: string[];
  keyword?: string;
  pages?: number;
  max_notes?: number;
  time_sleep?: number;
  fetch_comments?: boolean;
  sort_type_choice?: number;
  note_type?: number;
  note_time?: number;
  note_range?: number;
  pos_distance?: number;
  geo?: string;
};

export type XhsDataCrawlItem = {
  source: string;
  status: "success" | "failed" | string;
  error: string;
  note?: XhsSearchNote | null;
  comments: NoteComment[];
  comment_count: number;
};

export type XhsDataCrawlResponse = {
  task: TaskRecord;
  total: number;
  success_count: number;
  failed_count: number;
  items: XhsDataCrawlItem[];
};

export type SavedNote = {
  id: number;
  platform: PlatformId;
  platform_account_id: number;
  note_id: string;
  title: string;
  content: string;
  author_name: string;
  author_id?: string;
  author_fans?: number;
  likes?: number;
  collects?: number;
  comments?: number;
  shares?: number;
  like_fan_ratio?: number;
  engagement_rate?: number;
  metrics_fetched_at?: string | null;
  source_type?: string;
  is_own?: boolean;
  raw_json?: Record<string, unknown>;
  asset_urls?: string[];
  cover_url?: string;
  video_url?: string;
  video_addr?: string;
  created_at: string;
  tags?: Tag[];
};

export type AnalyticsTopContent = {
  id: number;
  note_id: string;
  title: string;
  content?: string;
  note_url?: string;
  platform_account_id?: number;
  author_name: string;
  created_at: string;
  likes: number;
  collects: number;
  comments: number;
  shares: number;
  engagement: number;
};

export type AnalyticsHotTopic = {
  keyword: string;
  notes: number;
  engagement: number;
};

export type AnalyticsCommentInsight = {
  total_comments: number;
  question_count: number;
  top_terms: Array<{ term: string; count: number }>;
  top_comments: Array<{
    id: number;
    note_id: number;
    user_name: string;
    content: string;
    like_count: number;
  }>;
};

export type BenchmarkTopNote = AnalyticsTopContent;

export type BenchmarkItem = {
  target_id: number;
  target_type: "account" | "brand" | string;
  name: string;
  value: string;
  status: string;
  last_refreshed_at?: string | null;
  matched_notes: number;
  total_engagement: number;
  average_engagement: number;
  top_notes: BenchmarkTopNote[];
};

export type BenchmarkOverview = {
  total_targets: number;
  matched_notes: number;
  total_engagement: number;
  average_engagement: number;
  items: BenchmarkItem[];
};

export type NoteAsset = {
  id: number;
  note_id: number;
  asset_type: "image" | "video" | string;
  url: string;
  local_path: string;
  download_url?: string;
  sort_order?: number;
};

export type NoteComment = {
  id: number;
  note_id: number;
  comment_id: string;
  user_name: string;
  user_id?: string | null;
  content: string;
  like_count: number;
  parent_comment_id?: string | null;
  created_at_remote?: string | null;
  raw_json?: Record<string, unknown>;
};

export type Tag = {
  id: number;
  name: string;
  color: string;
};

export type TagPayload = {
  name: string;
  color?: string;
};

export type BatchTagNotesPayload = {
  note_ids: number[];
  tag_ids: number[];
  mode: "replace" | "add" | "remove";
};

export type BatchTagNotesResponse = {
  updated_count: number;
  items: SavedNote[];
};

export type BatchCreateDraftsPayload = {
  note_ids: number[];
  intent?: "rewrite" | "publish" | string;
};

export type BatchCreateDraftsResponse = {
  created_count: number;
  items: Draft[];
};

export type BenchmarkCreateDraftsResponse = BatchCreateDraftsResponse;

export type NotesExportPayload = {
  note_ids: number[];
  format?: "json" | "csv";
};

export type NotesExportResponse = {
  exported_count: number;
  file_name: string;
  file_path: string;
  download_url: string;
};

export type AnalyticsReportPayload = {
  note_ids?: number[];
  format?: "json";
};

export type AnalyticsReportResponse = {
  report_type: "operations";
  generated_at: string;
  note_count: number;
  file_name: string;
  file_path: string;
  download_url: string;
  summary: {
    note_count: number;
    total_engagement: number;
    comment_count: number;
    top_topics: AnalyticsHotTopic[];
    top_notes: AnalyticsTopContent[];
    benchmark_count: number;
  };
};

export type SaveNotesResponse = {
  saved_count: number;
  items: SavedNote[];
};

export type Draft = {
  id: number;
  platform: PlatformId;
  platform_account_id?: number | null;
  title: string;
  body: string;
  tags?: { id?: string; name: string }[];
  source_note_id?: number | null;
  template_id?: number | null;
  topic_id?: number | null;
  origin?: "manual" | "ai" | "ai_image" | "agent" | "matrix" | "batch_rewrite" | "batch_create" | "auto_ops" | string;
  pipeline_id?: string | null;
  skill_version?: string;
  pillar?: string;
  experiment?: string;
  review_status?: "pending" | "adopted" | "discarded" | string;
  created_at: string;
  // 草稿列表的轻量发布就绪字段（不需要逐条调用完整 preflight）
  asset_count?: number;
  image_count?: number;
  video_count?: number;
  media_ready?: boolean;
  account_ready?: boolean;
  // 部分接口（如按笔记生成草稿）会带这两个字段
  version?: number;
  draft?: { id: number; title: string } | null;
  preflight?: Record<string, unknown> | null;
};

export type CreateDraftPayload = {
  platform: "xhs";
  source_note_id?: number;
  title?: string;
  body?: string;
  tags?: string[];
  intent?: "rewrite" | "publish" | string;
  account_id?: number | null;
  platform_account_id?: number | null;
  template_id?: number | null;
  topic_id?: number | null;
};

export type ModelType = "text" | "image";

export type ModelConfig = {
  id: number;
  name: string;
  model_type: ModelType;
  provider: string;
  model_name: string;
  base_url: string;
  has_api_key: boolean;
  is_default: boolean;
};

export type ModelConfigPayload = {
  name: string;
  model_type: ModelType;
  provider: string;
  model_name: string;
  base_url: string;
  api_key: string;
  is_default: boolean;
};

export type RewriteDraftPayload = {
  draft_id: number;
  instruction?: string;
  template_id?: number | null;
  account_id?: number | null;
};

export type GenerateNotePayload = {
  platform?: "xhs";
  topic: string;
  reference?: string;
  instruction?: string;
  template_id?: number | null;
  account_id?: number | null;
  enhance_middle?: boolean;
};

export type GenerateTitlePayload = {
  title?: string;
  body: string;
  count?: number;
  template_id?: number | null;
  account_id?: number | null;
};

export type GenerateTagsPayload = {
  title?: string;
  body: string;
  count?: number;
  account_id?: number | null;
};

export type PolishTextPayload = {
  text: string;
  instruction?: string;
};

export type GeneratedImageAsset = {
  id: number;
  draft_id?: number | null;
  prompt: string;
  model_name: string;
  params: Record<string, unknown>;
  file_path: string;
  created_at: string;
};

export type GenerateCoverPayload = {
  prompt: string;
  draft_id?: number;
  size?: string;
  style?: string;
};

export type GenerateImagePayload = {
  prompt: string;
  reference_images?: string[];
  save_to_assets?: boolean;
  draft_id?: number;
  size?: string;
};

export type GenerateImageResult = {
  url: string;
  raw?: unknown;
  asset?: GeneratedImageAsset;
};

export type UserImageFile = {
  file_name: string;
  url: string;
  size: number;
};

export type DescribeImagePayload = {
  image_url: string;
  instruction?: string;
};

export type ImageUtilityFile = {
  file_name: string;
  file_path: string;
  download_url: string;
  width: number;
  height: number;
  media_type: string;
};

export type ComposeImagePayload = {
  title: string;
  body?: string;
  width?: number;
  height?: number;
  background_color?: string;
  accent_color?: string;
};

export type ResizeImagePayload = {
  source_file_name: string;
  width?: number;
  height?: number;
  mode?: "cover" | "contain";
  format?: "png" | "jpeg";
  quality?: number;
};

export type TaskRecord = {
  id: number;
  platform: PlatformId;
  task_type: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled" | "exhausted" | string;
  progress: number;
  payload: Record<string, unknown>;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  duration_ms?: number | null;
  error_type?: string | null;
  retry_count?: number;
  max_retries?: number;
  parent_task_id?: number | null;
  children?: TaskRecord[];
};

export type SchedulerStatus = {
  enabled: boolean;
  running: boolean;
  interval_seconds: number;
  jobs: Array<{
    id: string;
    next_run_time?: string | null;
  }>;
  recent_tasks: TaskRecord[];
};

export type RunDueTasksResponse = {
  executed_count: number;
  failed_count: number;
  items: PublishJob[];
};

export type MonitoringTarget = {
  id: number;
  platform: PlatformId;
  target_type: "keyword" | "account" | "brand" | "note_url" | string;
  name: string;
  value: string;
  status: "active" | "paused" | string;
  config: Record<string, unknown>;
  last_refreshed_at?: string | null;
  created_at: string;
  updated_at: string;
  /** The interval the scheduler actually honours. */
  crawl_interval_minutes?: number;
  consecutive_failures?: number;
  last_crawl_error?: string | null;
};

export type MonitoringTargetPayload = {
  target_type: "keyword" | "account" | "brand" | "note_url";
  name?: string;
  value: string;
  status?: "active" | "paused";
  config?: Record<string, unknown>;
};

export type MonitoringSnapshot = {
  id: number;
  target_id: number;
  payload: {
    matched_count?: number;
    total_engagement?: number;
    top_notes?: Array<{
      id: number;
      note_id: string;
      title: string;
      author_name: string;
      engagement: number;
      fans?: number;
      like_fan_ratio?: number;
    }>;
    low_fan_viral?: {
      thresholds?: { max_fans?: number; min_likes?: number; min_like_fan_ratio?: number };
      count?: number;
      top_notes?: Array<{
        id: number;
        note_id: string;
        title: string;
        author_name: string;
        fans: number;
        likes: number;
        like_fan_ratio: number;
        engagement: number;
      }>;
    };
  };
  created_at: string;
};

export type MonitoringNote = {
  id: number;
  note_id: string;
  title: string;
  author_name: string;
  author_id?: string;
  created_at: string;
  likes: number;
  collects: number;
  comments: number;
  shares: number;
  engagement: number;
  fans?: number;
  like_fan_ratio?: number;
  engagement_rate?: number;
};

export type MonitoringRefreshResponse = {
  target: MonitoringTarget;
  task: TaskRecord;
  snapshot: MonitoringSnapshot;
};

export type KeywordGroup = {
  id: number;
  platform: PlatformId;
  name: string;
  keywords: string[];
  created_at: string;
  updated_at: string;
};

export type KeywordGroupPayload = {
  platform?: PlatformId;
  name: string;
  keywords: string[];
};

export type KeywordGroupDetail = KeywordGroup & {
  trend: {
    total_matches: number;
    total_engagement: number;
    keywords: Array<{
      keyword: string;
      notes: number;
      engagement: number;
      previous_notes?: number | null;
      notes_delta?: number | null;
      engagement_delta?: number | null;
      trend?: "new" | "up" | "down" | "flat";
      last_seen?: string;
    }>;
    matched_notes: Array<{
      id: number;
      note_id: string;
      title: string;
      author_name: string;
      engagement: number;
      created_at: string;
    }>;
  };
};

export type PublishJob = {
  id: number;
  platform_account_id: number;
  source_draft_id?: number | null;
  platform: PlatformId;
  title: string;
  body: string;
  publish_mode: "immediate" | "scheduled" | string;
  publish_options?: PublishOptions;
  origin?: string;
  skill_version?: string;
  pillar?: string;
  experiment?: string;
  status: "pending" | "uploading" | "publishing" | "scheduled" | "published" | "failed" | "cancelled" | string;
  scheduled_at?: string | null;
  external_note_id: string;
  publish_error: string;
  published_at?: string | null;
  created_at: string;
};

export type PublishOptions = {
  topics?: string[];
  location?: string;
  privacy_type?: 0 | 1 | number;
  is_private?: boolean;
  draft_tags?: Array<string | { id?: string; name?: string }>;
};

export type SendDraftToPublishPayload = {
  platform_account_id?: number | null;
  publish_mode?: "immediate" | "scheduled";
  scheduled_at?: string | null;
  topics?: string[];
  location?: string | null;
  privacy_type?: 0 | 1 | null;
  is_private?: boolean | null;
};

export type PublishJobUpdatePayload = {
  title?: string;
  body?: string;
  platform_account_id?: number | null;
  publish_mode?: "immediate" | "scheduled";
  scheduled_at?: string | null;
  topics?: string[];
  location?: string | null;
  privacy_type?: 0 | 1 | null;
  is_private?: boolean | null;
};

export type PublishAsset = {
  id: number;
  publish_job_id: number;
  asset_type: "image" | "video" | string;
  file_path: string;
  upload_status: "pending" | "uploading" | "uploaded" | "failed" | string;
  creator_media_id: string;
  upload_error: string;
  creator_upload_info: Record<string, unknown>;
};

export type PublishAssetPayload = {
  asset_type: "image" | "video";
  file_path: string;
};

export type AutoTask = {
  id: number;
  user_id: number;
  name: string;
  keywords: string[];
  pc_account_id: number;
  creator_account_id: number;
  template_id?: number | null;
  ai_instruction: string;
  status: "active" | "paused" | "completed" | string;
  last_run_at?: string | null;
  next_run_at?: string | null;
  total_published: number;
  created_at: string;
  schedule_type: "manual" | "daily" | "weekly" | "interval";
  schedule_time: string;
  schedule_days: string;
  schedule_interval_hours: number;
};

export type AutoTaskCreatePayload = {
  name: string;
  keywords: string[];
  pc_account_id: number;
  creator_account_id: number;
  template_id?: number | null;
  ai_instruction?: string;
  schedule_type?: "manual" | "daily" | "weekly" | "interval";
  schedule_time?: string;
  schedule_days?: string;
  schedule_interval_hours?: number;
};

export type AutoTaskUpdatePayload = {
  name?: string;
  keywords?: string[];
  template_id?: number | null;
  ai_instruction?: string;
  status?: "active" | "paused" | "completed";
  schedule_type?: "manual" | "daily" | "weekly" | "interval";
  schedule_time?: string;
  schedule_days?: string;
  schedule_interval_hours?: number;
};

export type AutoTaskRunResult = {
  auto_task: AutoTask;
  keyword: string;
  source_note: {
    note_id: string;
    title: string;
    likes: number;
    collects: number;
    comments: number;
  };
  draft: {
    id: number;
    title: string;
    body: string;
    created_at: string;
  };
  publish_job: {
    id: number;
    status: string;
    platform_account_id: number;
    publish_mode: string;
  } | null;
  auto_publish: boolean;
};

export type AutoTaskRunStart = {
  task_id: number;
  status: string;
  auto_task: AutoTask;
};

export type AppNotification = {
  id: number;
  title: string;
  body: string;
  level: "info" | "warning" | "error" | string;
  source_task_id?: number | null;
  source_type?: string | null;
  source_id?: number | null;
  read: boolean;
  created_at: string;
};

export type ViralHookAnalysis = {
  title: string;
  title_length: number;
  emoji_count: number;
  emojis: string[];
  has_number: boolean;
  has_question: boolean;
  has_exclamation: boolean;
  is_list_format: boolean;
  has_identity_hook: boolean;
  has_emotion_word: boolean;
  has_contrast_hook: boolean;
  has_series_format: boolean;
  hook_patterns: string[];
};

export type ViralContentAnalysis = {
  body_length: number;
  paragraph_count: number;
  avg_paragraph_length: number;
  line_break_density: number;
  emoji_density: number;
  hashtag_count: number;
  hashtags: string[];
  has_call_to_action: boolean;
  bullet_or_list_usage: boolean;
};

export type ViralEngagementAnalysis = {
  likes: number;
  collects: number;
  comments: number;
  shares: number;
  total_engagement: number;
  comment_to_like_ratio: number;
  collect_to_like_ratio: number;
  share_to_like_ratio: number;
};

export type ViralCommentAnalysis = {
  total: number;
  question_count: number;
  question_examples: string[];
  pain_points: string[];
  sentiment: "positive" | "negative" | "neutral" | string;
  positive_mentions: number;
  negative_mentions: number;
  keywords: string[];
  top_comments: Array<{
    user_name: string;
    content: string;
    like_count: number;
  }>;
};

export type ViralAnalysisPayload = {
  generated_at: string;
  note: {
    note_id: string;
    title: string;
    author_name: string;
    author_id: string;
    author_fans: number;
    type: string;
    image_count: number;
  };
  hook: ViralHookAnalysis;
  content: ViralContentAnalysis;
  visual: {
    image_count: number;
    note_type: string;
  };
  engagement: ViralEngagementAnalysis;
  comments: ViralCommentAnalysis;
  baseline: {
    note_count?: number;
    avg_engagement?: number;
    avg_likes?: number;
    max_engagement?: number;
  };
  scoring: {
    score: number;
    level: "S" | "A" | "B" | "C" | "D" | string;
    components: Record<string, number>;
  };
  strengths: string[];
  suggestions: string[];
  summary: string;
  comments_error?: string;
};

export type ViralAnalysisResponse = {
  id: number | null;
  note_db_id: number;
  note_id: string;
  analysis: ViralAnalysisPayload;
  created_at: string | null;
};

export type ViralTemplatePayload = {
  generated_at: string;
  source_count: number;
  avg_score: number;
  kind?: string;
  documents?: number;
  opening?: Array<{ label: string; count: number; pct: number }>;
  body?: Array<{ label: string; count: number; pct: number }>;
  closing?: Array<{ label: string; count: number; pct: number }>;
  skeletons?: Array<{ label: string; count: number; pct: number }>;
  middle_elements?: Array<{ label: string; count: number; pct: number }>;
  common_hook_patterns: string[];
  title_formulas: string[];
  structure: string[];
  keywords: string[];
  hashtags: string[];
  cta_examples: string[];
  example_titles: string[];
  recommendations: string[];
  ai_guide?: string;
  ai_guide_model?: string;
  ai_guide_at?: string;
  note_summaries: Array<{
    note_id: string;
    title: string;
    score: number;
    level: string;
  }>;
};

export type ViralTemplate = {
  id: number;
  name: string;
  source_note_ids: number[];
  payload: ViralTemplatePayload;
  is_active?: boolean;
  created_at: string;
  updated_at: string;
  usage_count?: number;
  has_ai_guide?: boolean;
};

export type ViralTemplateListResponse = {
  items: ViralTemplate[];
  total: number;
};

export type CreationSkill = {
  id: number;
  platform: string;
  account_id: number | null;
  name: string;
  version: string;
  status: "active" | "draft" | "archived";
  content_md: string;
  structured_json: Record<string, unknown>;
  source: string;
  created_at: string;
  updated_at: string;
};

export type AccountReportNote = {
  note_id: string;
  title: string;
  note_url: string;
  likes: number;
  collects: number;
  comments: number;
  shares: number;
  engagement: number;
  publish_time: string;
};

export type AccountReportItem = {
  user_id: string;
  nickname: string;
  fans: number;
  follows?: number;
  total_notes: number;
  total_engagement: number;
  avg_engagement: number;
  avg_likes: number;
  total_likes: number;
  total_collects: number;
  total_comments: number;
  total_shares: number;
  engagement_rate: number;
  posting_months: Array<{ month: string; count: number }>;
  latest_publish_time: string;
  top_notes: AccountReportNote[];
  summary: string;
  diagnosis?: AccountDiagnosis;
  scorecard?: {
    total: number;
    grade: string;
    dimensions: Array<{ key: string; name: string; score: number; advice: string }>;
    suggestions: string[];
  };
  error?: string;
};

export type DiagnosisMetric = {
  key: string;
  label: string;
  value: number | null;
  unit: string;
  direction: "higher" | "lower";
  percentile: number | null;
};

export type DiagnosisGroup = {
  key: string;
  name: string;
  score: number;
  metrics: DiagnosisMetric[];
  advice: string;
};

export type AccountDiagnosis = {
  groups: DiagnosisGroup[];
  cohort_size: number;
  basis: "views" | "fans" | "none";
  has_views: boolean;
  summary: string;
  note: string;
};

export type NoteDiagnosis = {
  note_id: number;
  platform_note_id: string;
  title: string;
  metrics: {
    likes: number;
    collects: number;
    comments: number;
    shares: number;
    views: number;
    fans: number;
  };
  engagement: number;
  basis: "views" | "fans" | "none";
  proxy: boolean;
  rates: {
    engagement_rate: number;
    save_rate: number;
    comment_rate: number;
    share_rate: number;
  };
  relative: {
    baseline_engagement: number;
    multiple: number | null;
    percentile: number | null;
    collect_per_like: number;
    level: string;
    peer_count: number;
  };
  funnel: {
    stages: Array<{
      key: string;
      name: string;
      value: number | null;
      unit: string;
      percent: number | null;
      status: "ok" | "proxy" | "missing";
      hint: string;
    }>;
    bottleneck: string;
    missing: string[];
  };
  features: {
    title: string;
    title_length: number;
    title_patterns: string[];
    hook_words: string[];
    cta_types: string[];
    tags: string[];
    tag_count: number;
    format: string;
    structure: {
      paragraphs: number;
      char_count: number;
      length_bucket: string;
      has_list: boolean;
      has_number_heading: boolean;
      emoji_count: number;
    };
    publish_time: string;
    has_views: boolean;
  };
  suggestions: string[];
  data_quality: {
    has_views: boolean;
    has_snapshots: boolean;
    peer_count: number;
  };
};

export type AccountReportResponse = {
  generated_at: string;
  month: string | null;
  items: AccountReportItem[];
};

export type AccountReportRequest = {
  account_id: number;
  users: string[];
  month?: string | null;
  max_pages?: number;
};

