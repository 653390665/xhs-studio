/**
 * Settings.tsx — 设置
 *
 * 子页：账号 / 模型 / 数据源 / 运行记录
 *
 * 原则：只显示后端真实返回的状态。没有成本/用量端点就不编造数字，
 * 用 health、RedFox 配置状态、近 7 天 API 错误数代替。
 */

import { useState } from "react";
import PageHeader from "../components/PageHeader";
import Button from "../components/Button";
import EmptyState from "../components/EmptyState";
import { SkeletonList } from "../components/Skeleton";
import { Stat, StatRow } from "../components/Stat";
import { useToast } from "../components/Toast";
import { get, unwrapList } from "../lib/api";
import { apiBaseLabel } from "../lib/base";
import { fetchDiagnostics } from "../lib/diagnostics";
import { useQuery, invalidate } from "../lib/query";
import { useSubPath } from "../lib/useSubPath";
import QrLogin from "../components/QrLogin";
import ModelSetup from "../components/ModelSetup";
import ImageModelSetup from "../components/ImageModelSetup";
import PositioningPanel from "../components/PositioningPanel";
import SearchSetup from "../components/SearchSetup";
import RiskControls from "../components/RiskControls";
import TaskPanel from "../components/TaskPanel";
import AutoOpsPanel from "../components/AutoOpsPanel";
import MatrixPanel from "../components/MatrixPanel";
import "./Settings.css";

/*
 * 三个面板，不是四个。
 * 原「数据源」和「运行记录」内容重叠（都在报 RedFox / 热榜状态），
 * 合并成「运行状态」一页：后端健康 + 数据源 + 最近错误。
 * 顺序按用户实际会做的事排：先配模型（AI 总开关），再绑账号，最后才看状态。
 */
type TabKey =
  | "models"
  | "image"
  | "accounts"
  | "positioning"
  | "auto-ops"
  | "matrix"
  | "status"
  | "risk";

const SUB_MAP: Record<string, TabKey> = {
  models: "models",
  image: "image",
  accounts: "accounts",
  positioning: "positioning",
  "auto-ops": "auto-ops",
  matrix: "matrix",
  status: "status",
  risk: "risk",
  // 老链接仍然可访问，落到合并后的页面
  sources: "status",
  diagnostics: "status",
};

export default function SettingsPage() {
  const sub = useSubPath("settings");
  const active = SUB_MAP[sub] ?? "models";

  return (
    <div className="st">
      <PageHeader
        title="设置"
        subtitle="先配模型，再绑账号。两件都办好，全部功能可用。"
      />

      {/* 五个子页的切换在外壳的 SectionNav 上（见 src/app/navigation.ts），
          这里不再画第二排标签——两条一样的横线会让人不知道点哪条 */}

      {active === "models" ? (
        <>
          <ModelSetup />
          {/*
            检索说明挂在模型页。
            它只服务「素材 → 找资料」（外部搜索），和「采集」用的账号 cookie
            是两把完全不同的钥匙。检索现在由后端用默认文本模型的网关代发，
            所以放在模型页才讲得通——这里已经没有单独的搜索 Key 了。
          */}
          <section className="st__sec">
            <h2 className="st__sec-title">找资料用的检索</h2>
            <p className="st__sec-hint">
              只有「素材 → 找资料」用它（走外部搜索，每条结果带来源链接）。
              检索和提炼、写稿共用同一个默认文本模型的网关，不用单独配 Key。
              「素材 → 采集」用的是账号登录态，不需要这一项。
            </p>
            <SearchSetup />
          </section>
        </>
      ) : null}
      {active === "image" ? <ImageModelSetup /> : null}
      {active === "accounts" ? (
        <AccountsPanel
          /*
           * 绑定入口默认勾上「同时获取创作中心账号」。
           *
           * 不勾的话，自动运营那条链路建不出任务（要 pc + creator 两个 id），
           * 而用户在「设置 → 账号」这一页看不出还缺一个身份。
           */
          defaultSyncCreator
        />
      ) : null}
      {active === "positioning" ? <PositioningPanel /> : null}
      {active === "auto-ops" ? <AutoOpsPanel /> : null}
      {active === "matrix" ? <MatrixPanel /> : null}
      {active === "status" ? (
        <>
          <SourcesPanel />
          <DiagnosticsPanel />
          {/*
            任务记录：/api/tasks 这一套端点前端零调用，于是「生成失败」的
            原始原因只活在 toast 里，3 秒后消失。放在运行状态页而不是
            单开一个入口：排错时它和「接口错误」是同一个动作。
          */}
          <section className="st__sec">
            <h2 className="st__sec-title">任务记录</h2>
            <TaskPanel />
          </section>
        </>
      ) : null}
      {active === "risk" ? <RiskControls /> : null}
    </div>
  );
}

