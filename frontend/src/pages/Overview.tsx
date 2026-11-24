/**
 * Overview.tsx — 今日
 *
 * 数据：GET /api/xhs/analytics/overview、/api/accounts
 *
 * 精简原则：这一页只回答一个问题——「现在该干什么」。
 * 所以只留三块：账号提示（有问题才出现）、四个数字、三步行动。
 * 原来的「最近动态」「热点」区块已去掉：
 *   · 最近动态有数据时错误地渲染骨架屏，从未显示过真实内容
 *   · 热点在未配 RedFox 时永远是空态，占地方
 */

import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import { Stat, StatRow, RollNumber } from "../components/Stat";
import { SkeletonList, SkeletonStats } from "../components/Skeleton";
import Button from "../components/Button";
import EmptyState from "../components/EmptyState";
import Tour from "../components/Tour";
import PositioningGuide from "../components/PositioningGuide";
import { TOUR_WELCOME } from "../components/tourSteps";
import { hasSeenTour } from "../lib/tour";
import { useQuery } from "../lib/query";
import { get } from "../lib/api";
import { loadPositioning } from "../lib/positioning";
import { loadStyleProfiles } from "../lib/skills";
import "./Overview.css";

interface OverviewShape {
  platform: string;
  today_crawls: number;
  saved_notes: number;
  own_notes: number;
  library_notes: number;
  pending_publishes: number;
  /** 正在发（上传/提交）的任务数，不属于「待发布」 */
  publishing_jobs?: number;
  healthy_accounts: number;
  at_risk_accounts: number;
  comment_count: number;
  total_engagement: number;
  own_total_engagement: number;
  library_total_engagement: number;
  hot_topics: unknown[];
  recent_activity: unknown[];
}

interface AccountShape {
  id: number;
  nickname?: string;
  platform?: string;
  status?: string;
}

interface ListShape<T> {
  items?: T[];
  total?: number;
}

