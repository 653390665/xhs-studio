/**
 * Publish.tsx — 发布
 *
 * 子页：队列 / 排期
 *
 * 核心约束：发布始终人工确认。所以这一页没有"一键全发"，
 * 每条都要过一道确认对话框，对话框里明确写出"将发到哪个账号"。
 *
 * 唯一的例外是「设置 → 风险控制」里的「自动发布」开关：打开之后，到点的
 * 排期任务由调度器直接执行，不再等人确认。那条路径在界面文案里必须说清，
 * 不能一边写着"不会自动发"一边到点真发。
 */

import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import { usePageTour } from "../components/useTour";
import { TOUR_PUBLISH } from "../components/tourSteps";
import Button from "../components/Button";
import EmptyState from "../components/EmptyState";
import ConfirmDialog from "../components/ConfirmDialog";
import { SkeletonList } from "../components/Skeleton";
import { Stat, StatRow } from "../components/Stat";
import { useToast } from "../components/Toast";
import { get, post, del, ApiError, type ListEnvelope } from "../lib/api";
import { useQuery, invalidate } from "../lib/query";
import { useSubPath } from "../lib/useSubPath";
import "./Publish.css";

/* ---------------- 类型 ---------------- */

interface PublishJob {
  id: number | string;
  /** 后端字段名是 source_draft_id，不是 draft_id */
  source_draft_id?: number | string;
  platform_account_id?: number | string;
  /** 账号名后端不给，前端用 platform_account_id 对出来 */
  account_name?: string;
  title?: string;
  body?: string;
  publish_mode?: string;
  status?: string;
  scheduled_at?: string;
  created_at?: string;
  published_at?: string;
  /** 失败原因在 publish_error 里，不是 error */
  publish_error?: string;
}

type TabKey = "jobs" | "calendar";

/**
 * 发布任务的状态词表。
 *
 * 必须和后端 `publish_service.py` 实际写的值一致，否则界面会显示英文原文、
 * 统计恒为 0。后端一共写这六个（`grep 'job.status = '` 可核对）：
 *
 *   pending    建了任务，等人工确认
 *   scheduled  排了时间，到点仍需确认（除非开了「自动发布」）
 *   publishing 正在发
 *   published  已发出
 *   failed     失败（原因在 publish_error）
 *   cancelled  人取消了
 *
 * 以前这里写的是 queued / running / success —— 三个后端从来不产出的词，
 * 于是「已发布」「发布中」两张卡片永远是 0，已发布的条目显示英文 `published`。
 *
 * 关于「到点仍需确认」：这句话以前是假的——`run_due_publish_jobs` 无条件
 * 执行到点的排期任务，只是因为 `SCHEDULER_ENABLED=false` 才没出事。现在
 * 无人值守路径要求 `auto_publish_enabled` 打开才发（`scheduler_service.py`
 * 的 `require_auto_publish`），否则任务留在 `pending` 等人按确认。
 */
const STATUS_LABEL: Record<string, { text: string; tone: string }> = {
  pending: { text: "待确认", tone: "warn" },
  scheduled: { text: "已排期", tone: "warn" },
  publishing: { text: "发布中", tone: "warn" },
  published: { text: "已发布", tone: "ok" },
  failed: { text: "失败", tone: "danger" },
  cancelled: { text: "已取消", tone: "muted" },
};

interface Account {
  id: number | string;
  platform?: string;
  status?: string;
  nickname?: string;
  name?: string;
}

/* ---------------- 主组件 ---------------- */

export default function PublishPages() {
  const sub = useSubPath("publish");
  const active = (sub === "calendar" ? "calendar" : "jobs") as TabKey;

  const tour = usePageTour(TOUR_PUBLISH, "publish");

  return (
    <div className="pb">
      <PageHeader
        title={active === "jobs" ? "发布队列" : "排期"}
        subtitle={
          active === "jobs"
            ? "每条都要你点确认才会发。只有开了「自动发布」的排期任务会自己到点发出。"
            : "安排好时间也要到点手动确认；除非你在「设置 → 风险控制」里明确打开「自动发布」。"
        }
        actions={tour.button}
      />

      {/* 队列 / 排期的切换在外壳的 SectionNav 上，这里不再重复画一套 */}
      {active === "jobs" ? <JobQueue /> : <CalendarPanel />}

      {tour.node}
    </div>
  );
}

interface PublishCounts {
  /** 建了任务、等一个人点确认（= pending + scheduled） */
  pending: number;
  /** 正在上传/提交 */
  running: number;
  published: number;
  failed: number;
  cancelled: number;
  total: number;
}

