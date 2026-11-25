/**
 * cards.ts — 小红书图文卡片（拆页 → 逐页生图）
 *
 * 为什么不在前端拼提示词
 * ----------------------
 * 前端拼过一版（正文首段 + "无文字、无水印"），实测十次出十种东西：
 * 有时是插画、有时是图表、有时是空白纸。原因是那句话没把要画的文字交给模型，
 * 还反过来禁止它画字。
 *
 * 现在提示词由后端按「风格 × 布局 × 页面类型」拼装，文字逐行写死。
 * 前端只负责：拆页预览、选风格、选尺寸、看进度、挑图。
 */

import { get, post } from "./api";

export type PageType = "cover" | "content" | "summary";

export interface CardPage {
  type: PageType;
  title: string;
  lines: string[];
  /** 单页覆盖整套的风格/布局 */
  style?: string | null;
  layout?: string | null;
}

export interface CardStyle {
  key: string;
  label: string;
  group: string;
  summary: string;
  max_lines: number;
}

export interface CardLayout {
  key: string;
  label: string;
  summary: string;
  max_lines: number;
}

export interface CardPreset {
  key: string;
  label: string;
  style: string;
  layout: string;
}

export interface CardPresets {
  sizes: string[];
  default_size: string;
  styles: CardStyle[];
  layouts: CardLayout[];
  presets: CardPreset[];
}

export interface PlannedCards {
  pages: CardPage[];
  total: number;
}

export interface GeneratedPage {
  index: number;
  page_type?: PageType;
  title?: string;
  prompt?: string;
  style?: string;
  layout?: string;
  url?: string;
  asset_id?: number;
  error?: string;
  skipped?: boolean;
}

export interface GeneratedCards {
  task_id: number;
  style: string;
  layout: string;
  size: string;
  pages: GeneratedPage[];
  generated: number;
  failed: number;
}

const CACHE_KEY = "xhs.cards.presets";

export function loadPresets(): Promise<CardPresets> {
  return get<CardPresets>("/api/ai/cards/presets").then((r) => {
    try {
      sessionStorage.setItem(CACHE_KEY, JSON.stringify(r));
    } catch {
      /* 存不下也不影响 */
    }
    return r;
  });
}

/** 拆页：把正文变成逐页大纲，用户可以先改再生成。 */
export function planCards(payload: {
  title?: string;
  body: string;
  draftId?: number | null;
  maxPages?: number;
  includeCover?: boolean;
  includeSummary?: boolean;
}): Promise<PlannedCards> {
  return post<PlannedCards>("/api/ai/cards/plan", {
    title: payload.title ?? "",
    body: payload.body,
    draft_id: payload.draftId ?? null,
    max_pages: payload.maxPages ?? 6,
    include_cover: payload.includeCover !== false,
    include_summary: payload.includeSummary !== false,
  });
}

/** 逐页生图。单页失败不抛异常，结果里带 error。 */
export function generateCards(payload: {
  pages: CardPage[];
  draftId?: number | null;
  preset?: string | null;
  style?: string | null;
  layout?: string | null;
  size?: string;
  attachToDraft?: boolean;
  onlyIndex?: number;
}): Promise<GeneratedCards> {
  return post<GeneratedCards>("/api/ai/cards/generate", {
    pages: payload.pages,
    draft_id: payload.draftId ?? null,
    preset: payload.preset ?? null,
    style: payload.style ?? null,
    layout: payload.layout ?? null,
    size: payload.size ?? "1024x1365",
    attach_to_draft: payload.attachToDraft === true,
    only_index: payload.onlyIndex ?? 0,
  });
}

/** 尺寸的短标签（下拉框用）。 */
export function sizeLabel(size: string): string {
  if (size === "1024x1365") return "3:4 竖版（小红书图文）";
  if (size === "1024x1024") return "1:1 方图";
  if (size === "1365x1024") return "4:3 横版";
  return size;
}
