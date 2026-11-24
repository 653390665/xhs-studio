/**
 * RiskControls.tsx — 风险开关
 *
 * `GET/PUT /api/settings/risk-controls` 存在很久了，前端零调用。
 * 后果不是「少一个设置页」，而是**后端有四个开关默认关、关掉就永远关着**：
 * 批量改写、自动发布、复制来源图片、自动建待发布任务——用户在界面上
 * 找不到任何地方能打开它，只能读代码。
 *
 * 设计上的两个约束：
 *   1. 高风险开关要 `acknowledge_risk=true` 才肯存。后端会 400 并说明要确认
 *      哪些项，所以这里把「确认」做成一次显式的勾选，不是弹窗点「我知道了」。
 *   2. `auto_engagement_enabled` 是保留项（自动私信/评论），后端直接拒绝。
 *      界面上要显示成「暂未开放」，不能给一个点了报错的开关。
 */

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Button from "./Button";
import { SkeletonList } from "./Skeleton";
import { useToast } from "./Toast";
import { ApiError, get, put } from "../lib/api";
import { invalidate, useQuery } from "../lib/query";
import { useKeptState } from "../lib/formState";
import "./RiskControls.css";

interface RiskPayload {
  auto_ops_enabled: boolean;
  competitor_rewrite_enabled: boolean;
  copy_source_images_enabled: boolean;
  auto_create_publish_job_enabled: boolean;
  auto_publish_enabled: boolean;
  auto_engagement_enabled: boolean;
  matrix_mode_enabled: boolean;
  batch_repost_enabled: boolean;
  updated_at?: string;
  reserved_fields?: string[];
  labels?: Record<string, string>;
}

/** 每个开关说清「打开之后会发生什么」。只给名字等于让人盲选。 */
const RISK_HINTS: Record<string, string> = {
  auto_ops_enabled:
    "允许定时任务按关键词自动采集对标并改写。入口在「设置 › 自动运营」。",
  competitor_rewrite_enabled:
    "允许把别人的笔记改写成自己的稿子。会保留核心信息、重写表达。",
  copy_source_images_enabled:
    "改写时把来源笔记的图片也保存下来。图不是自己的，商用前要确认授权。" +
    "关掉时自动运营会在生成草稿后停下，不会建发布任务。",
  auto_create_publish_job_enabled:
    "改写完成后自动创建一条待发布任务（仍然不会自己发出去）。",
  auto_publish_enabled:
    "到点自动发布，不再等人确认。这是唯一会真的把内容发出去的开关。" +
    "需要调度器在运行（见下方状态）。每账号每天最多 3 条、两条之间至少 60 分钟，" +
    "被限额挡住的会留在队列里等你处理。",
  auto_engagement_enabled: "自动私信、自动评论。平台明确禁止，暂不开放。",
  matrix_mode_enabled:
    "把同一个选题写成几个账号的不同版本。入口在「设置 › 账号矩阵」，至少要两个账号。",
  batch_repost_enabled:
    "一次给多篇旧稿换标题重发。入口在「素材 › 样本库」：勾几篇后点「改写成草稿」。" +
    "只产草稿，不建发布任务。",
};

/**
 * 这个开关守着的那条链路，界面上有没有入口。
 *
 * 为什么必须写出来：这些开关守着三条链路，界面上有没有前门决定了
 * 「打开这个开关会不会有可观察的变化」。没有前门的开关不是假开关
 * （后端真的会拦），但它守着一间没有门的房间，用户打开之后什么也不会发生。
 *
 * 2026-11-18 之前这条注释写的是「一个入口都没有」——那时候是真的：
 * `/api/auto-tasks` 调用 0 次、`/api/matrix` 0 次、`batch-rewrite-drafts` 0 次。
 * 现在三条都接上了，标签必须跟着改，否则界面在说反话：
 *
 *   · 自动运营      → 设置 → 自动运营
 *   · 账号矩阵      → 设置 → 账号矩阵
 *   · 批量改写      → 素材 → 样本库 → 勾几篇 → 改写成草稿
 *   · 自动发布      → 排期调度器
 *
 * `copy_source_images_enabled` 与 `auto_create_publish_job_enabled` 没有独立
 * 页面（它们是自动运营的两个子开关），但确实会影响自动运营的行为，
 * 所以不写「尚无入口」。
 *
 * `path` 非空时标签是**真链接**。只写文字不给路径的话，用户看到
 * 「设置 › 自动运营」却点不动，还得自己去侧栏找——那和没写入口差不多。
 */
