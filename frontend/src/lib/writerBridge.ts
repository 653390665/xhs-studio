/**
 * writerBridge.ts — 模型配置与「让模型做一件小事」的统一入口
 *
 * 历史：这里原来叫「写稿桥」，走的是 `/writer/*`，背后是一个常驻的
 * DeepSeek Harness 子进程（代码 IDE 那套 UI）。那个宿主已经整体退场：
 *   · 它的界面只能靠 CSS 补丁改字，改不了布局；
 *   · 它的模型调用只服务它自己，和后端的 `/api/ai/*` 是两套；
 *   · 它把「写稿」从一个 2,726 行的页面退化成 91 行的 iframe。
 *
 * 现在这里只做两件事，且全部直连后端：
 *   1. 读默认文本模型是否就绪（`GET /api/model-configs`）
 *   2. 转发几个老调用点还在用的动作（保存/删除/设为默认/润色）
 *
 * 为什么保留同名函数：默认值、错误文案、「有没有就绪」的判定散落在六个
 * 组件里；改名字要同时改六处，而这次要动的是背后的实现，不是调用方。
 * 名字先留着，等写稿页重写完再统一收。
 */

import { del, get, post, unwrapList } from "./api";

export interface WriterStatus {
  configured: boolean;
  state?: string;
  message?: string;
  revision: number;
  model?: string;
  settingsPath?: string;
  legacyImportAllowed?: boolean;
}

interface ModelConfigItem {
  id: number | string;
  name?: string;
  model_type?: string;
  provider?: string;
  model_name?: string;
  base_url?: string;
  has_api_key?: boolean;
  is_default?: boolean;
}

function announceProviderChange(): void {
  window.dispatchEvent(new Event("xhs:writer-status-changed"));
  try {
    window.localStorage.setItem("xhs.global-provider-epoch", String(Date.now()));
  } catch {
    /* 只是跨标签页通知，写不进去不影响功能 */
  }
}

/*
 * 出错时说人话。
 *
 * 原来这些 code 来自桥（MISSING_CREDENTIAL / CONFIGURATION_CHANGED…）。
 * 直连后端后 code 少了，但调用方仍在按 code 分支，所以保留这套映射：
 * 后端 4xx/5xx 的 detail 直接透出，网络问题给一句能行动的话。
 */
function failureText(code?: string, message?: string): string {
  if (code === "MISSING_CREDENTIAL") return "模型 Key 还没配置。去「设置 → 模型」填一次就好。";
  if (code === "INVALID_CREDENTIAL") return "DeepSeek 不认这把 Key。去「设置 → 模型」核对一下。";
  if (code === "RATE_LIMITED") return "DeepSeek 在限流，等几十秒再试。";
  if (code === "PROVIDER_UNAVAILABLE" || code === "PROVIDER_ERROR") {
    return "DeepSeek 那边暂时没响应，等一会儿再试。";
  }
  return message || "请求失败";
}

let cached: { at: number; value: WriterStatus } | null = null;
/** 就绪状态 15 秒内复用，避免每个组件各拉一次配置表 */
const CACHE_TTL = 15_000;

async function readStatus(): Promise<WriterStatus> {
  const res = await get("/api/model-configs?model_type=text&page_size=100");
  const items = unwrapList<ModelConfigItem>(res).items ?? [];
  const def = items.find((item) => item.is_default) ?? items[0];
  const configured = Boolean(def?.has_api_key);
  const value: WriterStatus = {
    configured,
    state: configured ? "ready" : "resave-required",
    message: configured
      ? "模型已配置"
      : "还没有可用的文本模型。到「设置 → 模型」填一次 Key。",
    revision: cached ? cached.value.revision + 1 : 1,
    model: def?.model_name,
    settingsPath: "/settings/models",
    legacyImportAllowed: false,
  };
  return value;
}

/**
 * 读当前模型是否就绪。
 *
 * `force` 会绕过 15 秒缓存 —— 用户刚保存完 Key 时必须重新问一次，
 * 否则界面会显示「还没配置」，让人以为保存失败。
 */
export async function writerBootstrap(force = false): Promise<WriterStatus> {
  if (!force && cached && Date.now() - cached.at < CACHE_TTL) {
    return cached.value;
  }
  const value = await readStatus();
  cached = { at: Date.now(), value };
  return value;
}

interface CompatResult {
  writer_sync?: WriterStatus;
  [key: string]: unknown;
}

/**
 * 兼容层：只保留还在被调用的几个动作，其余一律拒绝。
 *
 * 与其留下一条「什么路径都能过」的转发（那种东西半年后没人知道它到底
 * 连去哪），不如把支持范围写死。新增动作就显式加一个 case。
 */
export async function writerRequest<T = unknown>(
  path: string,
  body?: unknown,
): Promise<T> {
  const payload = (body ?? {}) as Record<string, unknown>;

  if (path === "status") {
    return (await writerBootstrap()) as T;
  }

  if (path === "config/save") {
    const created = await post<ModelConfigItem>("/api/model-configs", {
      name: String(payload.name ?? "DeepSeek"),
      model_type: "text",
      provider: String(payload.provider ?? "deepseek"),
      model_name: String(payload.model_name ?? ""),
      base_url: String(payload.base_url ?? ""),
      api_key: String(payload.api_key ?? ""),
      is_default: payload.is_default !== false,
    });
    cached = null;
    announceProviderChange();
    const status = await writerBootstrap(true);
    const result: CompatResult = {
      created,
      writer_sync: status,
    };
    return result as T;
  }

  if (path === "config/delete") {
    await del(`/api/model-configs/${encodeURIComponent(String(payload.id))}`);
    cached = null;
    announceProviderChange();
    return { id: payload.id, status: "deleted" } as T;
  }

  if (path === "config/default") {
    const updated = await post<ModelConfigItem>(
      `/api/model-configs/${encodeURIComponent(String(payload.id))}/set-default`,
      {},
    );
    cached = null;
    announceProviderChange();
    return { created: updated, writer_sync: await writerBootstrap(true) } as T;
  }

  /*
   * 只有「润色/整理一段文字」还用得到模型。
   *
   * 原来走桥的 `model/complete`（宿主里那把 Key）。直连后端后，
   * `/api/ai/polish-text` 就是同一件事：给一段文本和一条指令，回一段文本。
   * 上限也一致（文本 6000 / 指令 800）。
   *
   * `temperature` / `seed` 是可选的，透传给后端：工作台的「提炼成模板」
   * 要可复现（低温度 + 固定 seed），否则同一批素材点两次出两份不同模板。
   */
  if (path === "model/complete") {
    const text = String(payload.text ?? "");
    const instruction = String(payload.instruction ?? "").slice(0, 800);
    const body: Record<string, unknown> = { text, instruction };
    if (typeof payload.temperature === "number") {
      body.temperature = payload.temperature;
    }
    if (typeof payload.seed === "number") {
      body.seed = payload.seed;
    }
    const result = await post<{ text: string }>("/api/ai/polish-text", body);
    return { text: result.text } as T;
  }

  throw new Error(failureText(undefined, `这个动作已经下线：${path}`));
}

