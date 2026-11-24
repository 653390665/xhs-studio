/**
 * Plan.tsx — 选题库
 *
 * 选题是"写什么"的中间层：从热点、对标、样本都能生成候选。
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import Button from "../components/Button";
import EmptyState from "../components/EmptyState";
import { SkeletonList } from "../components/Skeleton";
import { Input, Select } from "../components/Field";
import { useToast } from "../components/Toast";
import {
  get,
  post,
  ApiError,
  unwrapList,
  type ListEnvelope,
} from "../lib/api";
import { useQuery, invalidate } from "../lib/query";
import { startTask, useTask } from "../lib/tasks";
import { useKeptState } from "../lib/formState";
import "./Plan.css";

/**
 * 后端 `serialize_topic` 返回的字段（`topic_bank_service.py`）。
 *
 * 这里原来声明的是 `{angle, score}`——**后端一个都不返回**。于是选题列表
 * 永远不显示「角度」（`t.angle` 恒为 undefined），也看不到为什么推荐这一条：
 * 后端算好的 `why` / `need` / `growth_task` 全被丢掉了。
 *
 * `type_label` 是七类选题库的分类名（痛点型/数字型/对比型…），
 * 比一个 0-100 的分数更能说明「这条选题是什么路子」。
 */
interface Topic {
  id: number | string;
  title?: string;
  /** pain / number / contrast ... 机器值 */
  type?: string;
  /** 痛点型 / 数字型 / 对比型 ... 给人看的 */
  type_label?: string;
  /** 这条选题要完成的增长任务 */
  growth_task?: string;
  /** 它命中的用户需求 */
  need?: string;
  /** 为什么推荐这一条 */
  why?: string;
  source?: string;
  status?: string;
  account_id?: number | null;
  scheduled_for?: string | null;
  created_at?: string;
}

