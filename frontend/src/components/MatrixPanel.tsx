/**
 * MatrixPanel.tsx — 账号矩阵（设置 → 账号矩阵）
 *
 * 后端两条端点都在：`POST /api/xhs/matrix/suggest-directions` 和
 * `POST /api/xhs/matrix/generate`。前端零调用，于是 `matrix_mode_enabled`
 * 这张卡只能写「尚无入口」。
 *
 * 三条硬约束，界面必须提前说清，否则用户点下去只会拿到 422/403：
 *
 * 1. `account_ids` 是 **2~5 个**（`matrix.py:36/42`）。只有一个号时后端直接
 *    422「List should have at least 2 items」，这不是 bug，是矩阵的定义。
 *    所以这里先数账号，不够就把「再绑一个」摆在按钮位置。
 * 2. `generate` 要 `matrix_mode_enabled`，`suggest-directions` 不要。
 *    也就是说「先看方向」永远能用，「开始生成」要先开开关。
 * 3. 产出是每个账号一篇**草稿**（`origin="matrix"`），不建发布任务。
 *    相似度过高的会带 warning，提示人工再差异化。
 */

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Button from "./Button";
import EmptyState from "./EmptyState";
import { Input, Textarea } from "./Field";
import { SkeletonList } from "./Skeleton";
import { useToast } from "./Toast";
import { ApiError, get, post, unwrapList } from "../lib/api";
import { useQuery, invalidate } from "../lib/query";
import { loadStructureTemplates } from "../lib/skills";
import "./Matrix.css";

interface AccountRow {
  id: number;
  platform?: string;
  sub_type?: string;
  nickname?: string;
  status?: string;
}

interface Direction {
  account_id: number;
  account_name: string;
  direction: string;
}

interface GenerateItem {
  account_id: number;
  account_name: string;
  direction?: string;
  draft_id?: number;
  title?: string;
  body_preview?: string;
  similarity?: number | null;
  warning?: string;
  status?: string;
  error?: string;
}

interface MatrixPayload {
  created_count: number;
  failed_count: number;
  items: GenerateItem[];
}

const fallbackDirections = [
  "讲方法和流程",
  "讲踩坑和失败",
  "讲真实案例",
  "讲报价和交付",
  "讲反常识观点",
];

