const DEFAULT_BASE = "http://127.0.0.1:8000";
const APP_PATH = "/platforms/xhs/assets/douyin";

const tokenInput = document.getElementById("token");
const baseInput = document.getElementById("apiBase");
const statusEl = document.getElementById("status");
const openApp = document.getElementById("openApp");

const setStatus = (text) => {
  statusEl.textContent = text;
};

const load = () => {
  chrome.storage.local.get(["token", "apiBase"], (stored) => {
    tokenInput.value = stored.token || "";
    baseInput.value = stored.apiBase || DEFAULT_BASE;
    setStatus(stored.token ? "已保存令牌" : "未保存令牌");
  });
};

const save = () => {
  const token = tokenInput.value.trim();
  const apiBase = (baseInput.value.trim() || DEFAULT_BASE).replace(/\/+$/, "");
  chrome.storage.local.set({ token, apiBase }, () => {
    setStatus(token ? "已保存" : "令牌为空");
  });
};

const test = () => {
  setStatus("测试中…");
  chrome.runtime.sendMessage({ type: "whoami" }, (response) => {
    if (chrome.runtime.lastError) {
      setStatus(chrome.runtime.lastError.message);
      return;
    }
    if (response && response.ok) {
      const body = response.body || {};
      setStatus(`连接成功：用户 #${body.user_id} ${body.username || ""}`);
    } else {
      const detail =
        (response && response.body && response.body.detail) ||
        (response && response.error) ||
        `HTTP ${response && response.status}`;
      setStatus(`连接失败：${detail}`);
    }
  });
};

document.getElementById("save").addEventListener("click", save);
document.getElementById("test").addEventListener("click", test);
openApp.addEventListener("click", (event) => {
  event.preventDefault();
  chrome.storage.local.get(["apiBase"], (stored) => {
    const base = String(stored.apiBase || DEFAULT_BASE).replace(/\/+$/, "");
    chrome.tabs.create({ url: `${base}${APP_PATH}` });
  });
});

load();
