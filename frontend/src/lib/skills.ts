/**
 * skills.ts — Skill 中心 / 模板 / 蒸馏的取数层
 *
 * 为什么单独一层：
 *   后端的 Skill Library、语料集、证据蒸馏是三套端点，但界面上它们同属
 *   「能力」这一件事。页面只关心"有哪些能力、开没开、这次会注入哪几个"，
 *   不关心端点分组。集中在这里，页面就不会散落一堆路径字符串。
 *
 * 所有函数都打真实接口，不做假数据：
 *   - 没有 Skill 就是空列表，不塞示例；
 *   - 试跑失败原样透出后端 detail；
 *   - 蒸馏报告只展示后端真实返回的 coverage / verdict。
 */

import { del, get, patch, post } from "./api";

/* ============================================================
   Skill Library
   ============================================================ */

export interface SkillModule {
  key: string;
  label: string;
  feature?: string;
  description?: string;
  auto_injected?: boolean;
  count: number;
}

export interface SkillItem {
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
  updated_at: string;
  /** 账号级覆盖，只有带 account_id 查询时才有 */
  account_enabled?: boolean;
  priority?: number;
  has_account_override?: boolean;
}

export interface SkillLibrary {
  items: SkillItem[];
  modules: SkillModule[];
  total: number;
  account_id?: number | null;
}

export interface SkillDetail extends SkillItem {
  content_md: string;
}

export interface SkillRouteHit {
  id: number;
  slug: string;
  name: string;
  module: string;
  module_label: string;
  /** 已减掉「模块匹配 +2」的相关度，和 threshold 同一刻度 */
  score: number;
  /** 原始分（含模块加成），只用于排查 */
  raw_score?: number;
  reasons: string[];
  content_chars: number;
}

export interface SkillRouteResult {
  items: SkillRouteHit[];
  /** 命中门槛。点名模块时该模块自己用更低的门槛。 */
  threshold?: number;
  /** 点名模块时，其它模块的 Skill 仍要过这个门槛（且必须有触发短语）。 */
  cross_threshold?: number | null;
  /**
   * 没命中时最接近的几条。只有 items 为空时才有。
   * 只回一句「没命中」分不清是库空的、开关关了，还是说法不一样。
   */
  near_misses?: Array<Omit<SkillRouteHit, "content_chars">>;
  /**
   * 没命中但生成时仍会注入的那几条（模块内兜底）。
   *
   * `module_skill_text` 在路由 0 命中时会退回本模块自己的 Skill——静默丢掉
   * 整个模块比注入一条略不相关的更糟。预演不返回它们的话，界面说「0 个」
   * 而实际 prompt 里有 1 条，两套说法。
   */
  fallback_items?: Array<{
    id: number;
    slug: string;
    name: string;
    module: string;
    module_label: string;
    content_chars: number;
  }>;
  fallback_reason?: string;
  candidate_count: number;
  module: string;
  module_label: string;
}

export interface SkillGateStep {
  index: number;
  title: string;
  criterion: string;
  checkable: boolean;
  status: "passed" | "failed" | "unverifiable" | string;
  /** 模型有没有回报这一步（false = 压根没提，不是「说了没做到」） */
  reported?: boolean;
  reason: string;
  result: string;
}

export interface SkillGate {
  steps: SkillGateStep[];
  passed: number;
  failed: number;
  unverifiable: number;
  /** 模型没有回报的步骤数（已计入 failed） */
  not_reported?: number;
  completion: number;
  status: string;
}

export interface SkillTryResult {
  text: string;
  artifact: string;
  fields: unknown[];
  field_summary?: Record<string, number>;
  gate: SkillGate;
  open_questions: string[];
  skill: { slug: string; name: string; module: string; module_label: string };
  step_count: number;
}

export function loadSkillLibrary(accountId?: number): Promise<SkillLibrary> {
  const query = accountId ? `?account_id=${accountId}` : "";
  return get<SkillLibrary>(`/api/xhs/skill-library${query}`);
}

/** 详情必须单独取：列表接口默认不带 content_md */
export function loadSkillDetail(id: number): Promise<SkillDetail> {
  return get<SkillDetail>(`/api/xhs/skill-library/${id}`);
}

export function setSkillEnabled(id: number, enabled: boolean): Promise<SkillItem> {
  return patch<SkillItem>(`/api/xhs/skill-library/${id}`, { enabled });
}

/** 账号级开关与优先级：不动全局，只影响这一个账号 */
export function setAccountSkill(
  id: number,
  payload: { account_id: number; enabled?: boolean; priority?: number },
): Promise<SkillItem> {
  return patch<SkillItem>(`/api/xhs/skill-library/${id}/account`, payload);
}