/* ---------------- 账号 ---------------- */

interface Account {
  id: number | string;
  nickname?: string;
  platform?: string;
  /** pc = 站内账号；creator = 创作中心（发布要用） */
  sub_type?: string;
  status?: string;
  healthy?: boolean;
  last_checked?: string;
}

function AccountsPanel({ defaultSyncCreator = false }: { defaultSyncCreator?: boolean } = {}) {
  const toast = useToast();
  const [qrOpen, setQrOpen] = useState(false);
  const accounts = useQuery(
    () => get("/api/accounts").then((r) => unwrapList<Account>(r)),
    [],
    { key: "settings|accounts" },
  );

  const items = accounts.data?.items ?? [];
  const creatorCount = items.filter((a) => a.sub_type === "creator").length;
  const pcCount = items.filter((a) => (a.sub_type ?? "pc") === "pc").length;

  if (accounts.initialLoading) return <SkeletonList rows={3} />;

  if (items.length === 0) {
    return (
      <>
        <EmptyState
          glyph="flow"
          title="还没有绑定小红书账号"
          description="扫一下码就绑好了。绑定后采集能带上登录态，也能基于自己的笔记做复盘。"
          action={
            <Button variant="primary" onClick={() => setQrOpen(true)}>
              扫码绑定
            </Button>
          }
        />
        <QrLogin
          open={qrOpen}
          syncCreator={defaultSyncCreator}
          onClose={() => setQrOpen(false)}
          onSuccess={() => {
            toast.success("账号已绑定");
            invalidate("settings|accounts");
          }}
        />
      </>
    );
  }

  return (
    <>
      <ul className="st__list">
        {items.map((a) => (
          <li className="st__row" key={String(a.id)}>
            <div className="st__row-main">
              <span className="st__row-title">
                {a.nickname ?? `账号 ${a.id}`}
                {a.sub_type === "creator" ? (
                  <span className="st__kind">创作中心</span>
                ) : null}
              </span>
              <span className="st__row-meta">
                {a.platform ?? "xiaohongshu"}
                {a.last_checked ? ` · 检查于 ${a.last_checked.slice(0, 16)}` : ""}
              </span>
            </div>
            <span
              className={`st__dot ${a.healthy ? "is-on" : "is-off"}`}
              aria-label={a.healthy ? "登录态正常" : "登录态异常"}
            />
            <span className="st__row-status">{a.status ?? "未知"}</span>
          </li>
        ))}
      </ul>

      {/*
        创作中心账号不是「另一个登录」，是同一份 cookie 换出来的身份。
        少了它，自动运营建不了任务（要 pc + creator 两个 id）。
        所以这里显式说「缺一个」，而不是让用户去别处猜。
      */}
      {creatorCount === 0 ? (
        <div className="st__note">
          还没有创作中心账号。自动运营要它来承接发布（{pcCount} 个 PC 账号
          已经够搜索用）。点「再绑一个」时勾上「同时获取创作中心账号」，
          它会用同一个手机号换一个 creator 身份，不用另扫一次。
        </div>
      ) : null}

      <div className="st__accountActs">
        <Button size="sm" variant="secondary" onClick={() => setQrOpen(true)}>
          再绑一个
        </Button>
      </div>

      <QrLogin
        open={qrOpen}
        syncCreator={defaultSyncCreator}
        onClose={() => setQrOpen(false)}
        onSuccess={() => {
          toast.success("账号已绑定");
          invalidate("settings|accounts");
        }}
      />
    </>
  );
}

/* ---------------- 模型 ---------------- */

/* ---------------- 数据源 ---------------- */

/** GET /api/xhs/trends/meta 真实结构（扁平，无 meta 包裹） */
interface TrendsMeta {
  provider?: string;
  available?: boolean;
  balance?: number;
  reason?: string;
  message?: string;
  hot_list_available?: boolean;
  hot_list_source?: string;
  features?: Record<string, boolean>;
}

interface RedfoxStatus {
  configured?: boolean;
  available?: boolean;
  balance?: number;
  reason?: string;
  message?: string;
  usage?: { day?: string | null; count?: number };
}

