/**
 * styleLibrary.ts — 写法管理（所有 StyleProfile 的统一入口）
 *
 * 为什么要有这一层：
 *   后端只有一个"写法"概念（StyleProfile），来源有五种：
 *     内置（ego）/ 样本提炼 / 证据蒸馏 / 抖音蒸馏 / 试跑产物
 *   它们都能 apply，apply 后写稿和后端生成都会读。
 *
 *   但新前端一直只看得到其中一部分：
 *     · 提炼页只看 from-library 的产物
 *     · 蒸馏页只看 engine=evidence 的
 *     · 内置 ego 在数据库里，界面上没有任何入口
 *
 *   这里把它们统一列出来，标清来源，动作统一为「应用 / 取消应用 / 删除」。
 */

import { del, get, post } from "./api";

export type StyleSource = "builtin" | "style_workflow" | "evidence" | "library" | "douyin" | string;

export interface StyleProfileSummary {
  id: number;
  name: string;
  status: string;
  source: string;
  engine: string;
  works_count: number;
  /** 老字段，不同来源含义不同（语料长度 / 正文长度），显示请用 promptChars */
  char_count: number;
  /** 模型实际会读到的正文长度 */
  prompt_chars?: number;
  /** 蒸馏型才有：语料总量 */
  corpus_chars?: number;
  created_at: string;
  updated_at?: string;
  account_id?: number | null;
  builtin_key?: string | null;
  /** 蒸馏时的语料标签，同一批素材会完全相同 */
  corpus_label?: string;
  /** 加料指纹；同指纹 = 同一批素材反复蒸出来的兄弟版本 */
  input_fingerprint?: string;
  distill_revision?: number;
  summary?: {
    positioning?: string;
    tone?: string;
  };
}

export interface StyleProfileDetail extends StyleProfileSummary {
  skill_md?: string;
  profile?: Record<string, unknown>;
}

/** 来源的中文标签。认不出来的原样显示，不硬猜成"未知"。 */
export function sourceLabel(source: string): string {
  switch (source) {
    case "builtin":
      return "内置";
    case "skill_workflow":
      return "Skill 试跑";
    case "evidence_distill":
      return "证据蒸馏";
    case "library":
      return "样本提炼";
    case "distill":
      return "抖音蒸馏";
    case "data_evolution":
      return "数据进化";
    /*
     * 下面三个是旧前端用过的写法，后端从来没产生过（`styleLibrary.ts` 原来只认
     * 它们）。留在这里不是猜，是让历史浏览器缓存里的旧值也能显示成中文，
     * 而不是掉进 default 分支露出一串英文 source。
     */
    case "style_workflow":
      return "Skill 试跑";
    case "evidence":
      return "证据蒸馏";
    case "douyin":
      return "抖音蒸馏";
    default:
      return source || "未标注";
  }
}

/** 这份写法能不能在工作台里改正文。证据型和内置型都不能。 */
export function isEditableProfile(p: Pick<StyleProfileSummary, "source" | "engine" | "status">): boolean {
  if (p.source === "builtin") return false;
  if (p.engine === "evidence" || p.source === "evidence_distill") return false;
  return true;
}

/**
 * 界面上该显示的「字数」。
 *
 * 后端 ``char_count`` 在不同来源里含义不同：library/distill 写的是语料总量，
 * evidence/builtin/编辑后写的是正文长度。活库实测 id=3：char_count 4782，
 * 正文只有 976。直接显示会让人拿语料量去比较文档量。
 *
 * ``prompt_chars`` 是后端新增的、语义固定的字段（模型会读到的正文长度）。
 * 老响应没有它时回落到 ``char_count``，保持兼容。
 */
export function displayChars(p: Pick<StyleProfileSummary, "char_count" | "prompt_chars">): number {
  return p.prompt_chars ?? p.char_count;
}