/** 预演：这次任务会注入哪几个 Skill */
export function routeSkills(payload: {
  task: string;
  module?: string;
  limit?: number;
  account_id?: number;
}): Promise<SkillRouteResult> {
  return post<SkillRouteResult>("/api/xhs/skill-library/route", payload);
}

/**
 * 试跑：让后端按 Skill 自己的步骤清单跑一遍，并按完成标准打分。
 * 这不是"把 Skill 塞进提示词"，返回的 gate 是逐步骤核验结果。
 */
export function trySkill(payload: {
  task: string;
  module?: string;
  slug?: string;
  context?: string;
  account_id?: number;
}): Promise<SkillTryResult> {
  return post<SkillTryResult>("/api/xhs/skill-library/try", payload);
}

/** 导入 zip（每个目录一个 SKILL.md） */
export function importSkillPack(file: File): Promise<{
  created: number;
  updated: number;
  total: number;
  items: SkillItem[];
}> {
  const form = new FormData();
  form.append("file", file);
  return post("/api/xhs/skill-library/import", form);
}

/*
 * 三个「推给写稿宿主」的函数已经不再需要。
 *
 * 它们原来让常驻的 DeepSeek Harness 重新拉方法库 / 写法 / 结构模板。
 * 宿主退场后，写稿直连后端，提示词在请求时现拼，没有「推一次才生效」这一层。
 *
 * 保留同名的空实现，是因为调用点散在 StyleLibraryPanel / PositioningPanel /
 * Skills 三个页面里，逐个删是纯噪音。它们返回成功，界面上的 toast 仍然会说
 * 「已应用」——这是真的：后端那条 profile 的 status 已经改了，下次生成就读新的。
 */

/* ============================================================
   语料集（证据蒸馏的输入）
   ============================================================ */

/** 语料集的「形状」：它适合喂哪个产品。 */
export interface CorpusShape {
  authors: number;
  notes: number;
  single_author: boolean;
  /** 采到粉丝数的篇数。0 说明低粉筛选无从下手 */
  fans_measured: number;
  /** 同时满足低粉爆款三个阈值的篇数 */
  breakouts: number;
  /** 阈值的人话描述，界面直接显示，不自己拼 */
  rule: string;
}

export interface CorpusSet {
  id: number;
  name: string;
  kind: string;
  keyword: string;
  source_accounts: string[];
  status: string;
  note: string;
  total: number;
  collect: Record<string, number>;
  genres: Record<string, number>;
  roles: Record<string, number>;
  shape?: CorpusShape;
  updated_at: string | null;
}

export interface CorpusMember {
  id: number;
  note_id: string;
  note_db_id: number | null;
  collect_status: string;
  collect_error: string;
  genre: string;
  genre_label: string;
  role: string;
  role_reason: string;
  published_at: string | null;
  title: string;
  author_name: string;
  likes: number;
  collects: number;
  engagement: number;
}

export interface CorpusSetDetail {
  set: CorpusSet;
  items: CorpusMember[];
}

export interface CorpusMeta {
  kinds: string[];
  genres: Array<{ value: string; label: string }>;
  collect_statuses: string[];
  roles: string[];
  limits: { max_source_accounts: number; max_pages: number };
}

export function loadCorpusMeta(): Promise<CorpusMeta> {
  return get<CorpusMeta>("/api/xhs/corpus/meta");
}

export function loadCorpusSets(): Promise<{ items: CorpusSet[]; total: number }> {
  return get("/api/xhs/corpus");
}

export function loadCorpusSet(id: number): Promise<CorpusSetDetail> {
  return get<CorpusSetDetail>(`/api/xhs/corpus/${id}`);
}

export function createCorpusSet(payload: {
  name: string;
  kind: string;
  source_accounts?: string[];
  keyword?: string;
  platform_account_id?: number | null;
}): Promise<CorpusSet> {
  return post<CorpusSet>("/api/xhs/corpus", payload);
}

export function collectCorpusSet(
  id: number,
  maxPages: number,
): Promise<Record<string, unknown>> {
  return post(`/api/xhs/corpus/${id}/collect`, {
    max_pages: maxPages,
    save_to_library: true,
  });
}

/** 正文要逐篇取，后端按 3 篇/分钟限速，所以由前端分批催 */
export function collectCorpusBodies(
  id: number,
  limit: number,
): Promise<Record<string, unknown>> {
  return post(`/api/xhs/corpus/${id}/collect-bodies`, { limit });
}

