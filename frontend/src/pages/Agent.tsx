/**
 * Agent.tsx — 智能助手
 *
 * 真实能力边界（已核对 openapi.json）：
 *   后端没有对话/chat 端点。智能体是「计划 → 运行 → 确认」三段式：
 *     GET  /api/agent/overview                    账号、计数、下一步建议
 *     POST /api/agent/plan                        给目标，产出执行计划
 *     POST /api/agent/runs                        按计划启动一次运行
 *     POST /api/agent/runs/{id}/confirm-publish   发布前的人工确认
 *
 * 所以这一页不是聊天框，而是「说目标 → 看计划 → 确认运行」。
 * 不做假聊天，避免让人以为能自由对话。
 */

import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import Button from "../components/Button";
import EmptyState from "../components/EmptyState";
import { SkeletonList } from "../components/Skeleton";
import { Stat, StatRow } from "../components/Stat";
import { useToast } from "../components/Toast";
import { get, post, ApiError, unwrapList } from "../lib/api";
import { useQuery, invalidate } from "../lib/query";
import "./Agent.css";

/* ---------------- 类型（对齐真实响应） ---------------- */

interface AgentCounts {
  accounts: number;
  notes: number;
  drafts: number;
  pending_drafts: number;
  active_skills: number;
  extract_jobs: number;
  style_profiles: number;
  pending_publish_jobs: number;
}

interface AgentOverview {
  accounts: Array<{ id: number | string; nickname?: string }>;
  counts: AgentCounts;
  recent_extract_jobs: unknown[];
  recent_style_profiles: unknown[];
  /** 字符串数组，不带路径 */
  next_actions: string[];
}

/**
 * `GET /api/agent/capabilities` 的形状。
 *
 * 这个端点一直存在，但前端从来没有调用过：用户打开助手页看到的只有
 * 输入框和运行记录，不知道它到底会做什么、边界在哪。于是「助手」变成了
 * 「先随便打一句话试试」。这里把能力清单摊开，例子点一下就填进目标框。
 */
interface AgentCapabilityItem {
  tool: string;
  label: string;
  description?: string;
}

interface AgentCapabilityGroup {
  key: string;
  label: string;
  description?: string;
  examples?: string[];
  primary?: boolean;
  items: AgentCapabilityItem[];
}

interface AgentCapabilities {
  groups: AgentCapabilityGroup[];
  safety?: string[];
  steps_limit?: number;
}

/**
 * 一步计划。形状必须和后端 `AgentPlanStep` 一致：
 *   {tool, args, reason}
 *
 * 原来这里声明的是 {index, title, action, description, tool}——五个字段
 * 后端一个都不产。后果是「确认并开始」把整个 plan 对象传给后端，
 * 后端要的是 list[AgentPlanStep]，直接 422，运行永远起不来。
 */
interface PlanStep {
  tool: string;
  args?: Record<string, unknown>;
  reason?: string;
}

interface AgentPlan {
  goal?: string;
  steps?: PlanStep[];
  notes?: string[];
  summary?: string;
}

interface AgentStepItem {
  id: number;
  step_index: number;
  tool: string;
  args?: Record<string, unknown>;
  status?: string;
  output?: Record<string, unknown>;
  error?: string | null;
  created_at?: string | null;
  finished_at?: string | null;
}

interface AgentRun {
  id: number | string;
  status?: string;
  goal?: string;
  summary?: string;
  error?: string;
  created_at?: string;
  updated_at?: string;
  /** 后端一直返回这个数组（tool/args/status/output/error），前端以前只读 4 个字段 */
  steps?: AgentStepItem[];
}

/**
 * 运行状态的英文 → 中文。
 *
 * 后端只有五个值（`grep 'run.status = '` 可核对）：
 *   running / awaiting_confirmation / completed / failed / cancelled
 *
 * 以前界面直接 `{r.status}`，于是用户看到的是 `awaiting_confirmation`
 * 这一行英文——而它恰好是**唯一需要用户动手**的那个状态。
 */
