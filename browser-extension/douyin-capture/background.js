// Service worker: the only place that talks to the local backend, so the page's
// CSP and CORS rules never apply to the capture request.

const DEFAULT_BASE = "http://127.0.0.1:8000";

async function settings() {
  const stored = await chrome.storage.local.get(["token", "apiBase"]);
  return {
    token: String(stored.token || "").trim(),
    apiBase: String(stored.apiBase || DEFAULT_BASE).replace(/\/+$/, ""),
  };
}

async function postCapture(payload) {
  const { token, apiBase } = await settings();
  if (!token) {
    return { ok: false, error: "还没有保存采集令牌。点扩展图标 → 粘贴令牌。" };
  }
  try {
    const response = await fetch(`${apiBase}/api/douyin/capture`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(payload),
    });
    let body = {};
    try {
      body = await response.json();
    } catch (error) {
      body = { detail: `HTTP ${response.status}` };
    }
    return { ok: response.ok, status: response.status, body };
  } catch (error) {
    return {
      ok: false,
      error: `连不上本地后端（${apiBase}）。确认后端已启动。 ${String(error)}`,
    };
  }
}

async function whoami() {
  const { token, apiBase } = await settings();
  if (!token) return { ok: false, error: "未保存令牌" };
  try {
    const response = await fetch(`${apiBase}/api/douyin/capture/whoami`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const body = await response.json().catch(() => ({}));
    return { ok: response.ok, status: response.status, body };
  } catch (error) {
    return { ok: false, error: String(error) };
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "capture") {
    postCapture(message.payload).then(sendResponse);
    return true;
  }
  if (message?.type === "whoami") {
    whoami().then(sendResponse);
    return true;
  }
  return false;
});