export function assignCorpusRoles(id: number): Promise<Record<string, unknown>> {
  return post(`/api/xhs/corpus/${id}/assign-roles`, {});
}

export function labelAllCorpus(id: number, genre: string, confirm: boolean) {
  return post(`/api/xhs/corpus/${id}/label-all`, { genre, confirm });
}

/** 给单篇成员标体裁。改体裁会把已算出的 baseline/负例重置。 */
export function labelCorpusMember(
  set_id: number,
  member_id: number,
  genre: string,
): Promise<{ updated: number; set: CorpusSet }> {
  return post(`/api/xhs/corpus/${set_id}/label`, {
    member_ids: [member_id],
    genre,
  });
}

export interface AddCorpusMembersResult {
  added: number;
  pending_body: number;
  skipped_already_in_set: number;
  missing_note_ids: number[];
  set: CorpusSet;
}

/** 把素材库里已有的笔记加进语料集。正文够长的直接 ok，短的进 pending_body。 */
export function addCorpusMembers(
  set_id: number,
  note_ids: number[],
  genre?: string | null,
): Promise<AddCorpusMembersResult> {
  return post<AddCorpusMembersResult>(`/api/xhs/corpus/${set_id}/members`, {
    note_ids,
    genre: genre || null,
  });
}

/** 从语料集移出一条成员；笔记本身留在素材库。 */
export function removeCorpusMember(
  set_id: number,
  member_id: number,
): Promise<{ deleted: boolean; id: number }> {
  return del(`/api/xhs/corpus/${set_id}/members/${member_id}`);
}

/** 删除语料集：只删集合和成员关系，笔记留在素材库。 */
export function deleteCorpusSet(
  set_id: number,
): Promise<{ deleted: boolean; id: number }> {
  return del(`/api/xhs/corpus/${set_id}`);
}

/* ============================================================
   证据蒸馏
   ============================================================ */

export interface EvidenceItem {
  key: string;
  label?: string;
  rule?: string;
  verdict: string;
  /** 后端 style_hypotheses 的维度：结构 / 表达 / 证据 / 深度 / 节奏 / 收尾 / 人称 / 钩子 / 排版 */
  dimension?: string;
  coverage: number;
  support?: number;
  total?: number;
  genre_convention?: boolean;
  preference_status?: string;
  counter_rule?: string;
  reason?: string;
  counter_examples?: string[];
  examples?: string[];
  control_coverage?: number;
  control_p?: number;
  discovery_coverage?: number;
  confirmation_coverage?: number;
}

export interface EvidenceProfile {
  id: number;
  name: string;
  status: string;
  source: string;
  engine: string;
  works_count: number;
  char_count: number;
  created_at: string | null;
  summary: Record<string, number>;
  corpus: Record<string, unknown>;
  items: EvidenceItem[];
  thresholds: { hard?: number; tendency?: number };
  injectable_rules: string[];
  author_mix: Record<string, unknown>;
  corpus_warning: string;
  hypothesis_set: string;
  corpus_set_id?: number | null;
  genre_baseline: Record<string, unknown>;
  batch_plan: Record<string, unknown>;
  skill_md: string;
  injection_block: string;
}

export interface EvidenceMeta {
  hypotheses: Array<{
    key: string;
    claim: string;
    source: string;
    dimension: string;
    detector: string;
    rule: string;
    counter_rule: string;
    note: string;
    tags: string[];
  }>;
  thresholds: { hard: number; tendency: number };
  verdict_labels: Record<string, string>;
  min_documents: number;
}

export function loadEvidenceMeta(): Promise<EvidenceMeta> {
  return get<EvidenceMeta>("/api/xhs/evidence-distill/meta");
}

export function loadEvidenceProfiles(): Promise<{
  items: EvidenceProfile[];
  total: number;
}> {
  return get("/api/xhs/evidence-distill/profiles");
}

export function loadEvidenceProfile(id: number): Promise<EvidenceProfile> {
  return get<EvidenceProfile>(`/api/xhs/evidence-distill/profiles/${id}`);
}

export function runEvidenceDistill(payload: {
  set_id: number;
  name?: string;
  account_id?: number | null;
  genre?: string | null;
  control_set_id?: number | null;
  hypothesis_set?: string;
}): Promise<EvidenceProfile> {
  return post<EvidenceProfile>("/api/xhs/evidence-distill", payload);
}

export function deleteEvidenceProfile(id: number): Promise<unknown> {
  return del(`/api/xhs/evidence-distill/profiles/${id}`);
}