/**
 * 列出写法。
 *
 * ``accountId`` 可选：传了就只要「这台机器上的 + 该账号的」。不传返回全部
 * （写法管理页要看到所有资产）。多账号时前端靠 `status === "applied"` 判断
 * 「当前生效」，列表不按账号过滤就会把另一个账号的写法显示成自己的。
 */
export function loadStyleProfiles(
  limit = 100,
  accountId?: number | null,
): Promise<{
  items: StyleProfileSummary[];
  total: number;
}> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (accountId) params.set("account_id", String(accountId));
  return get(`/api/xhs/style-distill?${params.toString()}`);
}

/** 只有这条接口会带 skill_md */
export function loadStyleDetail(id: number): Promise<StyleProfileDetail> {
  return get<StyleProfileDetail>(`/api/xhs/style-distill/${id}`);
}

export function applyStyle(
  id: number,
  accountId: number,
): Promise<{ profile?: StyleProfileDetail; message?: string }> {
  return post(`/api/xhs/style-distill/${id}/apply`, { account_id: accountId });
}

export function unapplyStyle(
  id: number,
  accountId: number,
): Promise<{ profile?: StyleProfileDetail; message?: string }> {
  return post(`/api/xhs/style-distill/${id}/unapply`, { account_id: accountId });
}

export function deleteStyle(id: number): Promise<unknown> {
  return del(`/api/xhs/style-distill/${id}`);
}

/* ============================================================
   分组：同一批素材反复蒸出来的写法只占一行
   ============================================================ */

export interface StyleGroup {
  /** 稳定的分组键：素材来源（去掉括号里的篇数/体裁等一次性描述） */
  key: string;
  /** 默认展示的那一份 */
  leader: StyleProfileSummary;
  /** 全组，含 leader，按展示顺序排好 */
  versions: StyleProfileSummary[];
  /** 组里有没有生效中的那份 */
  hasApplied: boolean;
}

/** 「历史」标记的来源：改名脚本写进名字里的，不是从状态推的。 */
function isHistorical(p: StyleProfileSummary): boolean {
  return p.name.includes("历史");
}

/**
 * 把「一勾Ego · 单作者语料（154 篇）（account，147 篇可用）」收成
 * 「一勾Ego · 单作者语料」。
 *
 * 括号里是会变的东西：篇数、可用篇数、体裁、是不是 account 语料。
 * 用整串当分组键，等于「同一批素材多蒸一次就换一组」——正是这次要收的乱。
 */
function baseCorpusLabel(label: string): string {
  let text = label.trim();
  let previous = "";
  while (text !== previous) {
    previous = text;
    text = text.replace(/\s*[（(][^（()）]*[)）]\s*$/, "").trim();
  }
  return text;
}

function groupKey(p: StyleProfileSummary): string {
  if (p.builtin_key) return `builtin:${p.builtin_key}`;
  const base = baseCorpusLabel(p.corpus_label ?? "");
  if (base) return `corpus:${base}`;
  if (p.input_fingerprint) return `fp:${p.input_fingerprint}`;
  return `solo:${p.id}`;
}

/**
 * 同一批素材只占一行。
 *
 * 以前 23 份写法一字排开：7/8/11 是同一批 Ego 语料蒸了三次，9/10/12/13/16/20
 * 都出自 AI产品阿豪，用户根本分不清哪份是当前该用的。
 *
 * 组内排序：生效中 → 非历史 → 素材多 → id 小（更早的那份通常是主版本，
 * 后面带「修正 / 假设集 / 回归」的多半是一次性实验）。
 */
