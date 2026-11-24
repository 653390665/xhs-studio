/**
 * api.ts — 统一 fetch 封装
 *
 * - 后端地址见 base.ts：开发是 127.0.0.1:8000，打包版是同源
 * - 自动带 Bearer token
 * - 401 自动清 token 并跳登录（不在这里做路由跳转，交给 auth store + 事件）
 * - 统一错误对象 ApiError
 * - get/post/put/patch/del 泛型返回
 */

import { clearSession, getToken, markSessionExpired, renewSession } from "./auth";
import { API_BASE } from "./base";

export { API_BASE };

/* ============================================================
   统一错误对象
   后端 FastAPI 错误形状（实测）：
     401 → {"detail": "用户名或密码错误"}
     422 → {"detail": [{loc:[...], msg:"...", type:"..."}]}
   ============================================================ */

export type ApiErrorKind =
  | "network" /* 连不上后端 */
  | "auth" /* 401/403 */
  | "not_found" /* 404 */
  | "validation" /* 422 */
  | "server" /* 5xx */
  | "http"; /* 其他 */

export class ApiError extends Error {
  readonly status: number;
  readonly kind: ApiErrorKind;
  readonly detail: string;
  readonly payload: unknown;

  constructor(
    status: number,
    detail: string,
    payload: unknown,
    kind: ApiErrorKind,
  ) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.payload = payload;
    this.kind = kind;
  }

  /** 给界面直接用的一句中文 */
  get displayMessage(): string {
    return this.detail || "请求失败";
  }
}

function kindForStatus(status: number): ApiErrorKind {
  if (status === 401 || status === 403) return "auth";
  if (status === 404) return "not_found";
  if (status === 422) return "validation";
  if (status >= 500) return "server";
  return "http";
}

/** 从 FastAPI 的错误体里抽出人话 */
function extractDetail(payload: unknown, fallback: string): string {
  if (typeof payload === "string" && payload.trim()) return payload;
  if (typeof payload !== "object" || payload === null) return fallback;

  const obj = payload as Record<string, unknown>;
  const detail = obj.detail;

  // 最常见：{"detail": "用户名或密码错误"}
  if (typeof detail === "string" && detail.trim()) return detail;

  // 422：[{loc, msg, type}]
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === "object" && item !== null) {
          const msg = (item as Record<string, unknown>).msg;
          if (typeof msg === "string") return msg;
        }
        return typeof item === "string" ? item : null;
      })
      .filter((m): m is string => Boolean(m));
    if (messages.length > 0) return messages.join("；");
  }

  // 少数端点用 message
  if (typeof obj.message === "string" && obj.message.trim()) return obj.message;

  return fallback;
}

/* ============================================================
   401 处理：清 token + 通知外壳跳登录
   用自定义事件而不是直接动 location，
   让 React Router 接管跳转，避免整页刷新。
   ============================================================ */

export const AUTH_EXPIRED_EVENT = "xhs:auth-expired";

export function onAuthExpired(handler: () => void): () => void {
  window.addEventListener(AUTH_EXPIRED_EVENT, handler);
  return () => window.removeEventListener(AUTH_EXPIRED_EVENT, handler);
}

function handleUnauthorized(): void {
  const hadToken = Boolean(getToken());
  clearSession();
  // 登录接口本身 401（密码错）不应触发"会话过期"跳转
  if (hadToken) {
    markSessionExpired();
    window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
  }
}

/* ============================================================
   请求
   ============================================================ */

export interface RequestOptions {
  /** 查询参数，值为 undefined/null 的会被丢掉 */
  query?: Record<string, string | number | boolean | undefined | null>;
  /** 额外请求头 */
  headers?: Record<string, string>;
  /** 外部取消信号（组件卸载时用） */
  signal?: AbortSignal;
  /** 是否跳过 401 统一处理（登录接口自己处理错误文案） */
  skipAuthRedirect?: boolean;
  /**
   * 页面卸载时也要发出去（关标签页 / 刷新 / 关窗口）。
   *
   * 只对 `beforeunload` / `pagehide` 里发起的请求有意义：普通请求带
   * `keepalive` 会白占一个连接槽。浏览器上限 64 KB，所以只适合
   * 「保存一段正文」这种小请求。
   */
  keepalive?: boolean;
}