/**
 * 补采作者粉丝数。
 *
 * 后端一次只查 1–10 位作者（每个作者一次平台请求，间隔 1.2 秒，避免风控），
 * 所以这里按轮次推进：每轮拿到有多少作者被处理，全部返回 0 就停。
 *
 * 为什么需要它：低粉爆款判定必须先有粉丝数，而搜索列表里大多数作者是
 * `author_fans_status=unknown`。不补采，筛选结果永远是 0，用户会以为筛选坏了。
 */
export async function backfillAuthorFans(
  noteIds: number[],
  options: { rounds?: number; limit?: number; onProgress?: (done: number, total: number) => void } = {},
): Promise<{ authors: number; notes: number; failed: number; rounds: number }> {
  const maxRounds = options.rounds ?? 12;
  const limit = options.limit ?? 10;
  let authors = 0;
  let notes = 0;
  let failed = 0;
  let rounds = 0;

  for (let round = 0; round < maxRounds; round += 1) {
    const result = await post<{
      authors_checked: number;
      notes_updated: number;
      failed: number;
    }>("/api/notes/enrich-author-fans", { note_ids: noteIds, limit });
    authors += result.authors_checked ?? 0;
    notes += result.notes_updated ?? 0;
    failed += result.failed ?? 0;
    rounds += 1;
    options.onProgress?.(authors, noteIds.length);
    // Nothing left to check: every remaining author either has a count or no id.
    if (!result.authors_checked) break;
  }
  return { authors, notes, failed, rounds };
}

/* ============================================================
   结构模板（跨作者语料的正确出口）
   ============================================================ */

export interface StructureTemplateSelection {
  rule: string;
  max_fans?: number;
  min_likes?: number;
  min_like_fan_ratio?: number;
  within_days?: number | null;
  candidates: number;
  selected: number;
  excluded_unmeasured: number;
  excluded_by_rule: number;
}

export interface StructureTemplateSummary {
  id: number;
  name: string;
  source_note_ids: number[];
  payload: {
    kind?: string;
    documents?: number;
    structure?: string[];
    skeletons?: Array<{ label: string; count: number; pct: number }>;
    recommendations?: string[];
    selection?: StructureTemplateSelection;
    /** 生成它的语料集。老模板没有这个字段，界面要能降级。 */
    corpus?: { set_id: number; name: string; genre?: string | null };
    /** 模型精炼过的写作规范；有就说明这个模板被「精修」过 */
    ai_guide?: string;
  };
  is_active: boolean;
  /** 后端渲染好的提示词片段，写稿面直接用 */
  prompt_block?: string;
  /** 列表接口才有：被多少篇草稿引用过 */
  usage_count?: number;
  /** 列表接口才有：payload 里有没有 ai_guide */
  has_ai_guide?: boolean;
  created_at: string;
  updated_at: string;
}

export function loadStructureTemplates(): Promise<{
  items: StructureTemplateSummary[];
  total: number;
}> {
  return get("/api/xhs/insights/viral-templates?limit=100");
}

export function setStructureTemplateActive(
  id: number,
  isActive: boolean,
): Promise<StructureTemplateSummary> {
  return patch<StructureTemplateSummary>(
    `/api/xhs/insights/viral-templates/${id}`,
    { is_active: isActive },
  );
}

/**
 * 删除结构模板。
 *
 * 只删模板本身，不碰来源笔记和语料集——模板是从它们算出来的，不是它们的一部分。
 * 写稿面会立刻拿不到它（桥推模板时后端回 404，插件当没选）。
 */
export function deleteStructureTemplate(
  id: number,
): Promise<{ deleted: boolean; id: number }> {
  return del(`/api/xhs/insights/viral-templates/${id}`);
}

/**
 * 用文本模型把规则模板精炼成一段可复用的写作规范（存进 payload.ai_guide）。
 *
 * 为什么要这一步：模板算出来的是「开头 62% 是痛点句、中段 48% 是清单」这种
 * 分布数字。提示词里塞一堆百分比，模型并不真的照着写。精炼一遍是把这些
 * 数字翻译成「开头先认领一个具体场景，别从大道理起手」这种能执行的句子。
 *
 * 精炼是手动触发：它会花一次十几秒的模型调用，而且同一个模板不需要精炼两遍
 * （后端会覆盖 payload.ai_guide）。
 */
export function refineStructureTemplate(id: number): Promise<{
  id: number;
  ai_guide?: string;
  [key: string]: unknown;
}> {
  return post(`/api/xhs/insights/viral-templates/${id}/refine`, {});
}