export function groupStyleProfiles(items: StyleProfileSummary[]): StyleGroup[] {
  const buckets = new Map<string, StyleProfileSummary[]>();
  for (const p of items) {
    const key = groupKey(p);
    const bucket = buckets.get(key);
    if (bucket) bucket.push(p);
    else buckets.set(key, [p]);
  }

  const rank = (p: StyleProfileSummary): number[] => [
    p.status === "applied" ? 0 : 1,
    isHistorical(p) ? 1 : 0,
    -(p.works_count ?? 0),
    p.id,
  ];
  const compare = (a: StyleProfileSummary, b: StyleProfileSummary): number => {
    const ra = rank(a);
    const rb = rank(b);
    for (let i = 0; i < ra.length; i += 1) {
      if (ra[i] !== rb[i]) return ra[i] - rb[i];
    }
    return 0;
  };

  const groups: StyleGroup[] = [];
  for (const [key, bucket] of buckets) {
    const versions = [...bucket].sort(compare);
    groups.push({
      key,
      leader: versions[0],
      versions,
      hasApplied: versions.some((p) => p.status === "applied"),
    });
  }
  /* 组之间：有生效写法的组在最前，其余按组内最佳那份的新旧排 */
  return groups.sort((a, b) => {
    const byApplied = Number(b.hasApplied) - Number(a.hasApplied);
    if (byApplied !== 0) return byApplied;
    return b.leader.id - a.leader.id;
  });
}

/* ============================================================
   把一份 skill_md 拆回四类模板
   ============================================================ */

export type StyleSectionKind = "full" | "title" | "hook" | "image";

const SECTION_RULES: Array<{ kind: StyleSectionKind; hit: RegExp }> = [
  { kind: "title", hit: /标题|题目|title/i },
  { kind: "hook", hit: /开头|钩子|hook|opening/i },
  { kind: "image", hit: /配图|封面|视觉|图卡|image|visual/i },
];

/**
 * 按二级标题拆段，再按关键词归到四类。
 *
 * 为什么用关键词而不是固定序号：
 *   后端三条生产路径的小节编号不一样——
 *   样本提炼是「## 2. 标题公式 / ## 6. 开头钩子 / ## 7. 正文结构」，
 *   证据蒸馏是「## 硬规则 / ## 倾向 / ## 系材惯例」，
 *   内置 ego 是「## 1. 主 Skill / ## 2. 定位与读者 …」。
 *   按编号拆必然错位，按标题词更稳。
 *
 * 认不出来的段落一律并进「整篇」，宁可多，不可丢。
 */
export function splitSkillMd(md: string): Partial<Record<StyleSectionKind, string>> {
  const text = (md || "").replace(/\r\n/g, "\n").trim();
  if (!text) return {};

  /* 先按二级标题切；第一段（可能是 H1 + 引言）单独留着 */
  const chunks: Array<{ heading: string; body: string }> = [];
  let heading = "";
  let buffer: string[] = [];

  const flush = () => {
    if (heading || buffer.some((line) => line.trim())) {
      chunks.push({ heading, body: buffer.join("\n").trim() });
    }
    buffer = [];
  };

  for (const line of text.split("\n")) {
    if (/^##\s+/.test(line)) {
      flush();
      heading = line.replace(/^##\s+/, "").trim();
      continue;
    }
    buffer.push(line);
  }
  flush();

  const out: Partial<Record<StyleSectionKind, string>> = {};
  const leftovers: string[] = [];
  const seen = new Set<StyleSectionKind>();

  for (const chunk of chunks) {
    if (!chunk.heading) {
      /* H1 和引言：并进整篇，保留来源说明 */
      if (chunk.body.trim()) leftovers.push(chunk.body);
      continue;
    }
    const rule = SECTION_RULES.find((r) => r.hit.test(chunk.heading));
    /* 同一种只取第一段：后面重复出现的小节并进整篇，不覆盖前面的 */
    if (rule && !seen.has(rule.kind)) {
      seen.add(rule.kind);
      out[rule.kind] = `## ${chunk.heading}\n\n${chunk.body}`.trim();
    } else {
      leftovers.push(`## ${chunk.heading}\n\n${chunk.body}`.trim());
    }
  }

  if (leftovers.length > 0) out.full = leftovers.join("\n\n");
  return out;
}