interface PublishJobsPayload {
  items: PublishJob[];
  total: number;
  counts?: PublishCounts;
}

/**
 * 队列和日历共用同一个取数函数（也共用同一个缓存 key）。
 *
 * 两个页面若各自请求，缓存里谁先到就谁的结果——日历那份没有 `counts`，
 * 队列就会退回「数这一页」的旧行为，而且这种 bug 只在切换过页面后出现。
 *
 * `page_size=500`（后端上限）：日历要看整月，一页 20 条会让第 21 条起的
 * 排期从日历上消失，看起来像那天没安排。
 */
function loadPublishJobs(): Promise<PublishJobsPayload> {
  return get<PublishJobsPayload>("/api/publish/jobs?page_size=500").then((r) => ({
    items: Array.isArray(r.items) ? r.items : [],
    total: typeof r.total === "number" ? r.total : 0,
    counts: r.counts,
  }));
}

/* ---------------- 队列 ---------------- */

function JobQueue() {
  const navigate = useNavigate();
  const toast = useToast();

  /*
   * `counts` 由后端整表算出来，前端不再自己数。
   *
   * 自己数有两个坑，而且两个都踩了：
   *   · 后端分页 (page_size 默认 20)，第 21 条起不进统计；
   *   · 「待确认」和「发布中」在列表里是两拨行，数漏一个就让数字和列表打架。
   * 现在数字和列表来自同一个查询，不可能对不上。
   */
  const jobs = useQuery(loadPublishJobs, [], { key: "publish|jobs" });

  /*
   * 后端 publish job 只给 platform_account_id，不给账号名。
   * 之前界面直接读 job.account_name（永远 undefined），
   * 于是每条都显示「未指定账号」——即使是发给已绑定的真实账号。
   * 这里自己把 id 对成昵称。
   */
  const accounts = useQuery(
    () => get<ListEnvelope<Account>>("/api/accounts"),
    ["accounts-for-publish"],
    { staleTime: 60_000 },
  );
  const nameOf = (id?: number | string) => {
    if (id === undefined || id === null) return "未指定账号";
    const a = accounts.data?.items?.find((x) => String(x.id) === String(id));
    return a?.nickname?.trim() || a?.name?.trim() || `账号 ${id}`;
  };

  const [pending, setPending] = useState<PublishJob | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [busyJob, setBusyJob] = useState<string | null>(null);

  const items = useMemo(() => jobs.data?.items ?? [], [jobs.data]);

  const stats = useMemo(() => {
    const counts = jobs.data?.counts;
    // 后端旧版本没有 counts 时退回「数这一页」，至少要能显示
    const count = (s: string) => items.filter((j) => j.status === s).length;
    return {
      pending: counts?.pending ?? count("pending") + count("scheduled"),
      running: counts?.running ?? count("publishing"),
      success: counts?.published ?? count("published"),
      failed: counts?.failed ?? count("failed"),
    };
  }, [jobs.data, items]);

  const confirmPublish = async () => {
    if (!pending) return;
    setConfirming(true);
    try {
      await post(`/api/publish/jobs/${pending.id}/publish`, {});
      toast.success(
        `已提交发布：${pending.title ?? "未命名"} → ${nameOf(pending.platform_account_id)}`,
      );
      invalidate("publish");
      invalidate("overview");
      setPending(null);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "发布失败");
    } finally {
      setConfirming(false);
    }
  };

  const cancelJob = async (job: PublishJob) => {
    try {
      /*
       * 后端这个端点是 POST，不是 DELETE。
       * 之前写成 del() 会拿到 405「该接口不支持这个请求方式」，取消永远失败。
       */
      await post(`/api/publish/jobs/${job.id}/cancel`, {});
      toast.success("已取消这条发布");
      invalidate("publish");
      invalidate("overview");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "取消失败");
    }
  };

  /*
   * 失败 / 已取消的 job 以前没有任何出口：既不能重试，也不能删掉。
   * 它们会永远躺在队列里，而「失败」那张卡片只会越堆越高。
   *
   * 后端两个端点一直都在（`POST /jobs/{id}/retry`、`DELETE /jobs/{id}`），
   * 前端零调用——这一类「做得出来但没有按钮」是这次审查里最常见的一类。
   */
  const retryJob = async (job: PublishJob) => {
    setBusyJob(String(job.id));
    try {
      await post(`/api/publish/jobs/${job.id}/retry`, {});
      toast.success("已放回待确认，确认后才会发出去");
      invalidate("publish");
      invalidate("overview");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "重试失败");
    } finally {
      setBusyJob(null);
    }
  };

  const deleteJob = async (job: PublishJob) => {
    setBusyJob(String(job.id));
    try {
      await del(`/api/publish/jobs/${job.id}`);
      toast.success("已从队列移除");
      invalidate("publish");
      invalidate("overview");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "删除失败");
    } finally {
      setBusyJob(null);
    }
  };

  if (jobs.initialLoading) return <SkeletonList rows={5} />;

  /*
   * 读不到就明说。
   *
   * 以前只判 `items.length === 0`，接口失败也落进「还没有要发的稿子」——
   * 用户看到的是「你还没写」，实际是「这次没读到」，两种结论差得很远。
   */
  if (jobs.error) {
    return (
      <EmptyState
        glyph="calendar"
        title="读不到发布队列"
        description={`后端返回：${jobs.error.message}`}
        action={
          <Button variant="primary" onClick={() => jobs.refetch()}>
            重试
          </Button>
        }
      />
    );
  }

  if (items.length === 0) {
    return (
      <EmptyState
        glyph="calendar"
        title="还没有要发的稿子"
        description="先把一篇草稿确认好，再排进这里。这里每一条都要你亲手点确认才会真的发出去，没确认前随时能改。"
        action={
          <>
            <Button variant="primary" onClick={() => navigate("/write")}>
              写第一篇
            </Button>
            <Button variant="ghost" onClick={() => navigate("/write")}>
              看已有草稿
            </Button>
          </>
        }
        extra={
          <div className="pb__promise">
            发布是唯一会对外的动作。默认没有任何"自动发"的开关；
            只有在「设置 → 风险控制」里明确打开「自动发布」，到点任务才会自己发。
          </div>
        }
      />
    );
  }

  return (
    <div>
      <StatRow data-tour="publish-stats">
        <Stat
          label="待确认"
          value={stats.pending}
          unit="条"
          tone={stats.pending > 0 ? "warn" : "default"}
          hint="等你按确认"
        />
        <Stat label="发布中" value={stats.running} unit="条" />
        <Stat label="已发布" value={stats.success} unit="条" tone="ok" />
        <Stat
          label="失败"
          value={stats.failed}
          unit="条"
          tone={stats.failed > 0 ? "danger" : "default"}
        />
      </StatRow>

      <ul className="pq" data-tour="publish-list">
        {items.map((job) => {
          const st = STATUS_LABEL[job.status ?? "pending"] ?? {
            // 后端加了新状态而前端还没跟上时，别把英文原文丢给用户
            text: "状态未知",
            tone: "muted",
          };
          /*
           * 需要人动手的状态：pending（还没发）、scheduled（到点了，等你确认）。
           * `publishing` 正在跑，`published` 已完成，都不该再有确认按钮。
           */
          const needsConfirm =
            job.status === "pending" || job.status === "scheduled";

          return (
            <li className="pq__row" key={String(job.id)}>
              <div className="pq__main">
                <span className="pq__title">{job.title ?? "未命名草稿"}</span>
                <span className="pq__meta">
                  发到 {nameOf(job.platform_account_id)}
                  {job.scheduled_at
                    ? ` · 计划 ${job.scheduled_at.replace("T", " ").slice(0, 16)}`
                    : ""}
                </span>
                {job.publish_error ? (
                  <span className="pq__error">{job.publish_error}</span>
                ) : null}
              </div>

              <span className={`pq__status pq__status--${st.tone}`}>
                {st.text}
              </span>

              {needsConfirm ? (
                <div className="pq__actions">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => cancelJob(job)}
                  >
                    取消
                  </Button>
                  <Button
                    size="sm"
                    variant="primary"
                    onClick={() => setPending(job)}
                  >
                    确认发布
                  </Button>
                </div>
              ) : job.status === "failed" || job.status === "cancelled" ? (
                /*
                 * 失败 / 取消的必须有出口。以前这两种状态在界面上是死路：
                 * 没有确认按钮（不该再发），也没有重试/删除（后端有端点但没人调），
                 * 于是队列里越堆越多，用户只能看着。
                 */
                <div className="pq__actions">
                  <Button
                    size="sm"
                    variant="ghost"
                    loading={busyJob === String(job.id)}
                    onClick={() => retryJob(job)}
                  >
                    重试
                  </Button>
                  <Button
                    size="sm"
                    variant="danger"
                    loading={busyJob === String(job.id)}
                    onClick={() => deleteJob(job)}
                  >
                    删除
                  </Button>
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>

      {/* 危险确认：说清发到哪、发什么 */}
      <ConfirmDialog
        open={Boolean(pending)}
        title="确认发布这条内容？"
        danger
        loading={confirming}
        confirmLabel="确认发布"
        cancelLabel="再想想"
        onCancel={() => setPending(null)}
        onConfirm={confirmPublish}
        description={
          <>
            发布后内容会立刻出现在小红书上，撤回需要到平台手动删除。
          </>
        }
      >
        <dl className="pq__confirm">
          <dt>内容</dt>
          <dd>{pending?.title ?? "未命名草稿"}</dd>
          <dt>账号</dt>
          <dd>{nameOf(pending?.platform_account_id)}</dd>
          <dt>时间</dt>
          <dd>
            {pending?.scheduled_at
              ? pending.scheduled_at.replace("T", " ").slice(0, 16)
              : "立即发布"}
          </dd>
        </dl>
      </ConfirmDialog>
    </div>
  );
}

/* ---------------- 排期日历 ---------------- */

function CalendarPanel() {
  const navigate = useNavigate();
  const [monthOffset, setMonthOffset] = useState(0);

  const jobs = useQuery(loadPublishJobs, [], { key: "publish|jobs" });

  const now = new Date();
  const base = new Date(now.getFullYear(), now.getMonth() + monthOffset, 1);
  const year = base.getFullYear();
  const month = base.getMonth();

  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const firstWeekday = new Date(year, month, 1).getDay(); // 0=周日

  // 按日期归组
  const byDay = useMemo(() => {
    const map = new Map<number, PublishJob[]>();
    for (const j of jobs.data?.items ?? []) {
      const raw = j.scheduled_at ?? j.created_at;
      if (!raw) continue;
      const d = new Date(raw);
      if (d.getFullYear() !== year || d.getMonth() !== month) continue;
      const list = map.get(d.getDate()) ?? [];
      list.push(j);
      map.set(d.getDate(), list);
    }
    return map;
  }, [jobs.data, year, month]);

  const cells: Array<number | null> = [
    ...Array.from({ length: firstWeekday }, () => null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ];

  return (
    <div className="cal">
      <div className="cal__bar">
        <div className="cal__nav">
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setMonthOffset((m) => m - 1)}
          >
            ←
          </Button>
          <span className="cal__month">
            {year} 年 {month + 1} 月
          </span>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setMonthOffset((m) => m + 1)}
          >
            →
          </Button>
          {monthOffset !== 0 ? (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setMonthOffset(0)}
            >
              回到本月
            </Button>
          ) : null}
        </div>
        <span className="cal__hint">
          排期只是计划。只有「设置 → 风险控制 → 自动发布」打开且调度器在运行时，
          到点才会自动发出；否则仍需你在这里确认
        </span>
      </div>

      {jobs.initialLoading ? (
        <SkeletonList rows={4} />
      ) : (
        <>
          <div className="cal__weekdays" aria-hidden="true">
            {["日", "一", "二", "三", "四", "五", "六"].map((w) => (
              <span key={w}>{w}</span>
            ))}
          </div>

          <div className="cal__grid">
            {cells.map((day, i) => {
              if (day === null) {
                return <div className="cal__cell is-empty" key={`e${i}`} />;
              }
              const dayJobs = byDay.get(day) ?? [];
              const isToday =
                monthOffset === 0 && day === now.getDate();

              return (
                <div
                  className={`cal__cell${isToday ? " is-today" : ""}`}
                  key={day}
                >
                  <span className="cal__day">{day}</span>
                  {dayJobs.length > 0 ? (
                    <ul className="cal__items">
                      {dayJobs.slice(0, 3).map((j) => (
                        <li
                          className={`cal__item cal__item--${
                            STATUS_LABEL[j.status ?? "pending"]?.tone ?? "muted"
                          }`}
                          key={String(j.id)}
                        >
                          {(j.title ?? "未命名").slice(0, 12)}
                        </li>
                      ))}
                      {dayJobs.length > 3 ? (
                        <li className="cal__more">
                          还有 {dayJobs.length - 3} 条
                        </li>
                      ) : null}
                    </ul>
                  ) : null}
                </div>
              );
            })}
          </div>

          {(jobs.data?.items ?? []).length === 0 ? (
            <EmptyState
              compact
              glyph="calendar"
              title="这个月还没有待发的稿子"
              description="这里只展示已经送进队列的稿子，暂时不能在日历里改发布时间。要发新稿，先去写稿页确认草稿，再送回发布队列。"
              action={
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => navigate("/write")}
                >
                  去写稿
                </Button>
              }
            />
          ) : null}
        </>
      )}
    </div>
  );
}