/**
 * 从语料集生成结构模板。
 *
 * 默认 `selection: "low_follower"` —— 只测低粉爆款。传 `"all"` 会退回到
 * 「所有正文够长的都算」，那正是把 18 万赞和 2 赞平均在一起的老行为。
 */
export function createTemplateFromCorpus(payload: {
  set_id: number;
  name?: string;
  genre?: string | null;
  selection?: "low_follower" | "all";
  max_fans?: number;
  min_likes?: number;
  min_like_fan_ratio?: number;
  within_days?: number;
}): Promise<{ id: number; name: string; payload?: { selection?: StructureTemplateSelection } }> {
  return post("/api/xhs/insights/viral-templates/from-corpus", payload);
}

/* ============================================================
   基础风格（提炼产出的写法）
   ============================================================ */

export interface StyleProfile {
  id: number;
  name: string;
  status: string;
  source: string;
  builtin_key?: string;
  works_count: number;
  char_count: number;
  engine: string;
  created_at: string;
  summary?: {
    works?: number;
    chars?: number;
    positioning?: string;
    tone?: string;
    sample_titles?: string[];
    hooks?: Array<{ label: string; count: number }>;
  };
}

export function loadStyleProfiles(accountId?: number | null): Promise<{
  items: StyleProfile[];
  total: number;
}> {
  /*
   * `account_id` 不是过滤器，是「语境」。
   *
   * `apply` 按账号绑定。不传账号时列表里可能同时有 A、B 两个账号的 applied 行，
   * 前端取第一条当「当前生效」——写稿页顶部那句「这次会带上 XXX」就会是
   * 另一个账号的写法。传了就只剩「未绑定 + 本账号」，applied 必然唯一。
   */
  const qs = accountId ? `?account_id=${accountId}` : "";
  return get(`/api/xhs/style-distill${qs}`);
}

/* ============================================================
   图片模型（设置 → 模型 → 图片）
   ============================================================ */

export interface ModelConfigItem {
  id: number;
  name: string;
  model_type: "text" | "image" | string;
  provider: string;
  model_name: string;
  base_url: string;
  has_api_key: boolean;
  is_default: boolean;
}

export function loadModelConfigs(modelType?: "text" | "image"): Promise<{
  items: ModelConfigItem[];
  total: number;
}> {
  const query = modelType ? `?model_type=${modelType}` : "";
  return get(`/api/model-configs${query}`);
}

export function createModelConfig(payload: {
  name: string;
  model_type: "text" | "image";
  provider: string;
  model_name: string;
  base_url: string;
  api_key?: string;
  is_default?: boolean;
}): Promise<ModelConfigItem> {
  return post<ModelConfigItem>("/api/model-configs", payload);
}

export function setDefaultModelConfig(id: number): Promise<ModelConfigItem> {
  return post<ModelConfigItem>(`/api/model-configs/${id}/set-default`, {});
}

export function testModelConfig(id: number): Promise<{
  id: number;
  status: string;
  message: string;
  latency_ms?: number;
}> {
  return post(`/api/model-configs/${id}/test`, {});
}

export function deleteModelConfig(id: number): Promise<unknown> {
  return del(`/api/model-configs/${id}`);
}

/** 真实出一张图：图片模型唯一可信的验证方式 */
export function generateImage(payload: {
  prompt: string;
  size?: string;
  save_to_assets?: boolean;
  draft_id?: number | null;
}): Promise<{ url: string; raw?: Record<string, unknown>; asset?: unknown }> {
  return post("/api/ai/images/generate", {
    prompt: payload.prompt,
    size: payload.size ?? "1024x1024",
    save_to_assets: payload.save_to_assets ?? false,
    draft_id: payload.draft_id ?? null,
  });
}

export function describeImage(payload: {
  image_url: string;
  instruction?: string;
}): Promise<{ text: string }> {
  return post("/api/ai/images/describe", {
    image_url: payload.image_url,
    instruction: payload.instruction ?? "",
  });
}

/** 抖音转写环境：在 Skill 中心只做状态展示，不在这里跑任务 */
export interface DouyinMeta {
  asr_ready: boolean;
  engine: string;
  hint: string;
  ffmpeg: boolean;
  ffprobe: boolean;
  ffmpeg_path?: string;
  ffprobe_path?: string;
  model_size?: string;
  device_plan?: string[];
  source_types?: string[];
}

export function loadDouyinMeta(): Promise<DouyinMeta> {
  return get<DouyinMeta>("/api/douyin/extract/meta");
}