export default function Overview() {
  const navigate = useNavigate();

  const overview = useQuery(
    () => get<OverviewShape>("/api/xhs/analytics/overview"),
    [],
    { key: "overview|analytics" },
  );

  const accounts = useQuery(
    () => get<ListShape<AccountShape>>("/api/accounts"),
    [],
    { key: "overview|accounts" },
  );

  /*
   * 账号定位是写稿时唯一会一直生效的"我是谁"。
   * 它藏在设置里，人不会主动去填；所以在首页把"还没填"这件事露出来，
   * 点一下就过去。填过之后这块不再出现，不占地方。
   */
  const activeAccount = (accounts.data?.items ?? []).find((a) => a.status === "active");
  const positioning = useQuery(
    () => loadPositioning(activeAccount?.id),
    [activeAccount?.id],
    {
      key: `overview|positioning|${activeAccount?.id ?? "none"}`,
      enabled: Boolean(activeAccount),
      staleTime: 30_000,
    },
  );
  const positioningEmpty = positioning.data?.is_empty === true;
  /*
   * 定位的引导直接放在今日展开，不再跳去设置。
   *
   * 原来这里只有一个「去填定位」，点完跳到设置里六个输入框——那正是
   * 用户说「太死板」的那一屏。定位是「我是谁」，属于每天开工前该想一下的事，
   * 放在今日顺手答完更合理；设置里那一页保留成「改已有的」。
   */
  const [guideOpen, setGuideOpen] = useState(false);

  /*
   * 三步行动要跟着数据走，不能一直是「新手三板斧」。
   *
   * 之前这三步只判断 saved_notes：704 条样本了还在说「再补一批同赛道的」，
   * 用户的真实进度（提炼过没有、写过没有）在界面上完全看不出来。
   * 现在每步读一个真实信号，做完的收起来，没做的才占位置。
   */
  const stylesQ = useQuery(() => loadStyleProfiles(), [], {
    key: "overview|styles",
    staleTime: 60_000,
  });
  const batchesQ = useQuery(
    () => get<ListShape<unknown>>("/api/xhs/distill-batches?limit=1"),
    [],
    { key: "overview|batches", staleTime: 60_000 },
  );
  const draftsQ = useQuery(
    () => get<ListShape<unknown>>("/api/drafts?page=1&page_size=1"),
    [],
    { key: "overview|drafts", staleTime: 30_000 },
  );

  const styleCount = stylesQ.data?.items.length ?? 0;
  const hasStyle = styleCount > 0;
  const batchCount = batchesQ.data?.total ?? 0;
  const hasBatch = batchCount > 0;
  const draftCount = draftsQ.data?.total ?? 0;
  const hasDraft = draftCount > 0;

  const [tourOpen, setTourOpen] = useState(false);

  /*
   * 第一次进来自动带看一遍。
   *
   * 用 TOUR_WELCOME（完整版 6 步）而不是 TOUR_HOME（3 步精简版）：
   * 第一次来的人连"这是什么"都还不知道，直接讲页面结构没有意义。
   * 之后点「带我看一遍」看到的也是同一份，两份文案不打架。
   */
  useEffect(() => {
    if (overview.initialLoading) return;
    if (!hasSeenTour("home")) {
      const t = window.setTimeout(() => setTourOpen(true), 600);
      return () => window.clearTimeout(t);
    }
  }, [overview.initialLoading]);

  const d = overview.data;
  const accountItems = accounts.data?.items ?? [];
  const hasAccount = accountItems.length > 0;
  const loading = overview.initialLoading;
  const pending = d?.pending_publishes ?? 0;
  const sampleCount = d?.saved_notes ?? 0;
  const hasSamples = sampleCount > 0;

  return (
    <div className="ov">
      <PageHeader
        title="今日"
        subtitle="整个流程就四步：采素材、提炼写法、写稿、发布。下面按你的进度排好了顺序。"
        actions={
          <>
            <button
              type="button"
              className="tour-launch"
              onClick={() => setTourOpen(true)}
            >
              带我看一遍
            </button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                overview.refetch();
                accounts.refetch();
              }}
            >
              刷新
            </Button>
          </>
        }
      />

      {/* 没有账号才提示，有账号不占地方 */}
      {!accounts.initialLoading && !hasAccount ? (
        <div className="ov__banner">
          <div className="ov__banner-main">
            <strong>还没绑小红书账号</strong>
            <p>不绑也能先采样本、提炼写法。绑了才有数据可复盘。</p>
          </div>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => navigate("/settings/accounts")}
          >
            去绑定
          </Button>
        </div>
      ) : null}

      {/*
        定位区：没写过就用引导问一轮；写过了就压成一行摘要，点「重新定」还能再来。
        无论哪种，都在今日完成，不用去设置里找。
      */}
      {activeAccount && !positioning.initialLoading ? (
        <section className={`ov__pos${positioningEmpty ? " is-empty" : ""}`}>
          <div className="ov__pos-head">
            <div className="ov__pos-main">
              <strong className="ov__pos-title">
                {positioningEmpty ? "先把账号定位说清楚" : "账号定位"}
                {positioningEmpty ? (
                  <span className="ov__pos-tag">还没写</span>
                ) : null}
              </strong>
              <p className="ov__pos-desc">
                {positioningEmpty
                  ? "写一句「我帮谁、解决什么问题、绝不写什么」，之后每次写稿都会自动带上，不用每次重新解释。"
                  : positioning.data?.positioning || "（定位只有零散字段，还没有一句话概括）"}
              </p>
            </div>
            <div className="ov__pos-acts">
              {guideOpen ? (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setGuideOpen(false)}
                >
                  收起
                </Button>
              ) : (
                <Button
                  variant={positioningEmpty ? "primary" : "secondary"}
                  size="sm"
                  onClick={() => setGuideOpen(true)}
                >
                  {positioningEmpty ? "现在开始（3 个问题）" : "重新定一次"}
                </Button>
              )}
              <button
                className="ov__pos-link"
                onClick={() => navigate("/settings/positioning")}
              >
                手动改
              </button>
            </div>
          </div>

          {guideOpen ? (
            <div className="ov__pos-guide">
              <PositioningGuide
                accountId={activeAccount.id}
                onApplied={() => {
                  setGuideOpen(false);
                  positioning.refetch();
                }}
                onClose={() => setGuideOpen(false)}
                onManualFallback={() => navigate("/settings/positioning")}
              />
            </div>
          ) : null}
        </section>
      ) : null}

      <div data-tour="home-stats">
        {loading ? (
          <SkeletonStats count={4} />
        ) : overview.error ? (
          /*
           * 读不到就明说，不要把失败显示成「你还没有数据」。
           *
           * 原来四个数字全是 `d?.x ?? 0`，接口失败时页面显示「样本 0 条」
           * 外加「先采一批样本」，而库里其实有 704 条——用户会以为数据被删了。
           * 空态和失败态必须是两种界面。
           */
          <EmptyState
            glyph="stack"
            title="读不到今日数据"
            description={`后端返回：${overview.error.message}`}
            action={
              <Button variant="primary" onClick={() => overview.refetch()}>
                重试
              </Button>
            }
          />
        ) : (
          <StatRow>
            <Stat
              label="样本"
              value={<RollNumber value={d?.saved_notes ?? 0} />}
              unit="条"
              hint="采集入库的外部笔记"
            />
            <Stat
              label="可蒸馏"
              value={<RollNumber value={d?.library_notes ?? 0} />}
              unit="条"
              hint="有正文、能拿去提炼的"
            />
            <Stat
              label="待发布"
              value={<RollNumber value={pending} />}
              unit="条"
              tone={pending > 0 ? "warn" : "default"}
              hint={
                (d?.publishing_jobs ?? 0) > 0
                  ? `另 ${d?.publishing_jobs} 条正在发`
                  : "要你确认后才发"
              }
            />
            <Stat
              label="已发布"
              value={<RollNumber value={d?.own_notes ?? 0} />}
              unit="条"
              hint="自己的内容"
            />
          </StatRow>
        )}
      </div>

      {/* 三步行动：这一页的核心 */}
      <section className="ov__steps" data-tour="home-actions">
        <h2 className="ov__steps-title">接下来</h2>

        {loading ? (
          <SkeletonList rows={3} />
        ) : (
          <ol className="ov__acts">
            {/* ---- 1 采样本：够了就收起成一行「已完成」 ---- */}
            <li className={`ov__act${hasSamples ? " is-done" : ""}`}>
              <span className="ov__act-idx">{hasSamples ? "✓" : "1"}</span>
              <div className="ov__act-body">
                <span className="ov__act-title">
                  {hasSamples ? `样本 ${sampleCount} 条` : "先采一批样本"}
                </span>
                <span className="ov__act-desc">
                  {hasSamples
                    ? `够用了。想换赛道或补新方向时再采；不补也能继续往下。`
                    : "搜一批同赛道笔记。没有原料，后面提炼和写稿都是空的。"}
                </span>
              </div>
              <Button
                size="sm"
                variant={hasSamples ? "ghost" : "primary"}
                onClick={() => navigate("/assets")}
              >
                {hasSamples ? "再采一批" : "去采集"}
              </Button>
            </li>

            {/* ---- 2 提炼：有写法或批次就算做过 ---- */}
            <li className={`ov__act${hasStyle || hasBatch ? " is-done" : ""}`}>
              <span className="ov__act-idx">
                {hasStyle || hasBatch ? "✓" : hasSamples ? "2" : "·"}
              </span>
              <div className="ov__act-body">
                <span className="ov__act-title">
                  {hasStyle || hasBatch ? "已经提炼过" : "提炼一套写法"}
                </span>
                <span className="ov__act-desc">
                  {hasStyle || hasBatch
                    ? `${styleCount > 0 ? `${styleCount} 份写法` : ""}${
                        styleCount > 0 && hasBatch ? " · " : ""
                      }${hasBatch ? "有可用的提炼批次" : ""}。写稿时会自动带上。`
                    : "选 3 篇以上有正文的样本，提炼成一批可复用的模板。"}
                </span>
              </div>
              <Button
                size="sm"
                variant={hasStyle || hasBatch ? "ghost" : hasSamples ? "secondary" : "ghost"}
                onClick={() => navigate("/write/batches")}
              >
                {hasStyle || hasBatch ? "再提炼" : "去提炼"}
              </Button>
            </li>

            {/* ---- 3 写稿：写过就变成「继续写」 ---- */}
            <li className={`ov__act${hasDraft && pending === 0 ? " is-done" : ""}`}>
              <span className="ov__act-idx">
                {pending > 0 ? "!" : hasDraft ? "✓" : "3"}
              </span>
              <div className="ov__act-body">
                <span className="ov__act-title">
                  {pending > 0
                    ? `确认发布 ${pending} 条`
                    : hasDraft
                      ? `已有 ${draftCount} 篇草稿`
                      : "写第一篇稿"}
                </span>
                <span className="ov__act-desc">
                  {pending > 0
                    ? "稿子已经就绪，发布前要你点一次确认。"
                    : hasDraft
                      ? "接着改，或者开一篇新的。写之前可以先跑自检。"
                      : "给一个主题就能出初稿。发出去之前随时能改。"}
                </span>
              </div>
              <Button
                size="sm"
                variant={pending > 0 ? "primary" : hasDraft ? "ghost" : "secondary"}
                onClick={() =>
                  navigate(pending > 0 ? "/publish" : "/write")
                }
              >
                {pending > 0 ? "去发布" : hasDraft ? "继续写" : "去写稿"}
              </Button>
            </li>
          </ol>
        )}
      </section>

      <Tour
        steps={TOUR_WELCOME}
        open={tourOpen}
        onClose={() => setTourOpen(false)}
        name="home"
      />
    </div>
  );
}
