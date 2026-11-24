/**
 * search.ts — 联网检索（走后端代理）
 *
 * 只有一条路：`POST /api/ai/search`。
 *
 * 历史：这里原来是浏览器直连 `api.deepseek.com/v1/tools/search`，Key 明文存在
 * `localStorage`（`xhs.search.key`）。换浏览器 / 清缓存就失效，而且把一把能计费
 * 的 Key 放在前端本身就是风险。现在写稿、提炼、检索共用同一个默认文本模型的
 * 网关（WorkBuddy 反代 `http://127.0.0.1:7863/v1`，检索走 `/v1/search`）：
 *
 *   浏览器 ── query ──▶ 后端 /api/ai/search ──▶ {base_url}/search
 *
 * 后端用「设置 → 模型」里默认文本模型的 base_url + key 发请求，前端不再碰 Key。
 * 没配默认模型时后端返回 400，这里翻译成 `not_configured`，界面据此指路。
 */

import { ApiError, post } from "./api";

export interface SearchHit {
  title: string;
  url: string;
  snippet: string;
  /** 来源站点名（网关给的 site；缺省时从域名推） */
  source: string;
  summary?: string;
  score?: number;
  /** 权威度 0-4，≥3 算权威；-1 未知。WorkBuddy 搜索不给这个字段 */
  authority?: number;
  /** 发布时间，RFC3339 */
  date?: string;
}

export interface SearchOutcome {
  ok: boolean;
  reason?: "not_configured" | "failed";
  message?: string;
  hits: SearchHit[];
  via?: SearchChannel;
}

type SearchChannel = "workbuddy";

const LEGACY_KEY_STORE = "xhs.search.key";
const LEGACY_PROVIDER_STORE = "xhs.search.provider";

function isAbortError(e: unknown): boolean {
  return (
    (typeof DOMException !== "undefined" &&
      e instanceof DOMException &&
      e.name === "AbortError") ||
    (e instanceof Error && e.name === "AbortError")
  );
}

/**
 * 老版本在 localStorage 里留过明文 DeepSeek Key。现在不用了，
 * 模块加载时顺手清掉，免得一把能计费的 Key 一直躺在浏览器里。
 */
function dropLegacyKey(): void {
  try {
    localStorage.removeItem(LEGACY_KEY_STORE);
    localStorage.removeItem(LEGACY_PROVIDER_STORE);
  } catch {
    /* 隐私模式写不进去，也不影响检索 */
  }
}
dropLegacyKey();

function hostOf(u: string): string {
  try {
    return new URL(u).hostname.replace(/^www\./, "");
  } catch {
    return "未知来源";
  }
}

interface SearchResponse {
  hits?: Array<Partial<SearchHit> & { url?: string }>;
  total?: number;
  provider?: string;
  elapsed_ms?: number;
}

/* ---------------- 统一入口 ---------------- */

/**
 * 搜一次：交给后端代理。没配默认模型 → not_configured，绝不回退免费源。
 */
export async function searchWeb(
  query: string,
  signal?: AbortSignal,
): Promise<SearchOutcome> {
  const q = query.trim();
  if (!q) return { ok: true, hits: [], via: "workbuddy" };

  try {
    const r = await post<SearchResponse>(
      "/api/ai/search",
      { query: q.slice(0, 128), count: 10 },
      { signal },
    );
    const raw = Array.isArray(r?.hits) ? r.hits : [];
    const hits: SearchHit[] = raw
      .filter((x) => typeof x?.url === "string" && x.url.trim())
      .map((x) => ({
        title: x.title?.trim() || x.url!,
        url: x.url!,
        snippet: (x.snippet || "").slice(0, 240),
        source: x.source?.trim() || hostOf(x.url!),
        summary: x.summary,
        score: x.score,
        authority: x.authority,
        date: x.date ?? undefined,
      }));
    return { ok: true, hits, via: "workbuddy" };
  } catch (e) {
    if (isAbortError(e)) throw e;
    // 400 = 默认文本模型没配 / 缺 base_url，属于「还没配源」，不是搜索失败。
    const notConfigured = e instanceof ApiError && e.status === 400;
    return {
      ok: false,
      reason: notConfigured ? "not_configured" : "failed",
      message: e instanceof Error ? e.message : "检索失败",
      hits: [],
      via: "workbuddy",
    };
  }
}
