import { useEffect, useState } from "react";
import { Input } from "./Field";
import Button from "./Button";
import { ApiError, post } from "../lib/api";
import { writerBootstrap, type WriterStatus } from "../lib/writerBridge";
import "./ModelSetup.css";

/*
 * 搜索源：Key 不再在这里填。
 *
 * 检索走 `POST /api/ai/search`，后端用「设置 → 模型」里默认文本模型的
 * base_url + key 去调网关的 `/search`（WorkBuddy 反代 `/v1/search`）。
 * 所以这里只保留一个真实计费的连通测试，用来确认「配的这个模型，搜索也能用」。
 */

interface SearchProbeResponse {
  hits?: Array<{ title?: string; url?: string }>;
  total?: number;
}

export default function SearchSetup() {
  const [status, setStatus] = useState<WriterStatus | null>(null);
  const [query, setQuery] = useState("小红书 立冬");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState("");

  useEffect(() => {
    void writerBootstrap()
      .then(setStatus)
      .catch(() => setResult("全局设置连接未完成，请到「模型」保存一次 Key。"));
  }, []);

  async function probe() {
    setRunning(true);
    setResult("");
    try {
      const r = await post<SearchProbeResponse>("/api/ai/search", {
        query: query.trim(),
        count: 5,
      });
      const hits = r?.hits ?? [];
      setResult(
        `网关真实检索返回 ${hits.length} 条，第一条：${hits[0]?.title || "（无）"}`,
      );
    } catch (e) {
      const msg =
        e instanceof ApiError
          ? e.displayMessage
          : (e as Error)?.message || "请检查默认文本模型";
      setResult(`搜索没通：${msg}`);
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="ms">
      <p className="ms__help">
        检索不用单独配 Key：它和提炼、写稿共用「
        <a href="/settings/models">设置 → 模型</a>
        」里的默认文本模型，由后端调该模型的网关（WorkBuddy 反代
        <code>/v1/search</code>）。换浏览器、清缓存都不影响。
      </p>
      <p role="status">
        {status?.configured
          ? "默认文本模型已就绪；下面可以真搜一次确认（会计费）。"
          : status?.message || "正在核对默认文本模型…"}
      </p>
      <Input label="搜索测试词" value={query} onChange={setQuery} />
      <Button
        onClick={() => void probe()}
        disabled={running || !status?.configured || !query.trim()}
      >
        {running ? "搜索中…" : "实际搜索测试（计费）"}
      </Button>
      <p role="status">{result}</p>
    </div>
  );
}