export default function MatrixPanel() {
  const toast = useToast();

  const accountsQ = useQuery(
    () => get("/api/accounts?page_size=100").then((r) => unwrapList<AccountRow>(r)),
    [],
    { key: "matrix|accounts", staleTime: 60_000 },
  );
  const templatesQ = useQuery(() => loadStructureTemplates(), [], {
    key: "matrix|templates",
    staleTime: 60_000,
  });

  const accounts = (accountsQ.data?.items ?? []).filter(
    (a) =>
      (a.platform ?? "xhs") === "xhs" &&
      ((a.sub_type ?? "pc") === "pc" || a.sub_type === "creator"),
  );
  const templates = templatesQ.data?.items ?? [];

  const [picked, setPicked] = useState<number[]>([]);
  const [topic, setTopic] = useState("");
  const [instruction, setInstruction] = useState("");
  const [templateId, setTemplateId] = useState("");

  const [directions, setDirections] = useState<Direction[] | null>(null);
  const [suggesting, setSuggesting] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [result, setResult] = useState<MatrixPayload | null>(null);

  const effectivePicked = useMemo(() => {
    const alive = picked.filter((id) => accounts.some((a) => a.id === id));
    return alive.length > 0 ? alive : accounts.slice(0, 5).map((a) => a.id);
  }, [picked, accounts]);

  const canRun = accounts.length >= 2 && effectivePicked.length >= 2;

  function toggle(id: number) {
    setPicked((prev) => {
      const base = prev.length > 0 ? prev : effectivePicked;
      if (base.includes(id)) {
        return base.length > 2 ? base.filter((x) => x !== id) : base;
      }
      if (base.length >= 5) return base;
      return [...base, id];
    });
  }

  async function suggest() {
    if (!canRun) return;
    setSuggesting(true);
    try {
      const r = await post<{ items: Direction[] }>(
        "/api/xhs/matrix/suggest-directions",
        { account_ids: effectivePicked, topic: topic.trim() },
      );
      setDirections(r.items ?? []);
      toast.success("方向建议出来了，可以逐条改");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "生成方向失败");
    } finally {
      setSuggesting(false);
    }
  }

  async function generate() {
    if (!canRun) return;
    const list =
      directions && directions.length > 0
        ? directions
        : effectivePicked.map((id, i) => ({
            account_id: id,
            account_name: accounts.find((a) => a.id === id)?.nickname ?? `账号 ${id}`,
            direction: fallbackDirections[i % fallbackDirections.length],
          }));

    setGenerating(true);
    try {
      const r = await post<MatrixPayload>("/api/xhs/matrix/generate", {
        account_ids: effectivePicked,
        topic: topic.trim(),
        instruction: instruction.trim(),
        template_id: templateId ? Number(templateId) : null,
        account_directions: list.map((d) => ({
          account_id: d.account_id,
          direction: d.direction,
        })),
      });
      setResult(r);
      invalidate("write|drafts|all");
      toast.success(`生成了 ${r.created_count} 篇草稿`);
    } catch (err) {
      /*
       * 403 是「批量矩阵」开关没开——原话就是要看到的那句话，
       * 不要改写成「生成失败」。
       */
      toast.error(err instanceof ApiError ? err.message : "生成失败");
    } finally {
      setGenerating(false);
    }
  }

  if (accountsQ.initialLoading) return <SkeletonList rows={3} />;

  return (
    <div className="mx">
      <p className="mx__lead">
        同一个选题，让每个账号写一个不同的角度。产出是<strong>每号一篇草稿</strong>，
        不建发布任务；相似度高的会标出来，提醒你再改。
      </p>

      {accounts.length < 2 ? (
        <div className="mx__blocker">
          <strong>矩阵至少要两个小红书账号</strong>
          <span>
            现在有 {accounts.length} 个。后端对 `account_ids` 的限制是 2~5 个——
            一个号只能写一篇，谈不上「矩阵」。
            去「设置 → 账号」再绑一个；如果你还有别的号，扫码时可以不勾
            「同时获取创作中心」单独加一个 PC 号。
          </span>
          <span className="mx__blockerAct">
            <Link className="mx__link" to="/settings/accounts">
              去绑定账号 ↗
            </Link>
          </span>
        </div>
      ) : null}

      <div className="mx__pick">
        <span className="mx__pickK">参与这次矩阵（2~5 个）</span>
        <div className="mx__chips">
          {accounts.map((a) => {
            const on = effectivePicked.includes(a.id);
            return (
              <button
                key={a.id}
                type="button"
                className={`mx__chip${on ? " is-on" : ""}`}
                aria-pressed={on}
                onClick={() => toggle(a.id)}
              >
                {a.nickname || `账号 ${a.id}`}
                {a.sub_type === "creator" ? (
                  <span className="mx__chipTag">创作中心</span>
                ) : null}
              </button>
            );
          })}
        </div>
      </div>

      <Input
        label="选题"
        hint="一句话题目或方向；也可以留空，让模型按各账号定位自己判断。"
        value={topic}
        placeholder="比如：AI 工具怎么选"
        onChange={setTopic}
        maxLength={300}
      />
      <Textarea
        label="统一要求"
        hint="对所有账号生效。差异化请在下面的「方向」里逐条写。"
        value={instruction}
        placeholder="比如：都用第一人称，每篇给一个可复用的步骤"
        onChange={setInstruction}
        rows={2}
        maxLength={1000}
      />
      {templates.length > 0 ? (
        <label className="mx__select">
          <span className="mx__selectK">结构模板</span>
          <select
            className="field__input field__select"
            value={templateId}
            onChange={(e) => setTemplateId(e.target.value)}
          >
            <option value="">不指定</option>
            {templates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      <div className="mx__acts">
        <Button
          variant="secondary"
          size="sm"
          loading={suggesting}
          disabled={!canRun}
          onClick={() => void suggest()}
        >
          先给我方向
        </Button>
        <Button
          variant="primary"
          size="sm"
          loading={generating}
          disabled={!canRun}
          onClick={() => void generate()}
        >
          开始生成草稿
        </Button>
        <span className="mx__actsHint">
          {canRun
            ? `将生成 ${effectivePicked.length} 篇`
            : "先绑定至少两个账号"}
        </span>
      </div>

      {directions && directions.length > 0 ? (
        <div className="mx__dirs">
          <div className="mx__dirsHead">
            <strong>每个账号的方向</strong>
            <span>改完再生成；方向差别越大，最后几篇越不像</span>
          </div>
          <ul className="mx__dirList">
            {directions.map((d) => (
              <li className="mx__dirRow" key={d.account_id}>
                <span className="mx__dirWho">{d.account_name}</span>
                <input
                  className="mx__dirInput"
                  value={d.direction}
                  maxLength={120}
                  onChange={(e) =>
                    setDirections((prev) =>
                      (prev ?? []).map((x) =>
                        x.account_id === d.account_id
                          ? { ...x, direction: e.target.value }
                          : x,
                      ),
                    )
                  }
                />
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {result ? (
        <div className="mx__result">
          <div className="mx__resultHead">
            <strong>
              生成 {result.created_count} 篇
              {result.failed_count > 0 ? `，失败 ${result.failed_count} 篇` : ""}
            </strong>
            <span>草稿在「写稿」左栏，按账号筛就能看到</span>
          </div>
          <ul className="mx__resultList">
            {result.items.map((item) => (
              <li className="mx__resultRow" key={item.account_id}>
                <span className="mx__resultWho">{item.account_name}</span>
                <span className="mx__resultTitle">
                  {item.title || item.error || "（没有产出）"}
                </span>
                {typeof item.similarity === "number" ? (
                  <span
                    className={`mx__sim${item.similarity >= 0.8 ? " is-warn" : ""}`}
                    title="与其他账号版本的正文相似度"
                  >
                    {item.similarity.toFixed(2)}
                  </span>
                ) : null}
                {item.draft_id ? (
                  <a className="mx__resultLink" href={`/write/${item.draft_id}`}>
                    打开草稿 ↗
                  </a>
                ) : null}
              </li>
            ))}
          </ul>
          {result.items.some((i) => i.warning) ? (
            <p className="mx__warn">
              {result.items
                .filter((i) => i.warning)
                .map((i) => `${i.account_name}：${i.warning}`)
                .join("；")}
            </p>
          ) : null}
        </div>
      ) : null}

      {!result && !canRun ? (
        <EmptyState
          compact
          glyph="flow"
          title="等账号齐了再开始"
          description="矩阵的价值在于同一个选题的几种不同写法。账号不够时，这里不会假装能跑。"
        />
      ) : null}
    </div>
  );
}
