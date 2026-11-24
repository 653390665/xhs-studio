/**
 * readiness.ts — 「现在能不能用」的唯一判定处
 *
 * 为什么要有这个文件：
 *   模型 Key 和账号登录状态散落在两处（后端 /api/model-configs、本机
 *   localStorage），各自都能单独判断，于是每个页面都写一套自己的「有没有配」
 *   逻辑，最后两种说法互相打架——用户看到「已配置」却点下去报错。
 *
 * 这里只做一件事：两件事各问一遍，给一个可以说人话的结论。
 *   · 模型：后端有默认文本模型，且那条配置带 Key
 *   · 账号：后端 /api/accounts 里有绑定记录且登录态正常
 *
 * 历史：这里原来还有一层「运行端真的接上了吗」——问的是常驻的写稿宿主。
 * 宿主已退场，模型调用直连后端，所以「后端有 Key」就等于「能用」。
 * 判定结果带 reason，页面据此决定文案，不再各自猜。
 */

import { get, unwrapList } from "./api";

export interface ModelReadiness {
  /** 后端有默认文本模型配置 */
  hasConfig: boolean;
  /** 那条配置带没带 Key（带了才算能用） */
  live: boolean;
  /** 后端那条配置带没带 Key */
  hasKey: boolean;
}

export interface AccountReadiness {
  bound: number;
  healthy: number;
}

export interface Readiness {
  model: ModelReadiness;
  account: AccountReadiness;
  /** 两件都就绪才 true */
  ready: boolean;
  /** 缺什么，给页面直接用 */
  missing: Array<"model" | "account">;
  /** 一句话解释，给启动页和引导用 */
  message: string;
}

const MODEL_CACHE_KEY = "xhs.readiness.model";
const ACCOUNT_CACHE_KEY = "xhs.readiness.account";

/*
 * 缓存的意义：启动时先拿上次结论渲染，避免每次刷新都闪一下「未配置」。
 * 但缓存只用于第一帧，真实的探测马上覆盖它 —— 不能拿旧结论当现状。
 */
function readCache<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { at?: number; value?: T };
    if (!parsed?.value || typeof parsed.at !== "number") return null;
    /* 超过一小时不再信任：Key 可能被撤了，账号可能掉了 */
    if (Date.now() - parsed.at > 60 * 60 * 1000) return null;
    return parsed.value;
  } catch {
    return null;
  }
}

function writeCache(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify({ at: Date.now(), value }));
  } catch {
    /* 存不进去就每次现算，不影响功能 */
  }
}

/** 后端模型配置：只读，不发任何计费请求 */
async function probeModel(): Promise<ModelReadiness> {
  try {
    const res = await get("/api/model-configs?model_type=text&page_size=100");
    const items = unwrapList<{
      model_type?: string;
      is_default?: boolean;
      has_api_key?: boolean;
    }>(res).items ?? [];
    const texts = items.filter((m) => (m.model_type ?? "text") === "text");
    const def = texts.find((m) => m.is_default) ?? texts[0];
    const hasKey = Boolean(def?.has_api_key);
    return {
      hasConfig: Boolean(def),
      hasKey,
      /* 直连后端之后，「有配置且有 Key」就是能用，不再有第二层运行端 */
      live: hasKey,
    };
  } catch {
    return { hasConfig: false, hasKey: false, live: false };
  }
}

/** 账号：后端有没有绑定记录、登录态是否正常 */
async function probeAccount(): Promise<AccountReadiness> {
  try {
    const res = await get("/api/accounts");
    const items = unwrapList<{ healthy?: boolean; status?: string }>(res).items ?? [];
    return {
      bound: items.length,
      healthy: items.filter(
        (a) => a.healthy === true || /normal|ok|active/i.test(String(a.status ?? "")),
      ).length,
    };
  } catch {
    return { bound: 0, healthy: 0 };
  }
}

/** 完整判定：两件事都问一遍，给结论 */
export async function checkReadiness(): Promise<Readiness> {
  const [model, account] = await Promise.all([probeModel(), probeAccount()]);
  writeCache(MODEL_CACHE_KEY, model);
  writeCache(ACCOUNT_CACHE_KEY, account);

  const missing: Array<"model" | "account"> = [];
  if (!model.live) missing.push("model");
  if (account.healthy === 0) missing.push("account");

  const parts: string[] = [];
  if (!model.live) {
    parts.push(model.hasConfig ? "模型配置里没有 Key，去重新填一次" : "还没配模型 Key");
  }
  if (account.healthy === 0) {
    parts.push(account.bound === 0 ? "还没扫码绑定小红书账号" : "账号登录态失效了，重新扫一次码");
  }

  return {
    model,
    account,
    ready: missing.length === 0,
    missing,
    message: parts.length ? parts.join("；") : "模型和账号都就绪",
  };
}

/** 拿上次结论，供第一帧渲染。过期的会被丢掉。 */
export function cachedReadiness(): Readiness | null {
  const model = readCache<ModelReadiness>(MODEL_CACHE_KEY);
  const account = readCache<AccountReadiness>(ACCOUNT_CACHE_KEY);
  if (!model || !account) return null;
  const missing: Array<"model" | "account"> = [];
  if (!model.live) missing.push("model");
  if (account.healthy === 0) missing.push("account");
  return {
    model,
    account,
    ready: missing.length === 0,
    missing,
    message: missing.length ? "有东西还没就绪" : "模型和账号都就绪",
  };
}

/**
 * 检索是否就绪。
 *
 * 检索现在走后端代理（`/api/ai/search`），用的是默认文本模型的网关，
 * 所以「模型就绪」就等于「检索就绪」，不再看本机有没有存 Key。
 * 保留这个函数是为了让 readiness 的调用方读到一个明确的名字。
 */
export function searchReady(model: ModelReadiness | null): boolean {
  return Boolean(model?.live);
}

/** 清掉缓存（Key 被换掉、账号解绑时调用） */
export function invalidateReadiness(): void {
  try {
    localStorage.removeItem(MODEL_CACHE_KEY);
    localStorage.removeItem(ACCOUNT_CACHE_KEY);
  } catch {
    /* 忽略 */
  }
  window.dispatchEvent(new Event("xhs:readiness-changed"));
}