function SourcesPanel() {
  const health = useQuery(() => get<{ status?: string; version?: string }>("/api/health"), [], {
    key: "settings|health",
    staleTime: 30_000,
  });

  const redfox = useQuery(() => get<RedfoxStatus>("/api/xhs/redfox/status"), [], {
    key: "settings|redfox",
    staleTime: 30_000,
  });

  const trends = useQuery(() => get<TrendsMeta>("/api/xhs/trends/meta"), [], {
    key: "settings|trends",
    staleTime: 60_000,
  });

  const rf = redfox.data;
  const tm = trends.data;

  return (
    <div className="st__sources">
      <StatRow>
        <Stat
          label="后端"
          value={health.data ? "在线" : "未连通"}
          tone={health.data ? "ok" : "danger"}
          hint={health.data?.version ? `版本 ${health.data.version}` : apiBaseLabel()}
        />
        <Stat
          label="RedFox"
          value={rf?.configured ? "已配置" : "未配置"}
          tone={rf?.configured ? "ok" : "warn"}
          hint={rf?.configured ? `今日调用 ${rf.usage?.count ?? 0} 次` : "热榜增强能力"}
        />
        <Stat
          label="免费热榜"
          value={tm?.hot_list_available ? "可用" : "不可用"}
          tone={tm?.hot_list_available ? "ok" : "warn"}
          hint="不依赖 RedFox 的部分"
        />
        <Stat
          label="趋势"
          value={tm?.available ? "可用" : "降级"}
          tone={tm?.available ? "ok" : "warn"}
          hint="未配置时后端明确降级"
        />
      </StatRow>

      <dl className="st__kv">
        <dt>后端地址</dt>
        <dd className="st__mono">{apiBaseLabel()}</dd>

        <dt>RedFox</dt>
        <dd>{rf?.message ?? "状态未知"}</dd>

        <dt>趋势与热榜</dt>
        <dd>{tm?.message ?? "状态未知"}</dd>

        {tm?.features ? (
          <>
            <dt>能力明细</dt>
            <dd>
              {Object.entries(tm.features)
                .map(([k, v]) => `${k} ${v ? "✓" : "✗"}`)
                .join(" · ")}
            </dd>
          </>
        ) : null}
      </dl>

      <div className="st__note">
        说明：RedFox 未配置时，热榜仍可用（免费源），但榜单、低粉爆款、账号搜索这些增强能力不可用。
        页面会照实标注，不会把降级数据当成真实趋势。
      </div>
    </div>
  );
}
/* ---------------- 运行记录 ---------------- */

/* ---------------- 运行记录 ---------------- */

function DiagnosticsPanel() {
  const diag = useQuery(() => fetchDiagnostics(20), [], {
    key: "settings|diagnostics",
  });

  const d = diag.data;
  const s = d?.summary;
  const rows = d?.api_errors ?? [];

  return (
    <div className="st__diag">
      {diag.initialLoading ? (
        <SkeletonList rows={2} />
      ) : (
        <StatRow>
          <Stat
            label={`近 ${d?.window_days ?? 7} 天 API 错误`}
            value={s?.api_errors ?? 0}
            unit="次"
            tone={(s?.api_errors ?? 0) > 0 ? "warn" : "ok"}
            hint="非 2xx 响应计数"
          />
          <Stat
            label="失败任务"
            value={s?.failed_tasks ?? 0}
            unit="个"
            tone={(s?.failed_tasks ?? 0) > 0 ? "danger" : "default"}
          />
          <Stat
            label="账号问题"
            value={s?.account_issues ?? 0}
            unit="个"
            tone={(s?.account_issues ?? 0) > 0 ? "warn" : "default"}
          />
          <Stat
            label="模板问题"
            value={s?.template_issues ?? 0}
            unit="个"
            tone={(s?.template_issues ?? 0) > 0 ? "warn" : "default"}
          />
        </StatRow>
      )}

      <h2 className="st__sub-title">最近的接口错误</h2>

      {diag.initialLoading ? (
        <SkeletonList rows={4} />
      ) : rows.length === 0 ? (
        <EmptyState
          compact
          glyph="search"
          title="没有接口错误"
          description="请求失败时会按端点记在这里，带状态码和时间。现在很干净。"
        />
      ) : (
        <ul className="st__logs">
          {rows.map((r, i) => (
            <li className="st__log" key={String(r.id ?? i)}>
              <span className="st__log-code">{r.status_code ?? "—"}</span>
              <span className="st__log-method">{r.method ?? "—"}</span>
              <span className="st__log-msg">{r.endpoint}</span>
              <span className="st__log-time">
                {(r.created_at ?? "").replace("T", " ").slice(5, 16)}
              </span>
            </li>
          ))}
        </ul>
      )}

      <div className="st__note">
        说明：这里统计的是后端近 {d?.window_days ?? 7} 天的请求异常。
        上面的数字会随实际调用变化，刷新页面即可读最新。
      </div>
    </div>
  );
}
