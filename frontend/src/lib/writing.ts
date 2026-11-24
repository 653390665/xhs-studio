/**
 * writing.ts — 写稿页的取数与动作
 *
 * 为什么单独一层：写稿页要同时碰五种东西（草稿、对话、批次、标题/标签生成、
 * 自检），每个都直接写 `get(...)` 的话，字段名和返回形状会散在 JSX 里。
 * 尤其 `_serialize_draft` 在后端有两个实现（`api/ai.py` 与 `api/drafts.py`），
 * 一旦哪边多一个字段，页面里就会静默读到 undefined —— 把形状写在这里，
 * 至少只有一处需要核对。
 *
 * 后端契约（实测，2026-11 阶段 1 补口后）：
 *   GET    /api/drafts?account_id=     列表（带 image_count / asset_count）
 *   GET    /api/drafts/{id}            单篇（带 batch_id / context）
 *   POST   /api/ai/generate-note       生成（返回草稿 + task_id + duration_ms）
 *   POST   /api/ai/draft-chat          改稿（返回 reply / patch / changes / score）
 *   GET    /api/ai/draft-chat/{id}     对话历史（服务端持久化，刷新不丢）
 *   POST   /api/ai/draft-chat/apply    应用某一轮的 patch
 *   POST   /api/ai/generate-title      一次给 count 个标题
 *   POST   /api/ai/generate-tags       一次给 count 个标签
 *   GET    /api/drafts/{id}/preflight  发布前自检
 */

import { del, get, patch, post, unwrapList } from "./api";

/* ============================================================
   形状
   ============================================================ */

export interface Draft {
  id: number;
  platform: string;
  platform_account_id?: number | null;
  title: string;
  body: string;
  tags: string[];
  origin: string;
  review_status: string;
  skill_version: string;
  batch_id?: number | null;
  /** 生成时冻结的上下文：写法名、模板、批次、勾选的 Skill */
  context?: Record<string, unknown>;
  created_at: string;
  /** 列表接口才带 */
  image_count?: number;
  asset_count?: number;
  media_ready?: boolean;
  account_ready?: boolean;
}

export interface ChatMessage {
  id: number;
  draft_id: number;
  role: "user" | "assistant";
  content: string;
  /** 助手这一轮建议改哪些字段 */
  patch?: { title?: string; body?: string; tags?: string[] } | null;
  /** 技能评分（后端 skill_score_service），没有配置写法时为 null */
  score?: DraftScore | null;
  created_at: string;
}

export interface DraftScore {
  total?: number;
  grade?: string;
  summary?: string;
  suggestions?: string[];
  dimensions?: Array<{ key?: string; label?: string; score?: number; max?: number }>;
  format_label?: string;
}

export interface Batch {
  id: number;
  name: string;
  kinds: string[];
  meta?: Record<string, unknown>;
  updated_at?: string | null;
  items?: Array<{ kind: string; title: string; chars: number }>;
}

export interface ChatResult {
  reply: string;
  patch?: { title?: string; body?: string; tags?: string[] } | null;
  changes: string[];
  score?: DraftScore | null;
  user_message_id: number;
  assistant_message_id: number;
}

export interface Generated {
  draft: Draft;
  /** 后端测的真实耗时（毫秒），不是浏览器秒表 */
  duration_ms?: number;
  task_id?: number;
}

/* ============================================================
   草稿
   ============================================================ */

/**
 * 标签在后端有两种形状：`["成长", "复盘"]` 和 `[{id, name}]`。
 * 二十来篇老草稿是后者。页面里每个地方各自 `typeof === "string"` 判断的话，
 * 迟早漏一处，显示成 "[object Object]"。
 */