function buildUrl(
  path: string,
  query?: RequestOptions["query"],
): string {
  const url = path.startsWith("http")
    ? path
    : `${API_BASE}${path.startsWith("/") ? path : `/${path}`}`;

  if (!query) return url;

  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null) continue;
    params.append(key, String(value));
  }
  const qs = params.toString();
  if (!qs) return url;
  return url.includes("?") ? `${url}&${qs}` : `${url}?${qs}`;
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  options: RequestOptions = {},
  renewed = false,
): Promise<T> {
  const url = buildUrl(path, options.query);

  const headers: Record<string, string> = {
    Accept: "application/json",
    ...options.headers,
  };

  const token = getToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  let payloadBody: BodyInit | undefined;
  if (body !== undefined) {
    if (body instanceof FormData) {
      // 交给浏览器自己带 boundary
      payloadBody = body;
    } else {
      headers["Content-Type"] = "application/json";
      payloadBody = JSON.stringify(body);
    }
  }

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers,
      body: payloadBody,
      signal: options.signal,
      keepalive: options.keepalive,
    });
  } catch (error) {
    // AbortError 不是错误，原样抛出让调用方识别
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new ApiError(
      0,
      `无法连接后端服务（${API_BASE}），请确认服务已启动`,
      error,
      "network",
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  let parsed: unknown = undefined;

  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      // 后端返回非 JSON（如纯文本报错）时保留原文
      parsed = text;
    }
  }

  if (!response.ok) {
    /*
     * Access token 只有 15 分钟，refresh token 有一个月。
     * 轮询扫码状态这类后台请求很容易撞上过期；以前这里直接
     * handleUnauthorized()，把整个会话清掉，表现为「扫码确认后没跳转」。
     * 先静默续期一次，再重放原请求；只有续期也失败才退出登录。
     */
    if (
      response.status === 401 &&
      !renewed &&
      !options.skipAuthRedirect &&
      (await renewSession(true))
    ) {
      return request<T>(method, path, body, options, true);
    }
    if (response.status === 401 && !options.skipAuthRedirect) {
      handleUnauthorized();
    }
    throw new ApiError(
      response.status,
      extractDetail(parsed, `请求失败（HTTP ${response.status}）`),
      parsed,
      kindForStatus(response.status),
    );
  }

  return parsed as T;
}

/* ============================================================
   对外方法
   ============================================================ */

export function get<T>(path: string, options?: RequestOptions): Promise<T> {
  return request<T>("GET", path, undefined, options);
}

export function post<T>(
  path: string,
  body?: unknown,
  options?: RequestOptions,
): Promise<T> {
  return request<T>("POST", path, body, options);
}

export function put<T>(
  path: string,
  body?: unknown,
  options?: RequestOptions,
): Promise<T> {
  return request<T>("PUT", path, body, options);
}

export function patch<T>(
  path: string,
  body?: unknown,
  options?: RequestOptions,
): Promise<T> {
  return request<T>("PATCH", path, body, options);
}

export function del<T>(
  path: string,
  body?: unknown,
  options?: RequestOptions,
): Promise<T> {
  return request<T>("DELETE", path, body, options);
}

/* ============================================================
   流式 POST（SSE）—— 采集接口用
   ============================================================ */

/**
 * /api/xhs/crawl/data 这类接口不是返回一次性 JSON，
 * 而是逐行吐 {"type":"plan"|"progress"|"item"|"done"|"error", ...}。
 *
 * 用普通的 post() 接会一直等到流结束、且解析失败，
 * 所以单独走一条：边读边回调，界面能实时显示抓到第几条。
 *
 * 取消：传 AbortSignal，abort 时会抛 AbortError，调用方自行忽略。
 */
export async function postStream(
  path: string,
  body: unknown,
  onEvent: (event: Record<string, unknown>) => void,
  options: RequestOptions = {},
): Promise<void> {
  const url = buildUrl(path, options.query);
  const headers: Record<string, string> = {
    Accept: "text/event-stream, application/json",
    "Content-Type": "application/json",
    ...options.headers,
  };

  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      signal: options.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(0, "无法连接后端服务，请确认服务已启动", err, "network");
  }

  if (!response.ok) {
    let detail = `请求失败（HTTP ${response.status}）`;
    try {
      detail = extractDetail(await response.json(), detail);
    } catch {
      /* 保留默认文案 */
    }
    if (response.status === 401 || response.status === 403) {
      handleUnauthorized();
    }
    throw new ApiError(response.status, detail, undefined, "auth");
  }

  if (!response.body) {
    throw new ApiError(response.status, "后端没有返回数据流", undefined, "server");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // 按行切；最后一段可能是不完整的，留在 buffer 里等下一块
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const raw of lines) {
        // 兼容 SSE 的 "data: {...}" 前缀和纯 JSON 行
        const line = raw.replace(/^data:\s*/, "").trim();
        if (!line || line === "[DONE]") continue;
        try {
          onEvent(JSON.parse(line) as Record<string, unknown>);
        } catch {
          // 单行解析失败不中断整条流
        }
      }
    }

    // 收尾：最后一行没有换行符时也要处理
    const tail = buffer.replace(/^data:\s*/, "").trim();
    if (tail && tail !== "[DONE]") {
      try {
        onEvent(JSON.parse(tail) as Record<string, unknown>);
      } catch {
        /* ignore */
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/* ============================================================
   列表信封归一化（API-NOTES.md 要求兼容两种形状）
     { total, page, page_size, items }
     { items, total }
   ============================================================ */

export interface ListEnvelope<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export function unwrapList<T>(
  payload: unknown,
  fallbackPageSize = 20,
): ListEnvelope<T> {
  if (Array.isArray(payload)) {
    return {
      items: payload as T[],
      total: payload.length,
      page: 1,
      page_size: fallbackPageSize,
    };
  }

  if (typeof payload === "object" && payload !== null) {
    const obj = payload as Record<string, unknown>;
    const items = Array.isArray(obj.items) ? (obj.items as T[]) : [];
    const total = typeof obj.total === "number" ? obj.total : items.length;
    const page = typeof obj.page === "number" ? obj.page : 1;
    const page_size =
      typeof obj.page_size === "number" ? obj.page_size : fallbackPageSize;
    return { items, total, page, page_size };
  }

  return { items: [], total: 0, page: 1, page_size: fallbackPageSize };
}