const RISK_WIRED: Record<string, { label: string; path?: string }> = {
  auto_ops_enabled: { label: "设置 › 自动运营", path: "/settings/auto-ops" },
  competitor_rewrite_enabled: { label: "设置 › 自动运营", path: "/settings/auto-ops" },
  copy_source_images_enabled: { label: "自动运营的子开关", path: "/settings/auto-ops" },
  auto_create_publish_job_enabled: { label: "自动运营的子开关", path: "/settings/auto-ops" },
  auto_publish_enabled: { label: "已接调度器", path: "#scheduler" },
  auto_engagement_enabled: { label: "未开放" },
  matrix_mode_enabled: { label: "设置 › 账号矩阵", path: "/settings/matrix" },
  batch_repost_enabled: { label: "样本库 › 改写成草稿", path: "/assets/library" },
};

/** 开关顺序：从「只是采集」到「会发出去」 */
const RISK_ORDER: string[] = [
  "auto_ops_enabled",
  "competitor_rewrite_enabled",
  "copy_source_images_enabled",
  "auto_create_publish_job_enabled",
  "batch_repost_enabled",
  "matrix_mode_enabled",
  "auto_publish_enabled",
  "auto_engagement_enabled",
];

interface SchedulerStatusPayload {
  enabled: boolean;
  running: boolean;
  interval_seconds: number;
  /** 环境变量指定了状态时，界面改不动 */
  editable?: boolean;
}

/**
 * 调度器开关与状态。
 *
 * `GET/PUT /api/settings/scheduler` 是这一轮新加的：之前 `scheduler.enabled`
 * 只能改 `config/default.yaml` 或设 `SCHEDULER_ENABLED=true`，两者在界面上
 * 都够不着。于是「自动发布」这个开关无论怎么点，调度器都没在跑，一次也不会发。
 *
 * 这一行同时承担「解释」：用户看到「调度器：未运行」就知道为什么开了自动发布
 * 也没动静，而不是去猜。
 */