const RUN_STATUS: Record<string, { text: string; tone: string }> = {
  running: { text: "运行中", tone: "warn" },
  awaiting_confirmation: { text: "等你确认发布", tone: "warn" },
  completed: { text: "已完成", tone: "ok" },
  failed: { text: "失败", tone: "danger" },
  cancelled: { text: "已取消", tone: "muted" },
};

/**
 * 工具名 → 中文。后端 `TOOL_LABELS` 是同一套词，这里只覆盖界面上会出现的那些；
 * 没覆盖的显示原始工具名（好过显示空白）。
 */
const TOOL_LABEL: Record<string, string> = {
  get_workbench_overview: "看现状",
  list_accounts: "读账号",
  list_drafts: "看草稿",
  list_publish_jobs: "看发布任务",
  guide_positioning: "引导式定定位",
  get_creation_skill: "读创作 Skill",
  run_skill_workflow: "按 Skill 执行",
  generate_topic_bank: "批量选题",
  list_library_notes: "查内容库",
  search_and_save_notes: "搜索并入库",
  generate_draft: "生成草稿",
  generate_draft_from_images: "用图生成草稿",
  route_skill_library: "按任务路由",
  get_skill_library_item: "读扩展 Skill",
  score_draft: "评分体检",
  update_draft: "改草稿",
  recommend_topics: "推荐话题",
  build_visual_brief: "视觉 Brief",
  create_template: "建模板",
  analyze_benchmark: "对标分析",
  plan_schedule: "排期建议",
  prepare_publish: "准备发布",
  review_published: "复盘",
  set_skill_library_enabled: "开关 Skill",
};

