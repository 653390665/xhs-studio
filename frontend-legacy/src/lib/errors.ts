/**
 * Central error-message normalization.
 *
 * Backend details are mostly Chinese, but FastAPI validation errors, network
 * failures and 5xx responses can surface as English/technical strings. Every
 * API error passes through the axios interceptor, which rewrites
 * ``error.response.data.detail`` with the message produced here. Pages can
 * therefore keep using ``detail || fallback`` and still show consistent copy.
 */

const STATUS_MESSAGES: Record<number, string> = {
  400: "提交内容不合法，请检查后重试",
  401: "登录已失效，请重新登录",
  403: "没有权限执行这个操作",
  404: "资源不存在或已被删除",
  409: "当前状态不允许这个操作",
  422: "提交内容不合法，请检查必填项",
  429: "操作太频繁，请稍后再试",
  500: "服务异常，请稍后重试",
  502: "服务暂时不可用，请稍后重试",
  503: "服务暂时不可用，请稍后重试",
  504: "服务响应超时，请稍后重试",
};

const DETAIL_MESSAGES: Record<string, string> = {
  "draft not found": "草稿不存在或已删除",
  "account not found": "账号不存在或无权访问",
  "publish job not found": "发布任务不存在",
  "skill not found": "Skill 不存在",
  "not found": "资源不存在或已被删除",
  unauthorized: "登录已失效，请重新登录",
  forbidden: "没有权限执行这个操作",
  "internal server error": "服务异常，请稍后重试",
  "bad gateway": "服务暂时不可用，请稍后重试",
  "service unavailable": "服务暂时不可用，请稍后重试",
  "network error": "无法连接后端服务，请确认服务已启动",
  "invalid token": "登录已失效，请重新登录",
  "token expired": "登录已失效，请重新登录",
};

type ErrorLike = {
  response?: {
    status?: number;
    data?: { detail?: unknown; message?: unknown };
  };
  message?: string;
  code?: string;
};

function hasChinese(value: string): boolean {
  return /[\u4e00-\u9fff]/.test(value);
}

function normalizeDetail(detail: unknown, status?: number): string | null {
  if (typeof detail === "string") {
    const text = detail.trim();
    if (!text) return null;
    const mapped = DETAIL_MESSAGES[text.toLowerCase()];
    if (mapped) return mapped;
    if (hasChinese(text)) return text;
    if (/request failed with status code/i.test(text)) return null;
    return status ? STATUS_MESSAGES[status] || null : null;
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (!item || typeof item !== "object") return "";
        const record = item as Record<string, unknown>;
        const message = String(record.msg || "").trim();
        const field = Array.isArray(record.loc) ? record.loc.slice(1).join(".") : "";
        return field && message ? `${field}：${message}` : message;
      })
      .filter(Boolean)
      .slice(0, 3);
    return messages.length ? `提交内容不合法：${messages.join("；")}` : "提交内容不合法";
  }
  if (detail && typeof detail === "object") {
    const record = detail as Record<string, unknown>;
    if (typeof record.message === "string" && record.message.trim()) {
      return normalizeDetail(record.message, status);
    }
  }
  return null;
}

export function errorMessage(error: unknown, fallback = "请求失败，请稍后重试"): string {
  const value = (error || {}) as ErrorLike;
  const status = value.response?.status;
  const normalized = normalizeDetail(value.response?.data?.detail, status);
  if (normalized) return normalized;

  if (status && STATUS_MESSAGES[status]) return STATUS_MESSAGES[status];

  const raw = (value.message || "").trim();
  if (/network error|econnrefused|failed to fetch|timeout|timed out|connection reset/i.test(raw)) {
    return "无法连接后端服务，请确认服务已启动";
  }
  if (/request failed with status code/i.test(raw)) return fallback;
  // Only Chinese copy passes through; unknown English details fall back to the
  // status-based message so the UI never mixes languages.
  if (raw && hasChinese(raw)) return raw;
  return fallback;
}

export function normalizeApiError(error: unknown): string {
  return errorMessage(error);
}

type TaskErrorLike = {
  error_type?: string | null;
  payload?: Record<string, unknown> | null;
};

function stripHtml(value: string): string {
  return value
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Turn persisted task errors into operator-facing copy.
 *
 * Task payloads can contain raw HTTP bodies, model URLs and stack traces. The
 * dashboard must never show those verbatim; this helper maps the common local
 * failure modes to a concrete next action and otherwise strips HTML.
 */
export function humanizeTaskError(task: TaskErrorLike): string {
  const type = (task.error_type || "").trim();
  const raw = typeof task.payload?.error === "string" ? task.payload.error : "";
  const text = `${type} ${raw}`;

  if (/127\.0\.0\.1.*7863|localhost.*7863|host=.*7863/i.test(text)) {
    return "AI 模型还没连上，AI 改写和标题生成暂时不能用。去「设置 → 模型」换一个可用模型。";
  }
  if (/max retries exceeded|newconnectionerror|nameresolutionerror|econnrefused|connection refused|connection reset|failed to fetch|connect timeout/i.test(text)) {
    return "模型或后端服务连接失败，请检查服务地址是否可访问";
  }
  if (/404/i.test(text) && /<!doctype|<html/i.test(raw)) {
    return "模型接口返回 404，通常是接口地址或模型名配置错误";
  }
  if (/429|too many requests|rate limit/i.test(text)) {
    return "请求被限流，请稍后重试或换一个数据源";
  }
  if (/401|403|unauthorized|forbidden|invalid token/i.test(text)) {
    return "登录态或密钥已失效，请重新登录或更新模型密钥";
  }
  if (/timeout|timed out|超时/i.test(text) || /timeout/i.test(type)) {
    return "请求超时，请稍后重试";
  }
  if (/cookie|login required|not logged in|登录态/i.test(text)) {
    return "账号登录态失效，请重新登录后再试";
  }

  const clean = stripHtml(raw);
  if (clean && /[\u4e00-\u9fff]/.test(clean)) return clean.slice(0, 120);
  if (type && type !== "unknown") return `任务执行失败（${type}），请查看任务详情或稍后重试`;
  return "任务执行失败，请查看任务详情或稍后重试";
}