function SchedulerStatus() {
  const toast = useToast();
  const q = useQuery(
    () => get<SchedulerStatusPayload>("/api/settings/scheduler"),
    [],
    { key: "settings|scheduler", staleTime: 10_000 },
  );
  const [busy, setBusy] = useState(false);

  if (q.initialLoading) return null;
  if (q.error) {
    return <p className="rc__err">读不到调度器状态：{q.error.message}</p>;
  }
  const s = q.data;
  if (!s) return null;

  const running = Boolean(s.running);
  const editable = s.editable !== false;

  async function toggle(next: boolean) {
    setBusy(true);
    try {
      await put<SchedulerStatusPayload>("/api/settings/scheduler", {
        enabled: next,
      });
      toast.success(next ? "调度器已启动" : "调度器已停止");
      invalidate("settings|scheduler");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={`rc__sched${running ? "" : " is-off"}`}>
      <span className="rc__schedDot" aria-hidden="true" />
      <span className="rc__schedText">
        <strong>调度器：{running ? "运行中" : "未运行"}</strong>
        {running ? (
          <span>{`每 ${s.interval_seconds} 秒检查一次排期。到点任务会直接发出去。`}</span>
        ) : (
          <span>
            排期任务不会自己发，到点后仍需你在「发布」页确认。
            {editable ? "" : "（当前部署用环境变量指定了调度器状态，界面改不了。）"}
          </span>
        )}
      </span>
      <Button
        size="sm"
        variant={running ? "ghost" : "secondary"}
        loading={busy}
        disabled={!editable}
        onClick={() => void toggle(!running)}
      >
        {running ? "停止调度器" : "启动调度器"}
      </Button>
    </div>
  );
}

export default function RiskControls() {
  const toast = useToast();
  const q = useQuery(() => get<RiskPayload>("/api/settings/risk-controls"), [], {
    key: "settings|risk",
    staleTime: 30_000,
  });

  const [draft, setDraft] = useState<Record<string, boolean>>({});
  const [ack, setAck] = useKeptState("settings|risk-ack", false);
  const [saving, setSaving] = useState(false);

  const data = q.data;
  const reserved = new Set(data?.reserved_fields ?? []);

  // 首次加载（或服务端刷新）时把值灌进本地草稿；
  // 之后用户改动不回灌，否则每次 refetch 会把未保存的勾选抹掉。
  const [seeded, setSeeded] = useState(false);
  useEffect(() => {
    if (!data || seeded) return;
    const next: Record<string, boolean> = {};
    for (const key of RISK_ORDER) {
      next[key] = Boolean((data as unknown as Record<string, unknown>)[key]);
    }
    setDraft(next);
    setSeeded(true);
  }, [data, seeded]);

  const label = (key: string) => data?.labels?.[key] ?? key;

  async function save() {
    setSaving(true);
    try {
      // 只发改过的项：全量 PUT 会把并发改的另一项覆盖回去
      const changed: Record<string, boolean> = {};
      for (const key of RISK_ORDER) {
        const before = Boolean((data as unknown as Record<string, unknown> | undefined)?.[key]);
        if (draft[key] !== before) changed[key] = draft[key];
      }
      if (Object.keys(changed).length === 0) {
        toast.info("没有改动");
        return;
      }
      await put<RiskPayload>("/api/settings/risk-controls", {
        ...changed,
        acknowledge_risk: ack,
      });
      toast.success("已保存");
      setAck(false);
      setSeeded(false);
      invalidate("settings|risk");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  if (q.initialLoading) return <SkeletonList rows={4} />;

  if (q.error) {
    return (
      <p className="rc__err">
        读不到风险开关：{q.error.message}
      </p>
    );
  }

  const dirty = RISK_ORDER.some((key) => {
    const before = Boolean((data as unknown as Record<string, unknown> | undefined)?.[key]);
    return draft[key] !== before;
  });
  const enabling = RISK_ORDER.some((key) => {
    const before = Boolean((data as unknown as Record<string, unknown> | undefined)?.[key]);
    return draft[key] && !before;
  });

  return (
    <div className="rc">
      <p className="rc__lead">
        这些开关默认全关。打开意味着「让系统替你做决定」，每一步的风险由你承担。
        其中只有「自动发布」会把内容真的发出去，其余只影响草稿和队列。
      </p>

      {/*
        这段说明的存在理由：这 8 个开关里，有几个守的功能确实还没做，
        有几个已经接上了。不分开说，用户两种误解都会发生——
        要么以为「开了也没用」，要么以为「开了就自动发」。
      */}
      <div className="rc__wired" id="scheduler">
        <strong>开关守着的功能，大部分已经接上界面。</strong>
        <span>
          每一行后面那个标签写着入口在哪，点一下直接过去。没写入口的
          （自动私信/评论）还没开放。
        </span>
        <span>
          「自动发布」是唯一会真的把内容发出去的开关。它还需要调度器在运行
          （见下面那行），两个条件都满足时，到点的排期任务才会自己发出。
        </span>
      </div>

      <SchedulerStatus />

      <ul className="rc__list">
        {RISK_ORDER.map((key) => {
          const isReserved = reserved.has(key);
          const on = Boolean(draft[key]);
          const wired = RISK_WIRED[key] ?? "";
          return (
            <li className={`rc__row${isReserved ? " is-reserved" : ""}`} key={key}>
              <label className="rc__label">
                <input
                  type="checkbox"
                  checked={on}
                  disabled={isReserved}
                  onChange={(e) =>
                    setDraft((prev) => ({ ...prev, [key]: e.target.checked }))
                  }
                />
                <span className="rc__text">
                  <span className="rc__name">
                    {label(key)}
                    {isReserved ? (
                      <span className="rc__tag">暂未开放</span>
                    ) : wired ? (
                      wired.path?.startsWith("#") ? (
                        <button
                          type="button"
                          className="rc__tag rc__tag--wired rc__tag--link"
                          title="跳到下面的调度器状态"
                          onClick={(e) => {
                            /*
                             * 不能用 href="#scheduler"：那会往历史里塞一条
                             * 带 hash 的记录，且 React Router 不会处理滚动。
                             * 这里直接滚，不产生导航。
                             */
                            e.preventDefault();
                            e.stopPropagation();
                            const id = (wired.path ?? "").slice(1);
                            if (id) {
                              document
                                .getElementById(id)
                                ?.scrollIntoView({ behavior: "smooth", block: "center" });
                            }
                          }}
                        >
                          {wired.label} ↓
                        </button>
                      ) : wired.path ? (
                        <Link
                          className="rc__tag rc__tag--wired rc__tag--link"
                          to={wired.path}
                          title={`打开：${wired.label}`}
                          onClick={(e) => e.stopPropagation()}
                        >
                          {wired.label} ↗
                        </Link>
                      ) : (
                        <span className="rc__tag rc__tag--wired">
                          {wired.label}
                        </span>
                      )
                    ) : null}
                  </span>
                  <span className="rc__hint">{RISK_HINTS[key] ?? ""}</span>
                </span>
              </label>
            </li>
          );
        })}
      </ul>

      {enabling ? (
        <label className="rc__ack">
          <input
            type="checkbox"
            checked={ack}
            onChange={(e) => setAck(e.target.checked)}
          />
          <span>
            我确认这些开关的风险（账号被限流、内容被判搬运、平台封禁），
            由我自行承担。
          </span>
        </label>
      ) : null}

      <div className="rc__actions">
        <Button
          variant="primary"
          loading={saving}
          disabled={!dirty || (enabling && !ack)}
          onClick={() => void save()}
        >
          保存
        </Button>
        {!dirty ? (
          <span className="rc__saved">
            {data?.updated_at
              ? `上次修改 ${data.updated_at.replace("T", " ").slice(0, 16)}`
              : "还没有改过"}
          </span>
        ) : null}
      </div>
    </div>
  );
}