export default function AgentPage() {
  const navigate = useNavigate();
  const toast = useToast();

  const overview = useQuery(() => get<AgentOverview>("/api/agent/overview"), [], {
    key: "agent|overview",
  });

  // 静态清单，一个会话里不会变；缓存久一点。
  const capabilities = useQuery(
    () => get<AgentCapabilities>("/api/agent/capabilities"),
    [],
    { key: "agent|capabilities", staleTime: 10 * 60_000 },
  );
  const capabilityGroups = (capabilities.data?.groups ?? []).filter((g) => g.primary);

  const runs = useQuery(
    () => get("/api/agent/runs").then((r) => unwrapList<AgentRun>(r)),
    [],
    { key: "agent|runs" },
  );

  const [goal, setGoal] = useState("");
  const [plan, setPlan] = useState<AgentPlan | null>(null);
  const [planning, setPlanning] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  const counts = overview.data?.counts;
  const actions = overview.data?.next_actions ?? [];
  const runItems = runs.data?.items ?? [];

  /*
   * 运行中的记录要自己刷。
   *
   * 以前点「确认并开始」之后只 `invalidate` 一次，后端还在跑，界面永远停在
   * 刚提交那一刻的状态——用户只能靠刷新页面猜它跑完没有。后端是后台线程
   * 执行的，没有推送，所以这里轮询。
   *
   * 只在「有运行中的记录」时才开定时器：没有活就每秒打一次接口是浪费。
   */
  const hasLiveRun = runItems.some(
    (r) => r.status === "running" || r.status === "awaiting_confirmation",
  );
  useEffect(() => {
    if (!hasLiveRun) return;
    const timer = window.setInterval(() => runs.refetch(), 3000);
    return () => window.clearInterval(timer);
  }, [hasLiveRun, runs]);

  const makePlan = async () => {
    if (!goal.trim()) {
      setError("先说清你想让助手做什么");
      return;
    }
    setError(null);
    setPlan(null);
    setPlanning(true);
    try {
      const res = await post<AgentPlan>("/api/agent/plan", {
        goal: goal.trim(),
      });
      setPlan(res ?? {});
    } catch (err) {
      const m = err instanceof ApiError ? err.message : "生成计划失败";
      setError(m);
      toast.error(m);
    } finally {
      setPlanning(false);
    }
  };

  const startRun = async () => {
    if (!plan) return;
    setStarting(true);
    try {
      /*
       * 传 steps 数组，不传整个 plan 对象。
       *
       * 后端 `AgentRunRequest.plan: list[AgentPlanStep]`，给对象直接 422
       * （实测 `{'type':'list_type','msg':'必须是列表'}`）。`summary` 是
       * 给人看的，不进请求。
       */
      const res = await post<AgentRun>("/api/agent/runs", {
        goal: goal.trim(),
        plan: plan.steps ?? [],
      });
      toast.success("已启动一次运行");
      invalidate("agent");
      setPlan(null);
      setGoal("");
      if (res?.id) {
        toast.info(`运行编号 ${res.id}，发布前会要求你确认`);
      }
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "启动失败");
    } finally {
      setStarting(false);
    }
  };

  /*
   * 点「确认发布」。
   *
   * 后端 `POST /runs/{id}/confirm-publish` 一直存在，前端从来没有调用过：
   * 助手跑到 `awaiting_confirmation` 就停在那里，界面只有一行英文状态，
   * 用户找不到地方回答它。这一步就是把那条断链接上。
   *
   * 这里只创建待发布任务，不直接发——发布永远要人去发布页按一次确认。
   */
  const confirmPublish = async (runId: string) => {
    setConfirming(runId);
    try {
      await post(`/api/agent/runs/${runId}/confirm-publish`, {});
      toast.success("已创建发布任务，去「发布」里点确认才会真的发出去");
      invalidate("agent");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "确认发布失败");
    } finally {
      setConfirming(null);
    }
  };

  /*
   * 取消一次运行。
   *
   * 后端 `POST /runs/{id}/cancel` 存在，前端零调用。没有这个按钮，
   * 发现目标说错了只能等它跑完 8 步——而每步都在花模型调用。
   */
  const cancelRun = async (runId: string) => {
    setCancelling(runId);
    try {
      await post(`/api/agent/runs/${runId}/cancel`, {});
      toast.success("已取消这次运行");
      invalidate("agent");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "取消失败");
    } finally {
      setCancelling(null);
    }
  };

  return (
    <div className="ag">
      <PageHeader
        title="助手"
        subtitle="给它一个目标，它先出计划，你确认后才开始跑。涉及发布会停下来问你。跑完的东西落在草稿箱。"
      />

      {overview.initialLoading ? (
        <SkeletonList rows={3} />
      ) : (
        <StatRow>
          <Stat label="账号" value={counts?.accounts ?? 0} unit="个" />
          <Stat label="样本" value={counts?.notes ?? 0} unit="条" />
          <Stat
            label="草稿"
            value={counts?.drafts ?? 0}
            unit="篇"
            hint={
              counts?.pending_drafts
                ? `其中 ${counts.pending_drafts} 篇待处理`
                : undefined
            }
          />
          <Stat
            label="待发布"
            value={counts?.pending_publish_jobs ?? 0}
            unit="条"
            tone={(counts?.pending_publish_jobs ?? 0) > 0 ? "warn" : "default"}
          />
        </StatRow>
      )}

      {/* 能力清单：告诉用户「能做什么」，而不是让他先猜一句话 */}
      {capabilityGroups.length > 0 ? (
        <section className="ag__caps" aria-label="它能做什么">
          <div className="ag__caps-head">
            <span className="ag__caps-k">它能做什么</span>
            <span className="ag__caps-hint">
              点一条把例子填进下面的输入框；{capabilities.data?.steps_limit ?? 8} 步以内出计划，
              发布永远要你再确认。
            </span>
          </div>
          <div className="ag__caps-list">
            {capabilityGroups.map((group) => {
              const example = group.examples?.[0] ?? "";
              return (
                <button
                  key={group.key}
                  type="button"
                  className="ag__cap"
                  title={group.description || group.label}
                  onClick={() => {
                    if (example) setGoal(example);
                    setError(null);
                  }}
                >
                  <span className="ag__cap-label">{group.label}</span>
                  {example ? <span className="ag__cap-eg">{example}</span> : null}
                </button>
              );
            })}
          </div>

          {/* 边界：只说「能做什么」会让人以为它什么都能做 */}
          {(capabilities.data?.safety?.length ?? 0) > 0 ? (
            <div className="ag__safety" aria-label="它的边界">
              <span className="ag__safety-k">它的边界</span>
              <ul className="ag__safety-list">
                {capabilities.data?.safety?.map((line) => (
                  <li key={line} className="ag__safety-item">
                    {line}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </section>
      ) : null}

      {/* 目标输入 */}
      <section className="ag__setup">
        <label className="ag__label" htmlFor="agent-goal">
          你想让它做什么
        </label>
        <textarea
          id="agent-goal"
          className="ag__goal"
          rows={2}
          value={goal}
          placeholder="例如：把样本库里这 5 篇关于汇报的笔记蒸馏成一篇新稿"
          onChange={(e) => {
            setGoal(e.target.value);
            setError(null);
          }}
        />

        {/* 下一步建议：真实来自后端，是字符串，点击填进目标框 */}
        {actions.length > 0 ? (
          <div className="ag__sugs">
            <span className="ag__sugs-k">可以这样开始</span>
            <div className="ag__sugs-list">
              {actions.map((a, i) => (
                <button
                  key={i}
                  type="button"
                  className="ag__sug"
                  onClick={() => {
                    setGoal(a);
                    setError(null);
                  }}
                >
                  {a}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {error ? (
          <div className="ag__error" role="alert">
            {error}
          </div>
        ) : null}

        <div className="ag__actions-row">
          <Button variant="primary" onClick={makePlan} loading={planning}>
            {planning ? "正在规划" : "生成计划"}
          </Button>
          {goal ? (
            <Button
              variant="ghost"
              onClick={() => {
                setGoal("");
                setPlan(null);
                setError(null);
              }}
            >
              清空
            </Button>
          ) : null}
        </div>
      </section>

      {/* 计划 */}
      {plan ? (
        <section className="ag__plan">
          <div className="ag__plan-head">
            <h2 className="ag__plan-title">执行计划</h2>
            <Button
              variant="primary"
              size="sm"
              onClick={startRun}
              loading={starting}
            >
              确认并开始
            </Button>
          </div>

          {plan.summary ? <p className="ag__plan-sum">{plan.summary}</p> : null}

          {plan.steps && plan.steps.length > 0 ? (
            <ol className="ag__steps">
              {plan.steps.map((s, i) => (
                <li className="ag__step" key={`${s.tool}-${i}`}>
                  <span className="ag__step-idx">{i + 1}</span>
                  <div className="ag__step-body">
                    <span className="ag__step-title">
                      {/* 后端只给 tool + reason；没有「标题」这个字段 */}
                      {s.reason || s.tool || `步骤 ${i + 1}`}
                    </span>
                    {s.reason && s.tool ? (
                      <span className="ag__step-desc">{s.tool}</span>
                    ) : null}
                  </div>
                </li>
              ))}
            </ol>
          ) : (
            <p className="ag__plan-sum">
              计划已生成但没有分步内容。可以直接开始，或换个更具体的目标。
            </p>
          )}

          {plan.notes && plan.notes.length > 0 ? (
            <ul className="ag__notes">
              {plan.notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}

      {/* 运行记录 */}
      <section className="ag__runs">
        <h2 className="ag__runs-title">运行记录</h2>
        {runs.initialLoading ? (
          <SkeletonList rows={3} />
        ) : runItems.length === 0 ? (
          <EmptyState
            compact
            glyph="flow"
            title="还没有运行过"
            description="上面写个目标、确认计划后，这里会按时间列出每次运行的状态。"
            action={
              <Button
                size="sm"
                variant="secondary"
                onClick={() => navigate("/assets")}
              >
                先去采样本
              </Button>
            }
          />
        ) : (
          <ul className="ag__run-list">
            {runItems.map((r) => {
              const st = RUN_STATUS[r.status ?? ""] ?? {
                text: r.status ?? "未知状态",
                tone: "muted",
              };
              // 只有这一个状态需要用户动手：助手停在发布前等人回答
              const needsConfirm = r.status === "awaiting_confirmation";
              return (
                <li className="ag__run" key={String(r.id)}>
                  <div className="ag__run-main">
                    <span className="ag__run-id">#{r.id}</span>
                    <span className="ag__run-goal">{r.goal ?? "—"}</span>
                    <span className={`ag__run-status is-${st.tone}`}>
                      {st.text}
                    </span>
                    <span className="ag__run-time">
                      {(r.created_at ?? "").replace("T", " ").slice(0, 16)}
                    </span>
                  </div>
                  {r.error ? (
                    <span className="ag__run-error">{r.error}</span>
                  ) : null}
                  {/*
                    停在发布前时把「停在哪、为什么、要你做什么」说清楚。
                    只显示一个状态词的话，用户不知道这是等他还是出错了。
                  */}
                  {needsConfirm ? (
                    <div className="ag__run-ask">
                      <span>
                        助手已经写完稿，停在这里等你确认。确认后只会创建一条
                        待发布任务，去「发布」里再点一次才会真的发出去。
                      </span>
                      <Button
                        size="sm"
                        variant="primary"
                        loading={confirming === String(r.id)}
                        onClick={() => void confirmPublish(String(r.id))}
                      >
                        确认发布这条
                      </Button>
                    </div>
                  ) : null}
                  {r.summary ? (
                    <span className="ag__run-summary">{r.summary}</span>
                  ) : null}

                  {/*
                    步骤时间线。后端 `serialize_run` 一直在返回 steps[]
                    （tool / args / status / output / error），前端从来没读过——
                    于是「它到底做了什么」在界面上完全不可见。
                  */}
                  {r.steps && r.steps.length > 0 ? (
                    <div className="ag__steps-wrap">
                      <button
                        type="button"
                        className="ag__steps-toggle"
                        aria-expanded={expanded === String(r.id)}
                        onClick={() =>
                          setExpanded((prev) =>
                            prev === String(r.id) ? null : String(r.id),
                          )
                        }
                      >
                        {expanded === String(r.id) ? "收起步骤" : `看这 ${r.steps.length} 步做了什么`}
                      </button>
                      {expanded === String(r.id) ? (
                        <ol className="ag__timeline">
                          {r.steps.map((step) => {
                            const tool = TOOL_LABEL[step.tool] ?? step.tool;
                            return (
                              <li
                                className={`ag__tl-step is-${step.status ?? "unknown"}`}
                                key={step.id}
                              >
                                <span className="ag__tl-idx">{step.step_index}</span>
                                <div className="ag__tl-body">
                                  <span className="ag__tl-tool">{tool}</span>
                                  {step.error ? (
                                    <span className="ag__tl-error">{step.error}</span>
                                  ) : null}
                                </div>
                              </li>
                            );
                          })}
                        </ol>
                      ) : null}
                    </div>
                  ) : null}

                  {/* 跑着的可以取消：每步都在花模型调用 */}
                  {r.status === "running" ? (
                    <div className="ag__run-ask is-quiet">
                      <span>正在跑，发现目标说错了可以停。</span>
                      <Button
                        size="sm"
                        variant="ghost"
                        loading={cancelling === String(r.id)}
                        onClick={() => void cancelRun(String(r.id))}
                      >
                        取消这次运行
                      </Button>
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
