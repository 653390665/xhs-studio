/**
 * SearchSetup.tsx — 「找资料」用的检索网关
 *
 * 为什么要单独配
 * --------------
 * 写稿/提炼要的是网关的 `/chat/completions`，「找资料」要的是 `/search`。
 * 这两件事不一定在同一个网关上：amr-link 只做 chat，`/v1/search` 直接 404，
 * 于是找资料必然失败。所以这里让用户单独填一个支持 /search 的网关。
 *
 * 留空 = 回落到「设置 → 模型」的默认文本模型（和以前行为一致）。
 *
 * 落盘：`user_settings.json`（和 RedFox key 同一个文件），Key 用 Fernet 加密。
 * 接口：GET/PUT /api/search/gateway
 */

import { useEffect, useState } from "react";
import { ApiError, get, put } from "../lib/api";
import { Input } from "./Field";
import Button from "./Button";
import { post } from "../lib/api";
import "./ModelSetup.css";

interface GatewayState {
  base_url: string;
  model_name: string;
  configured: boolean;
  api_key_masked: string;
}

interface SearchProbeResponse {
  hits?: Array<{ title?: string; url?: string }>;
}

const EMPTY: GatewayState = {
  base_url: "",
  model_name: "",
  configured: false,
  api_key_masked: "",
};

export default function SearchSetup() {
  const [saved, setSaved] = useState<GatewayState>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");

  const [baseUrl, setBaseUrl] = useState("");
  const [modelName, setModelName] = useState("");
  const [apiKey, setApiKey] = useState("");

  const [saving, setSaving] = useState(false);
  const [saveNote, setSaveNote] = useState("");

  const [query, setQuery] = useState("小红书 立冬");
  const [probing, setProbing] = useState(false);
  const [probeNote, setProbeNote] = useState("");

  useEffect(() => {
    let alive = true;
    get<GatewayState>("/api/search/gateway")
      .then((r) => {
        if (!alive) return;
        setSaved(r);
        setBaseUrl(r.base_url);
        setModelName(r.model_name);
      })
      .catch((e) => {
        if (!alive) return;
        setLoadError(
          e instanceof ApiError ? e.displayMessage : "读取检索配置失败",
        );
      })
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  async function save() {
    setSaving(true);
    setSaveNote("");
    try {
      const body: Record<string, string> = {
        base_url: baseUrl.trim(),
        model_name: modelName.trim(),
      };
      /* 空 Key 表示「不改」；用户明确要清空时点下面的按钮 */
      if (apiKey.trim()) body.api_key = apiKey.trim();

      const r = await put<GatewayState>("/api/search/gateway", body);
      setSaved(r);
      setApiKey("");
      setSaveNote(
        r.configured
          ? "已保存。下面可以真搜一次确认。"
          : "已保存，但地址和 Key 要都填了才算配置完成。",
      );
    } catch (e) {
      setSaveNote(
        e instanceof ApiError ? `保存失败：${e.displayMessage}` : "保存失败",
      );
    } finally {
      setSaving(false);
    }
  }

  async function clearAll() {
    setSaving(true);
    setSaveNote("");
    try {
      const r = await put<GatewayState>("/api/search/gateway", {
        base_url: "",
        model_name: "",
        api_key: "",
      });
      setSaved(r);
      setBaseUrl("");
      setModelName("");
      setApiKey("");
      setSaveNote("已清空。检索会回落到「设置 → 模型」的默认文本模型。");
    } catch (e) {
      setSaveNote(
        e instanceof ApiError ? `清空失败：${e.displayMessage}` : "清空失败",
      );
    } finally {
      setSaving(false);
    }
  }

  async function probe() {
    setProbing(true);
    setProbeNote("");
    try {
      const r = await post<SearchProbeResponse>("/api/ai/search", {
        query: query.trim(),
        count: 5,
      });
      const hits = r?.hits ?? [];
      setProbeNote(
        `检索通了，返回 ${hits.length} 条。第一条：${hits[0]?.title || "（无）"}`,
      );
    } catch (e) {
      const msg = e instanceof ApiError ? e.displayMessage : "检索失败";
      setProbeNote(`检索没通：${msg}`);
    } finally {
      setProbing(false);
    }
  }

  return (
    <div className="ms">
      <p className="ms__help">
        「找资料」要的是网关的 <code>/search</code>，它和写稿用的{" "}
        <code>/chat/completions</code> 不一定在同一个网关上。
        如果你的默认文本模型只做对话（访问 <code>/v1/search</code> 会 404），
        就在这里单独填一个支持检索的网关。
      </p>

      {loading ? <p role="status">正在读取检索配置…</p> : null}
      {loadError ? <p role="status">{loadError}</p> : null}

      {!loading && !loadError ? (
        <>
          <p role="status">
            {saved.configured
              ? `已单独配置检索网关：${saved.base_url}（Key ${saved.api_key_masked}）`
              : "当前没单独配检索网关，检索会回落到默认文本模型。"}
          </p>

          <Input
            label="检索网关地址"
            value={baseUrl}
            onChange={setBaseUrl}
            placeholder="http://127.0.0.1:7863/v1"
          />
          <Input
            label="模型名（可留空，留空则用默认文本模型的模型名）"
            value={modelName}
            onChange={setModelName}
            placeholder="deepseek-v4.1-flash"
          />
          <Input
            label={
              saved.api_key_masked
                ? `API Key（已保存 ${saved.api_key_masked}，留空=不改）`
                : "API Key"
            }
            value={apiKey}
            onChange={setApiKey}
            placeholder="sk-..."
          />

          <div className="ms__row">
            <Button variant="primary" onClick={() => void save()} loading={saving}>
              保存检索配置
            </Button>
            <Button variant="ghost" onClick={() => void clearAll()} disabled={saving}>
              清空（回落到默认模型）
            </Button>
          </div>
          {saveNote ? <p role="status">{saveNote}</p> : null}

          <hr />

          <Input label="搜索测试词" value={query} onChange={setQuery} />
          <Button
            variant="secondary"
            onClick={() => void probe()}
            loading={probing}
            disabled={!query.trim()}
          >
            实际搜索测试（会计费）
          </Button>
          {probeNote ? <p role="status">{probeNote}</p> : null}
        </>
      ) : null}
    </div>
  );
}