export default function Plan() {
  const navigate = useNavigate();
  const toast = useToast();
  const [adding, setAdding] = useState(false);
  /* 填好的方向和条数切页后还在，不用重填 */
  const [theme, setTheme] = useKeptState("plan|theme", "");
  const [perType, setPerType] = useKeptState("plan|perType", "2");
  /*
   * 生成选题要 6 秒左右（走 LLM），切页会丢状态。
   * 改成读任务：切走再回来，按钮还是"生成中…"，生成的选题也不会被吞掉。
   */
  const task = useTask("topics");
  const busy = task?.status === "running";

  const topics = useQuery(
    () => get("/api/xhs/topics").then((r) => unwrapList<Topic>(r)),
    [],
    { key: "plan|topics" },
  );

  /*
   * 账号：选题生成要落到某个账号名下。
   *
   * 这里原来写死 `account_id: 1`。后端 `_owned_account` 会校验归属，
   * 不是当前用户的账号就抛「账号不存在或无权访问」，整次生成 400。
   * 多账号或 id 不是 1 的环境下，选题功能等于不可用。
   */
  const accountsQ = useQuery(
    () => get<ListEnvelope<{ id: number; platform?: string; status?: string }>>("/api/accounts"),
    [],
    { key: "plan|accounts", staleTime: 60_000 },
  );
  const accountId =
    accountsQ.data?.items?.find(
      (a) => (a.platform ?? "xhs") === "xhs" && a.status === "active",
    )?.id ?? null;

  const items = topics.data?.items ?? [];

  /*
   * 原来这里手输标题调 POST /api/xhs/topics —— 后端这条路只有 GET/PATCH，
   * 实测必回 405「该接口不支持这个请求方式」，选题库从来加不进东西。
   * 后端真正能建选题的是 POST /api/xhs/topics/generate（按方向批量生成）。
   * 实测：use_llm=true 时 6 秒出 6 条通顺标题；false 时是模板拼接，读着不通。
   * 所以这里固定走 LLM，并把"方向"作为唯一输入。
   */
  const generateTopics = async () => {
    if (!theme.trim()) {
      toast.error("先写一个方向，比如「向上管理」");
      return;
    }
    if (!accountId) {
      toast.error("还没绑定账号，选题要先落在一个账号名下");
      return;
    }
    const handle = startTask("topics", "正在生成选题", {
      detail: theme.trim(),
      invalidates: ["plan", "write"],
    });
    if (!handle) {
      toast.info("上一批选题还在生成");
      return;
    }
    try {
      await post("/api/xhs/topics/generate", {
        account_id: accountId,
        theme: theme.trim(),
        per_type: Number(perType) || 2,
        use_llm: true,
        save: true,
      });
      setTheme("");
      setAdding(false);
      handle.finish(undefined, "选题已入库");
      toast.success("选题已生成");
      invalidate("plan");
      invalidate("write");
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "生成失败";
      handle.fail(msg);
      toast.error(msg);
    }
  };

  return (
    <div className="pl">
      <PageHeader
        title="选题"
        subtitle="先攒候选，再挑着写。选题只看角度值不值得写，不看能不能爆。"
        actions={
          <Button
            variant="primary"
            size="sm"
            onClick={() => setAdding((v) => !v)}
          >
            {adding ? "收起" : "生成选题"}
          </Button>
        }
      />

      {/* 新增：给一个方向，AI 按几种类型各出几条 */}
      <div className={`pl__add${adding ? " is-open" : ""}`}>
        <div className="pl__add-inner">
          <Input
            label="写哪个方向"
            placeholder="例如：向上管理、副业起步、职场沟通"
            value={theme}
            onChange={setTheme}
          />
          <Select
            label="每种类型几条"
            value={perType}
            options={[
              { value: "1", label: "1 条" },
              { value: "2", label: "2 条" },
              { value: "3", label: "3 条" },
            ]}
            onChange={setPerType}
          />
          <div className="pl__add-actions">
            <Button
              variant="primary"
              size="sm"
              onClick={generateTopics}
              loading={busy}
            >
              {busy ? "生成中…" : "生成"}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setAdding(false);
                setTheme("");
              }}
            >
              取消
            </Button>
          </div>
          <p className="pl__add-hint">
            会按痛点、数字、对比等几种写法各出几条，生成约需 6 秒。
          </p>
        </div>
      </div>

      {topics.initialLoading ? (
        <SkeletonList rows={5} />
      ) : items.length === 0 ? (
        <EmptyState
          glyph="spark"
          title="还没有选题"
          description="给一个方向，让 AI 按几种常见写法各出几条，你再挑值得写的。有了选题，写稿时可以直接选它当起点。"
          action={
            <>
              <Button variant="primary" onClick={() => setAdding(true)}>
                生成第一批选题
              </Button>
              <Button
                variant="ghost"
                onClick={() => navigate("/assets")}
              >
                从对标找
              </Button>
            </>
          }
        />
      ) : (
        <ul className="pl__list">
          {items.map((t, i) => (
            <li
              className="pl__row"
              key={String(t.id)}
              style={{ ["--i" as string]: Math.min(i, 7) }}
            >
              <div className="pl__main">
                <span className="pl__title">{t.title ?? "未命名选题"}</span>
                {/*
                  角度/理由：后端给的是 why + need + growth_task，不是 angle。
                  以前读 t.angle（永远 undefined），所以这一行永远是空的。
                */}
                {t.why || t.need ? (
                  <span className="pl__angle">{t.why || t.need}</span>
                ) : null}
              </div>
              {t.type_label ? (
                <span className="pl__type">{t.type_label}</span>
              ) : null}
              {t.source ? (
                <span className="pl__source">{t.source}</span>
              ) : null}
              <Button
                size="sm"
                variant="ghost"
                onClick={() =>
                  navigate(
                    `/write?topic=${encodeURIComponent(t.title ?? "")}` +
                      (t.why || t.need
                        ? `&angle=${encodeURIComponent(t.why || t.need || "")}`
                        : ""),
                  )
                }
              >
                用它写
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

