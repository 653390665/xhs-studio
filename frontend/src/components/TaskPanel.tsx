/**
 * TaskPanel.tsx — 后端任务清单（失败原因能查到）
 *
 * 为什么单独做一页：`/api/tasks` 那一套端点存在很久了，前端一次都没调过。
 * 于是「生成初稿失败」这种事的原始错误只活在 toast 里——3 秒后消失，
 * 刷新更是什么都不剩。而库里 `tasks` 表有每一条的 error_type、payload.error
 * 和耗时。
 *
 * 这里不做「任务中心」那种大盘：只列最近的、能重试能取消，够排错就行。
 */

import { useMemo, useState } from "react";
import Button from "./Button";
import EmptyState from "./EmptyState";
import { SkeletonList } from "./Skeleton";
import { useToast } from "./Toast";
import { invalidate, useQuery } from "../lib/query";
import {
  TASK_STATUS_LABEL,
  cancelTask,
  getTasks,
  retryTask,
  taskDurationMs,
  taskError,
  taskTypeLabel,
} from "../lib/backendTasks";
import "./TaskPanel.css";

type Filter = "all" | "failed" | "running";

const FILTER_LABEL: Record<Filter, string> = {
  all: "全部",
  failed: "失败",
  running: "进行中",
};

export default function TaskPanel() {
  const toast = useToast();
  const [filter, setFilter] = useState<Filter>("all");
  const [busy, setBusy] = useState<number | null>(null);

  const q = useQuery(() => getTasks(60), [], {
    key: "settings|backend-tasks",
    staleTime: 10_000,
  });

  const items = useMemo(() => q.data?.items ?? [], [q.data]);

  const visible = useMemo(() => {
    if (filter === "failed") {
      return items.filter((t) => t.status === "failed" || t.status === "exhausted");
    }
    if (filter === "running") {
      return items.filter((t) => t.status === "running" || t.status === "pending");
    }
    return items;
  }, [items, filter]);

  const failedCount = items.filter(
    (t) => t.status === "failed" || t.status === "exhausted",
  ).length;

  async function onRetry(id: number) {
    setBusy(id);
    try {
      await retryTask(id);
      toast.success("已重新排队");
      invalidate("settings|backend-tasks");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "重试失败");
    } finally {
      setBusy(null);
    }
  }

  async function onCancel(id: number) {
    setBusy(id);
    try {
      await cancelTask(id);
      toast.success("已取消");
      invalidate("settings|backend-tasks");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "取消失败");
    } finally {
      setBusy(null);
    }
  }

  if (q.initialLoading) return <SkeletonList rows={4} />;

  if (q.error) {
    return (
      <EmptyState
        glyph="stack"
        title="读不到任务记录"
        description={`后端返回：${q.error.message}`}
        action={
          <Button variant="primary" onClick={() => q.refetch()}>
            重试
          </Button>
        }
      />
    );
  }

  return (
    <div className="tsk">
      <div className="tsk__bar">
        <div className="tsk__filters" role="group" aria-label="筛选任务">
          {(["all", "failed", "running"] as Filter[]).map((key) => (
            <button
              key={key}
              type="button"
              className={`tsk__chip${filter === key ? " is-on" : ""}`}
              aria-pressed={filter === key}
              onClick={() => setFilter(key)}
            >
              {FILTER_LABEL[key]}
              {key === "failed" && failedCount > 0 ? (
                <span className="tsk__chipN">{failedCount}</span>
              ) : null}
            </button>
          ))}
        </div>
        <span className="tsk__count">
          {visible.length} / {items.length} 条
        </span>
      </div>

      {visible.length === 0 ? (
        <EmptyState
          compact
          glyph="flow"
          title={filter === "all" ? "还没有任务记录" : `没有${FILTER_LABEL[filter]}的任务`}
          description="生成、润色、发布、采集都会在这里留一条记录，带耗时和失败原因。"
        />
      ) : (
        <ul className="tsk__list">
          {visible.map((task) => {
            const st = TASK_STATUS_LABEL[task.status] ?? {
              text: task.status,
              tone: "muted",
            };
            const error = taskError(task);
            const ms = taskDurationMs(task);
            const retryable =
              task.status === "failed" || task.status === "exhausted";
            const cancellable =
              task.status === "running" || task.status === "pending";

            return (
              <li className="tsk__row" key={task.id}>
                <div className="tsk__rowMain">
                  <span className="tsk__id">#{task.id}</span>
                  <span className="tsk__type">{taskTypeLabel(task.task_type)}</span>
                  <span className={`tsk__status is-${st.tone}`}>{st.text}</span>
                  <span className="tsk__meta">
                    {(task.created_at ?? "").replace("T", " ").slice(5, 16)}
                    {ms !== null ? ` · ${(ms / 1000).toFixed(1)}s` : ""}
                    {task.retry_count > 0 ? ` · 重试 ${task.retry_count}` : ""}
                  </span>
                  <span className="tsk__actions">
                    {retryable ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        loading={busy === task.id}
                        onClick={() => void onRetry(task.id)}
                      >
                        重试
                      </Button>
                    ) : null}
                    {cancellable ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        loading={busy === task.id}
                        onClick={() => void onCancel(task.id)}
                      >
                        取消
                      </Button>
                    ) : null}
                  </span>
                </div>
                {/*
                  失败原因必须展开显示，不能只藏在 tooltip 里：
                  用户来这里的目的就是看「为什么失败」。
                */}
                {error ? (
                  <p className="tsk__error" title={error}>
                    {error}
                  </p>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}

      <p className="tsk__note">
        说明：这里列的是后端 `tasks` 表里的记录。发布、抖音提取等有自己页面的
        任务不会重复出现在这里，去对应板块看更完整。
      </p>
    </div>
  );
}