export function tagNames(tags: unknown): string[] {
  if (!Array.isArray(tags)) return [];
  return tags
    .map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object") {
        const name = (item as { name?: unknown }).name;
        if (typeof name === "string") return name;
      }
      return "";
    })
    .map((name) => name.replace(/^#/, "").trim())
    .filter(Boolean);
}

export function listDrafts(options: {
  accountId?: number | null;
  pageSize?: number;
} = {}): Promise<Draft[]> {
  const params = new URLSearchParams({ page: "1", page_size: String(options.pageSize ?? 100) });
  // 只在真的选了账号时才过滤：null / 0 都表示「这台机器上全部草稿」
  if (options.accountId) params.set("account_id", String(options.accountId));
  return get(`/api/drafts?${params.toString()}`).then((r) => unwrapList<Draft>(r).items);
}

/**
 * 单篇读取。
 *
 * 现在列表里已经带全了字段，页面用不到它；保留是因为「深链打开一篇不在前
 * 100 条里的草稿」迟早要做，而 writing.ts 是这层的唯一出口。
 */
export function loadDraft(draftId: number): Promise<Draft> {
  return get<Draft>(`/api/drafts/${draftId}`);
}

export function saveDraft(
  draftId: number,
  payload: {
    title?: string;
    body?: string;
    tags?: string[];
    /** 0 = 取消关联；正数是模板 id */
    templateId?: number;
  },
  /** 页面卸载时保存：带 keepalive，浏览器不会因为关标签页就丢掉请求 */
  options?: { keepalive?: boolean },
): Promise<Draft> {
  const body: Record<string, unknown> = {};
  if (payload.title !== undefined) body.title = payload.title;
  if (payload.body !== undefined) body.body = payload.body;
  if (payload.tags !== undefined) body.tags = payload.tags;
  // 后端用 0 表示「取消关联」，不能用 null（那会被当成「没传」）
  if (payload.templateId !== undefined) body.template_id = payload.templateId;
  return patch<Draft>(`/api/drafts/${draftId}`, body, options);
}

export function deleteDraft(draftId: number): Promise<unknown> {
  return del(`/api/drafts/${draftId}`);
}

/**
 * 采用 / 弃用。
 *
 * 后端 `PATCH /api/drafts/{id}/review` 一直存在，前端零调用——41 篇迁过来的
 * 草稿全是 `pending`，用户分不清哪篇是要发的、哪篇是废稿。
 *
 * `pending` 不是"待审核"的意思，是"还没表态"：不表态也能发，只是列表里
 * 没有区分度。
 */
export function reviewDraft(
  draftId: number,
  reviewStatus: "pending" | "adopted" | "discarded",
): Promise<Draft> {
  return patch<Draft>(`/api/drafts/${draftId}/review`, {
    review_status: reviewStatus,
  });
}

/* ============================================================
   生成
   ============================================================ */

export interface GenerateInput {
  topic: string;
  accountId?: number | null;
  batchId?: number | null;
  /** undefined = 让后端按任务自动路由；给了数组 = 只注入这几篇 */
  skillIds?: number[] | null;
  instruction?: string;
  templateId?: number | null;
}

export function generateNote(input: GenerateInput): Promise<Generated> {
  return post<Draft>("/api/ai/generate-note", {
    topic: input.topic.trim(),
    // 平台目前只有小红书是启用的；抖音上线前不留一个假的 platform 参数
    platform: "xhs",
    account_id: input.accountId ?? null,
    batch_id: input.batchId ?? null,
    // 传 null（而不是省略）会被后端当成显式空列表，所以只在真的有勾选时带上
    ...(input.skillIds && input.skillIds.length > 0 ? { skill_ids: input.skillIds } : {}),
    instruction: input.instruction ?? "",
    template_id: input.templateId ?? null,
  }).then((draft) => ({
    draft,
    duration_ms: (draft as unknown as { duration_ms?: number }).duration_ms,
    task_id: (draft as unknown as { task_id?: number }).task_id,
  }));
}

/* ============================================================
   对话
   ============================================================ */

export function loadChat(draftId: number): Promise<ChatMessage[]> {
  return get(`/api/ai/draft-chat/${draftId}`).then(
    (r) => unwrapList<ChatMessage>(r).items,
  );
}

export function sendChat(payload: {
  draftId: number;
  message: string;
  batchId?: number | null;
  skillIds?: number[] | null;
}): Promise<ChatResult> {
  return post<ChatResult>("/api/ai/draft-chat", {
    draft_id: payload.draftId,
    message: payload.message,
    // 历史由后端从库里读，前端不再回传——两个来源都传会让模型看到重复的轮次
    history: [],
    batch_id: payload.batchId ?? null,
    ...(payload.skillIds && payload.skillIds.length > 0 ? { skill_ids: payload.skillIds } : {}),
  });
}

export function applyChatPatch(payload: {
  draftId: number;
  messageId: number;
}): Promise<{ draft: Draft; score?: DraftScore | null }> {
  return post("/api/ai/draft-chat/apply", {
    draft_id: payload.draftId,
    message_id: payload.messageId,
  });
}

/* ============================================================
   局部重写：标题 / 标签
   ============================================================ */

/**
 * 模型偶尔会把提示词里的「标题公式」当成一个候选标题返回。
 *
 * 实测（deepseek-flash，5 次里 1 次）：第一条是「暂定标题公式」这种
 * 指令回显，后面四条才是真标题。它不是错误，只是小模型把 system prompt
 * 里的字抄了一行；直接显示会让人第一眼看到一条不能用的东西。
 *
 * 判定写得很窄：只丢「短且含『公式/规则/暂定』」那种，真实标题里
 * 出现这些词的情况极少，误伤代价也只是一条候选少一个。
 */
function isInstructionEcho(text: string): boolean {
  const t = text.trim();
  if (!t) return true;
  return t.length <= 10 && /公式|规则|暂定|示例|如下/.test(t);
}

export function generateTitles(payload: {
  title: string;
  body: string;
  count?: number;
  accountId?: number | null;
}): Promise<string[]> {
  return post<{ items: string[] }>("/api/ai/generate-title", {
    title: payload.title,
    body: payload.body,
    count: payload.count ?? 5,
    account_id: payload.accountId ?? null,
  }).then((r) => (r.items ?? []).filter((item) => !isInstructionEcho(item)));
}

export function generateTags(payload: {
  title: string;
  body: string;
  count?: number;
  accountId?: number | null;
}): Promise<string[]> {
  return post<{ items: string[] }>("/api/ai/generate-tags", {
    title: payload.title,
    body: payload.body,
    count: payload.count ?? 8,
    account_id: payload.accountId ?? null,
  }).then((r) => r.items ?? []);
}

/* ============================================================
   账号
   ============================================================ */

export interface WritingAccount {
  id: number;
  nickname?: string;
  platform?: string;
  status?: string;
  healthy?: boolean;
}

export function listAccounts(): Promise<WritingAccount[]> {
  return get("/api/accounts").then(
    (r) => unwrapList<WritingAccount>(r).items.filter((a) => (a.platform ?? "xhs") === "xhs"),
  );
}

/* ============================================================
   提炼批次
   ============================================================ */

export function listBatches(): Promise<Batch[]> {
  return get(`/api/xhs/distill-batches?limit=50`).then(
    (r) => unwrapList<Batch>(r).items,
  );
}

/**
 * 把工作台的四份模板存进后端。
 *
 * 为什么必须做这一步（2026-11-14 查出来的断链）：
 *   工作台的产物一直只写在 `localStorage["xhs.studio.results.<id>"]`，
 *   而写稿页的「素材」下拉读的是 `GET /api/xhs/distill-batches`。
 *   前端全库只有那一处 GET，**没有任何地方 POST**——于是提炼十次，
 *   写稿页的下拉永远是空的，还提示「还没有提炼批次，去提炼一次」。
 *
 * `batchId` 传工作台的 profileId（字符串）。后端按 `meta.client_id` 幂等：
 * 同一批再存是更新同一行，不会堆重复。
 */
export function upsertBatch(payload: {
  clientId: string;
  name: string;
  /** 四类模板；空正文的会跳过，不用调用方过滤 */
  items: Array<{ kind: string; title?: string; body: string }>;
  meta?: Record<string, unknown>;
}): Promise<Batch> {
  const items = payload.items
    .filter((item) => (item.body ?? "").trim().length > 0)
    .map((item) => ({
      kind: item.kind,
      title: item.title ?? "",
      body: item.body,
    }));
  return post<Batch>("/api/xhs/distill-batches", {
    batch_id: payload.clientId,
    name: payload.name,
    items,
    ...(payload.meta ? { meta: payload.meta } : {}),
  });
}

/* ============================================================
   送发布
   ============================================================ */

export interface PublishJobLite {
  id: number;
  status?: string;
  source_draft_id?: number | null;
}

/**
 * 把一篇草稿送进发布队列。
 *
 * 后端的 `send-to-publish` 一直存在，前端**零调用**——所以「发布」板块
 * 永远是空的，用户自检通过之后没有任何按钮能把稿子送出去，只能看到
 * 「还没有要发的稿子」。
 *
 * `publish_mode: "immediate"` 表示「现在排进队列」，不等于「已发布」：
 * 队列里每一条仍然要人点确认。这是发布链路的既有约束。
 */
export function sendToPublish(payload: {
  draftId: number;
  accountId: number;
  scheduledAt?: string | null;
}): Promise<PublishJobLite> {
  return post<PublishJobLite>(`/api/drafts/${payload.draftId}/send-to-publish`, {
    platform_account_id: payload.accountId,
    publish_mode: payload.scheduledAt ? "scheduled" : "immediate",
    ...(payload.scheduledAt ? { scheduled_at: payload.scheduledAt } : {}),
  });
}

/* ============================================================
   自检
   ============================================================ */

export interface PreflightCheck {
  key: string;
  label: string;
  level: "ok" | "warning" | "error";
  message: string;
}

export interface PreflightResult {
  ok: boolean;
  error_count: number;
  warning_count: number;
  checks: PreflightCheck[];
  summary: string;
}

export function preflightDraft(draftId: number): Promise<PreflightResult> {
  return get<PreflightResult>(`/api/drafts/${draftId}/preflight`);
}
