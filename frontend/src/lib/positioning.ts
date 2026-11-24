/**
 * positioning.ts — 账号定位（后端唯一一份，绑定账号）
 *
 * 为什么单独一层：
 *   账号定位是「人决定的事」，不是从语料统计出来的。
 *   后端把它放在 /api/xhs/account-positioning，和风格蒸馏分开：
 *   一个有 4 篇笔记的账号可以先有定位、还没有风格。
 *
 * 注入范围（后端 account_positioning_service.py）：
 *   进提示词：positioning / audience / main_topics / taboos / language_samples
 *   不进提示词：promise（内容承诺，属于经营决策，不写给模型当写作约束）
 *
 * /prompt-block 返回的就是真实注入文本，页面直接展示，不另写一份说明。
 */

import { get, post, put } from "./api";

export interface Positioning {
  account_id: number | null;
  positioning: string;
  audience: string;
  promise: string;
  main_topics: string[];
  taboos: string[];
  language_samples: string[];
  source: string;
  missing?: string[];
  is_empty?: boolean;
  updated_at?: string | null;
}

export interface PositioningPatch {
  positioning?: string;
  audience?: string;
  promise?: string;
  main_topics?: string[] | string;
  taboos?: string[] | string;
  language_samples?: string[] | string;
}

export function loadPositioning(accountId?: number): Promise<Positioning> {
  const query = accountId ? `?account_id=${accountId}` : "";
  return get<Positioning>(`/api/xhs/account-positioning${query}`);
}

export function savePositioning(
  patch: PositioningPatch,
  accountId?: number,
): Promise<Positioning> {
  const query = accountId ? `?account_id=${accountId}` : "";
  return put<Positioning>(`/api/xhs/account-positioning${query}`, patch);
}

export function loadPositioningPrompt(accountId?: number): Promise<{
  account_id: number | null;
  prompt_block: string;
  chars: number;
}> {
  const query = accountId ? `?account_id=${accountId}` : "";
  return get(`/api/xhs/account-positioning/prompt-block${query}`);
}

/**
 * 用已有素材起草一份定位（不落库）。
 *
 * 定位页是六个空框，而「账号定位」是写稿时唯一一直生效的「我是谁」。
 * 用户不填，之后每一篇稿都只能按通用模型写。但这件事不该靠凭空想——
 * 库里已有样本、有写法统计，足够起草一份能改的初稿。
 *
 * 返回的是草稿：只填进输入框，用户改完点保存才落库。
 * 自动写进库里会造成「我没填但系统帮我填了」的不信任。
 */
export function draftPositioning(accountId?: number): Promise<{
  account_id: number;
  source_notes: number;
  draft: PositioningPatch;
}> {
  return post("/api/xhs/account-positioning/draft", {
    account_id: accountId ?? null,
  });
}

/* ============================================================
   引导式起草（persona Skill 两轮）
   ============================================================ */

/** 每个字段的来源：用户说了 / 从笔记推断 / 两处都没有 */
export type FieldSource = "asked" | "inferred" | "unknown";

export interface GuideResult {
  account_id: number;
  /** 六字段是否都已足够确定（true 时 questions 为空） */
  ready: boolean;
  /** 空白账号模式下恒为 0：不读笔记 */
  note_count: number;
  /** 这次问到第几步 / 一共几步（按方法论顺序） */
  step_index?: number;
  step_total?: number;
  /** 本次有没有用上 persona Skill（没启用时界面上要说明） */
  skill_used: boolean;
  /** 只有本人能回答的问题 */
  questions: string[];
  draft: PositioningPatch;
  sources: Record<string, FieldSource>;
  note: string;
}

/**
 * 引导式起草。
 *
 * 第一轮（不带 answers）拿「只有你能回答的问题」；
 * 第二轮（带 answers）把答案和笔记一起交给 Skill，出完整草案。
 *
 * 和 `draftPositioning` 的区别：那个一次猜完，分不清哪句是用户说的；
 * 这个按《变现倒推定位》先问可售卖资产 / 变现路径 / 禁区，再反推定位，
 * 并且逐字段标注来源。
 */
export function guidePositioning(
  accountId: number | undefined,
  answers?: Record<string, string>,
  noteIds?: number[],
): Promise<GuideResult> {
  return post("/api/xhs/account-positioning/guide", {
    account_id: accountId ?? null,
    answers: answers && Object.keys(answers).length > 0 ? answers : null,
    note_ids: noteIds && noteIds.length > 0 ? noteIds : null,
  });
}

/** 确认之后把草案写进定位表。只写传进来的字段。 */
export function applyPositioningDraft(
  draft: PositioningPatch,
  accountId?: number,
  source = "skill_guide",
): Promise<Positioning> {
  const query = accountId ? `?account_id=${accountId}` : "";
  return post<Positioning>(`/api/xhs/account-positioning/apply-draft${query}`, {
    account_id: accountId ?? null,
    draft,
    source,
  });
}

/** 字段标签，和后端 _FIELD_LABELS 保持一致 */export const POSITIONING_FIELDS: Array<{
  key: keyof PositioningPatch;
  label: string;
  hint: string;
  kind: "text" | "list";
  injected: boolean;
}> = [  {
    key: "positioning",
    label: "一句话定位",
    hint: "我帮谁、在什么场景下、解决什么问题、为什么是我",
    kind: "text",
    injected: true,
  },
  {
    key: "audience",
    label: "目标用户",
    hint: "越具体越好：职业、阶段、正在卡住的事",
    kind: "text",
    injected: true,
  },
  {
    key: "promise",
    label: "内容承诺",
    hint: "关注我能稳定得到什么。只给人看，不写进提示词",
    kind: "text",
    injected: false,
  },
  {
    key: "main_topics",
    label: "内容支柱",
    hint: "一行一个，最多 8 个会进提示词",
    kind: "list",
    injected: true,
  },
  {
    key: "taboos",
    label: "禁区",
    hint: "绝不写的内容。红线优先于任何风格要求",
    kind: "list",
    injected: true,
  },
  {
    key: "language_samples",
    label: "语言样本",
    hint: "你真实说过的句子，一行一句。用来校准口吻",
    kind: "list",
    injected: true,
  },
];
