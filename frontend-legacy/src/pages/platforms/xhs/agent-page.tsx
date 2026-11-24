import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  CopyOutlined,
  EditOutlined,
  FileTextOutlined,
  FundOutlined,
  LoadingOutlined,
  RobotOutlined,
  SendOutlined,
  ThunderboltOutlined,
  UploadOutlined,
  VideoCameraOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Col,
  Collapse,
  Divider,
  Empty,
  Input,
  List,
  Row,
  Select,
  Space,
  Spin,
  Tag,
  theme,
  Typography,
  Upload,
  message,
} from "antd";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { NAV_SECTIONS } from "../../../app/navigation";
import { PageHeader } from "../../../components/layout/app-shell";
import { NextStepBar } from "../../../components/layout/next-step-bar";
import {
  cancelAgentRun,
  confirmAgentPublish,
  fetchAccounts,
  fetchAgentCapabilities,
  fetchAgentOverview,
  fetchAgentRun,
  fetchAgentRuns,
  fetchCurrentCreationSkill,
  fetchSkillLibrary,
  planAgent,
  runAgent,
  uploadAssetFile,
} from "../../../lib/api";
import { formatShanghaiTime } from "../../../lib/time";
import type {
  AgentCapabilities,
  AgentOverview,
  AgentPlanStep,
} from "../../../lib/api";
import type { AgentRun, AgentStepRecord, CreationSkill, PlatformAccount } from "../../../types";

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

const TOOL_LABELS: Record<string, string> = {
  list_accounts: "读取账号",
  get_account_persona: "读取创作 Skill（旧名）",
  get_creation_skill: "读取创作 Skill",
  analyze_account: "分析账号内容",
  list_library_notes: "查找样本库",
  search_and_save_notes: "搜索并入库",
  create_template: "生成标题/要点模板",
  generate_draft: "生成草稿",
  generate_draft_from_images: "图片生成草稿",
  score_draft: "评分与体检",
  prepare_publish: "准备发布",
  recommend_topics: "推荐话题",
  route_skill_library: "按任务路由 Skill",
  list_skill_library: "浏览模块 Skill",
  get_skill_library_item: "读取模块 Skill",
  set_skill_library_enabled: "启用/停用模块 Skill",
  analyze_benchmark: "对标样本分析",
  plan_schedule: "排期建议",
  build_visual_brief: "视觉 Brief",
  review_published: "发布后复盘",
  get_workbench_overview: "工作台总览",
  list_drafts: "查看草稿",
  list_publish_jobs: "查看发布任务",
  list_douyin_extract_jobs: "查看提取任务",
  get_douyin_extract_job: "查看提取详情",
  create_douyin_extract_job: "创建抖音提取",
  run_douyin_extract_job: "执行抖音提取",
  distill_writing_style: "蒸馏写法",
  list_style_profiles: "查看候选写法",
  apply_style_skill: "保存为创作 Skill",
  convert_douyin_to_drafts: "转成小红书草稿",
};

const SCENARIOS = [
  {
    key: "douyin",
    icon: <VideoCameraOutlined />,
    label: "抖音作品 → 蒸馏写法 → 生成草稿",
    description: "先提取口播，再按账号的创作 Skill 生成小红书草稿",
    goal: "看看我最近的抖音提取任务，把至少 3 篇文稿蒸馏成写法，并生成 3 篇小红书草稿",
  },
  {
    key: "weekly",
    icon: <FundOutlined />,
    label: "本周复盘 → 下周 3 条计划",
    description: "看本周发布表现，再给出下周选题和排期",
    goal: "复盘这周发布的数据，并给我排下周 3 条内容",
  },
];

type SkillStepCheck = {
  index: number;
  title: string;
  criterion: string;
  checkable: boolean;
  status: "passed" | "failed" | "unverifiable";
  reason: string;
  result: string;
};

const GATE_META: Record<SkillStepCheck["status"], { color: string; label: string }> = {
  passed: { color: "green", label: "达标" },
  failed: { color: "red", label: "未达标" },
  unverifiable: { color: "gold", label: "需人工判断" },
};

/**
 * Renders a Skill actually being executed: the artifact it produced, plus one
 * row per step showing whether that step's own completion criterion was met.
 *
 * The point of this panel is that the criteria are checkable. A Skill that
 * could not be finished reports `failed` with the missing input instead of a
 * polished paragraph that looks complete.
 */
function SkillWorkflowOutput({ output }: { output: Record<string, unknown> }) {
  const skill = (output.skill as Record<string, unknown>) || {};
  const checks = (output.step_checks as SkillStepCheck[]) || [];
  const questions = (output.open_questions as string[]) || [];
  const artifact = String(output.artifact || "");
  const gateStatus = String(output.gate_status || "");
  const passed = Number(output.gate_passed ?? 0);
  const failed = Number(output.gate_failed ?? 0);
  const unverifiable = Number(output.gate_unverifiable ?? 0);
  const gateColor =
    gateStatus === "passed" ? "green" : gateStatus === "failed" ? "red" : "gold";
  const gateLabel =
    gateStatus === "passed" ? "完成标准全部达标" : gateStatus === "failed" ? "有步骤未达标" : "部分待确认";

  return (
    <Space direction="vertical" size={8} style={{ width: "100%" }}>
      <Space size={6} wrap>
        <Tag color="blue">{String(skill.name || "模块 Skill")}</Tag>
        <Tag>{String(skill.module_label || "")}</Tag>
        <Tag>{String(output.step_count ?? checks.length)} 步</Tag>
        <Tag color={gateColor}>{gateLabel}</Tag>
        <Tag color="green">达标 {passed}</Tag>
        {failed > 0 ? <Tag color="red">未达标 {failed}</Tag> : null}
        {unverifiable > 0 ? <Tag color="gold">待人工 {unverifiable}</Tag> : null}
      </Space>

      {checks.length ? (
        <Collapse
          size="small"
          items={[
            {
              key: "gate",
              label: `完成标准逐条核验（${checks.length} 步）`,
              children: (
                <Space direction="vertical" size={6} style={{ width: "100%" }}>
                  {checks.map((check) => {
                    const meta = GATE_META[check.status] ?? GATE_META.unverifiable;
                    return (
                      <div key={check.index}>
                        <Space size={6} wrap>
                          <Tag color={meta.color}>{meta.label}</Tag>
                          <Text style={{ fontSize: 12 }}>
                            {check.index}. {check.title}
                          </Text>
                        </Space>
                        <div style={{ paddingLeft: 8 }}>
                          <Text type="secondary" style={{ fontSize: 11 }}>
                            标准：{check.criterion || "该步未写完成标准"}
                          </Text>
                          {check.result ? (
                            <div>
                              <Text style={{ fontSize: 11 }}>结果：{check.result.slice(0, 220)}</Text>
                            </div>
                          ) : null}
                          {check.status !== "passed" ? (
                            <div>
                              <Text type="warning" style={{ fontSize: 11 }}>
                                {check.reason}
                              </Text>
                            </div>
                          ) : null}
                        </div>
                      </div>
                    );
                  })}
                </Space>
              ),
            },
          ]}
        />
      ) : null}

      {questions.length ? (
        <Alert
          type="warning"
          showIcon
          message={`还缺 ${questions.length} 项信息才能做完整`}
          description={
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12 }}>
              {questions.map((question) => (
                <li key={question}>{question}</li>
              ))}
            </ul>
          }
        />
      ) : null}

      {artifact ? (
        <div>
          <Space size={6} style={{ marginBottom: 4 }}>
            <FileTextOutlined />
            <Text strong style={{ fontSize: 12 }}>
              产物（{artifact.length} 字）
            </Text>
            <Button
              size="small"
              type="link"
              onClick={() => {
                void navigator.clipboard.writeText(artifact);
                message.success("已复制产物");
              }}
            >
              复制
            </Button>
          </Space>
          <pre
            style={{
              margin: 0,
              padding: 10,
              maxHeight: 420,
              overflow: "auto",
              background: "rgba(0,0,0,0.03)",
              borderRadius: 8,
              fontSize: 12,
              lineHeight: 1.6,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}
          >
            {artifact}
          </pre>
        </div>
      ) : (
        <Text type="secondary" style={{ fontSize: 12 }}>
          这次没有产出可用结果，按上面的缺口补充信息后重跑。
        </Text>
      )}
    </Space>
  );
}

function stepOutput(step: AgentStepRecord) {
  const output = step.output || {};
  if (step.tool === "list_accounts") {
    const accounts = (output.accounts as Array<Record<string, unknown>>) || [];
    return (
      <Space size={4} wrap>
        {accounts.map((account) => (
          <Tag key={String(account.id)}>
            {String(account.nickname || account.id)} · {String(account.sub_type || "")}
            {account.has_persona ? " · 有 Skill" : ""}
          </Tag>
        ))}
      </Space>
    );
  }
  if (step.tool === "get_account_persona") {
    return (
      <Text type="secondary" style={{ fontSize: 12 }}>
        {output.has_persona ? String(output.positioning || "已读取 Skill") : "该账号还没有生效的创作 Skill"}
      </Text>
    );
  }
  if (step.tool === "analyze_account") {
    const keywords = (output.keywords as string[]) || [];
    return (
      <Space direction="vertical" size={2}>
        <Text style={{ fontSize: 13 }}>
          笔记 {String(output.note_count ?? 0)} 条 · 篇均互动 {String(output.avg_engagement ?? 0)}
        </Text>
        <Space size={4} wrap>
          {keywords.slice(0, 8).map((word) => (
            <Tag key={word} color="blue">{word}</Tag>
          ))}
        </Space>
      </Space>
    );
  }
  if (step.tool === "list_library_notes" || step.tool === "search_and_save_notes") {
    const notes = (output.notes as Array<Record<string, unknown>>) || [];
    return (
      <Space direction="vertical" size={4} style={{ width: "100%" }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          共 {String(output.count ?? notes.length)} 条
        </Text>
        <Space size={4} wrap>
          {notes.slice(0, 6).map((note) => (
            <Tag key={String(note.id)}>{String(note.title || note.note_id)}</Tag>
          ))}
        </Space>
      </Space>
    );
  }
  if (step.tool === "create_template") {
    return (
      <Space direction="vertical" size={2}>
        <Text style={{ fontSize: 13 }}>模板「{String(output.name || "")}」</Text>
        <Space size={4} wrap>
          {((output.keywords as string[]) || []).slice(0, 6).map((word) => (
            <Tag key={word} color="blue">{word}</Tag>
          ))}
        </Space>
      </Space>
    );
  }
  if (step.tool === "generate_draft" || step.tool === "generate_draft_from_images") {
    return (
      <Space direction="vertical" size={2}>
        <Text style={{ fontSize: 13 }}>{String(output.title || "")}</Text>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {String(output.body_preview || "").slice(0, 120)}
        </Text>
        {output.skill_version ? (
          <Text type="secondary" style={{ fontSize: 11 }}>
            使用 Skill：{String(output.skill_name || "当前 Skill")} {String(output.skill_version)}
          </Text>
        ) : null}
      </Space>
    );
  }
  if (step.tool === "score_draft") {
    const words = (output.sensitive_words as string[]) || [];
    return (
      <Space direction="vertical" size={2}>
        <Space size={6}>
          <Tag color="blue">标题 {String(output.title_score ?? "-")}</Tag>
          <Tag color="purple">体检 {String(output.note_score ?? "-")}</Tag>
          <Tag color={Number(output.sensitive_count) > 0 ? "red" : "green"}>
            风险词 {String(output.sensitive_count ?? 0)}
          </Tag>
        </Space>
        {words.length ? (
          <Space size={4} wrap>
            {words.map((word) => <Tag key={word} color="red">{word}</Tag>)}
          </Space>
        ) : null}
      </Space>
    );
  }
  if (step.tool === "prepare_publish") {
    return (
      <Space direction="vertical" size={2}>
        <Text style={{ fontSize: 13 }}>{String(output.title || "")}</Text>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {String(output.account_name || "")} · 待确认
        </Text>
      </Space>
    );
  }
  if (step.tool === "recommend_topics") {
    const topics = (output.topics as Array<Record<string, unknown>>) || [];
    return (
      <Space direction="vertical" size={3}>
        <Space size={4} wrap>
          {topics.slice(0, 6).map((topic) => (
            <Tag key={String(topic.title)} color="cyan">{String(topic.title)}</Tag>
          ))}
        </Space>
        {output.warning ? (
          <Text type="warning" style={{ fontSize: 11 }}>
            {String(output.warning)}
          </Text>
        ) : null}
      </Space>
    );
  }
  if (step.tool === "run_skill_workflow") {
    return <SkillWorkflowOutput output={output} />;
  }
  if (step.tool === "get_workbench_overview") {
    const counts = (output.counts as Record<string, number>) || {};
    const actions = (output.next_actions as string[]) || [];
    return (
      <Space direction="vertical" size={4} style={{ width: "100%" }}>
        <Space size={4} wrap>
          <Tag>账号 {counts.accounts ?? 0}</Tag>
          <Tag>草稿 {counts.drafts ?? 0}</Tag>
          <Tag>待审 {counts.pending_drafts ?? 0}</Tag>
          <Tag>Skill {counts.active_skills ?? 0}</Tag>
          <Tag>提取 {counts.extract_jobs ?? 0}</Tag>
        </Space>
        <Space size={4} wrap>
          {actions.map((action) => (
            <Tag key={action} color="blue" style={{ whiteSpace: "normal" }}>
              {action}
            </Tag>
          ))}
        </Space>
      </Space>
    );
  }
  if (
    step.tool === "create_douyin_extract_job" ||
    step.tool === "run_douyin_extract_job" ||
    step.tool === "get_douyin_extract_job"
  ) {
    return (
      <Space direction="vertical" size={2}>
        <Space size={4} wrap>
          <Tag color="blue">任务 #{String(output.id ?? "-")}</Tag>
          <Tag>{String(output.status ?? "")}</Tag>
          <Tag>作品 {String(output.total ?? 0)}</Tag>
          <Tag color="green">完成 {String(output.completed ?? 0)}</Tag>
          {Number(output.failed ?? 0) > 0 ? (
            <Tag color="red">失败 {String(output.failed)}</Tag>
          ) : null}
          {output.transcribed ? <Tag>已转写 {String(output.transcribed)}</Tag> : null}
        </Space>
        {output.error ? (
          <Text type="danger" style={{ fontSize: 12 }}>{String(output.error)}</Text>
        ) : null}
      </Space>
    );
  }
  if (step.tool === "distill_writing_style") {
    const summary = (output.summary as Record<string, unknown>) || {};
    const hooks = (summary.hooks as Array<Record<string, unknown>>) || [];
    return (
      <Space direction="vertical" size={3}>
        <Space size={4} wrap>
          <Tag color="purple">样本 {String(output.works_count ?? 0)} 篇</Tag>
          <Tag>{output.engine === "llm" ? "统计 + 模型" : "统计"}</Tag>
        </Space>
        <Space size={4} wrap>
          {hooks.slice(0, 3).map((hook) => (
            <Tag key={String(hook.label)} color="blue">{String(hook.label)}</Tag>
          ))}
        </Space>
      </Space>
    );
  }
  if (step.tool === "apply_style_skill") {
    return (
      <Space size={4} wrap>
        <Tag color="green">{String(output.skill_version || "")}</Tag>
        <Text type="secondary" style={{ fontSize: 12 }}>{String(output.message || "")}</Text>
      </Space>
    );
  }
  if (step.tool === "convert_douyin_to_drafts") {
    const drafts = (output.drafts as Array<Record<string, unknown>>) || [];
    return (
      <Space direction="vertical" size={3} style={{ width: "100%" }}>
        <Space size={4} wrap>
          <Tag color="green">生成 {String(output.created ?? 0)}</Tag>
          <Tag>跳过 {String(output.skipped ?? 0)}</Tag>
          <Tag color={Number(output.failed) > 0 ? "red" : "default"}>
            失败 {String(output.failed ?? 0)}
          </Tag>
        </Space>
        <Space direction="vertical" size={1}>
          {drafts.slice(0, 5).map((draft) => (
            <Text key={String(draft.draft_id)} style={{ fontSize: 12 }}>
              #{String(draft.draft_id)} {String(draft.title || "")}
            </Text>
          ))}
        </Space>
      </Space>
    );
  }
  if (step.tool === "generate_topic_bank") {
    const items = (output.items as Array<Record<string, unknown>>) || [];
    return (
      <Space direction="vertical" size={3}>
        <Space size={4} wrap>
          <Tag>生成 {String(output.count ?? items.length)}</Tag>
          <Tag>{output.engine === "model" ? "模型生成" : "模板生成"}</Tag>
        </Space>
        <Space size={4} wrap>
          {items.slice(0, 6).map((item) => (
            <Tag key={String(item.title)}>{String(item.title)}</Tag>
          ))}
        </Space>
      </Space>
    );
  }
  if (step.tool === "list_drafts" || step.tool === "list_style_profiles") {
    const items = (output.items as Array<Record<string, unknown>>) || [];
    return (
      <Space size={4} wrap>
        {items.slice(0, 8).map((item) => (
          <Tag key={String(item.id)}>
            {String(item.title || item.name || item.id)}
          </Tag>
        ))}
      </Space>
    );
  }
  if (step.tool === "set_skill_library_enabled") {
    return (
      <Space size={4} wrap>
        <Tag color={output.enabled ? "green" : "default"}>
          {output.enabled ? "已启用" : "已停用"}
        </Tag>
        <Tag>{String(output.name || output.slug || "")}</Tag>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {output.scope === "global" ? "全局" : `账号 ${String(output.scope || "").replace("account:", "")}`}
          {output.priority ? ` · 优先级 ${String(output.priority)}` : ""}
        </Text>
      </Space>
    );
  }
  if (step.tool === "analyze_benchmark") {
    const keywords = (output.keywords as string[]) || [];
    const visual = (output.visual_skeleton as Record<string, any>) || {};
    return (
      <Space direction="vertical" size={3}>
        <Space size={4} wrap>
          <Tag>样本 {String(output.note_count ?? 0)}</Tag>
          {visual.page_count ? <Tag color="purple">视觉 {String(visual.page_count)}</Tag> : null}
          {visual.cover?.title_ratio ? <Tag>封面标题 30–40%</Tag> : null}
        </Space>
        <Space size={4} wrap>
          {keywords.slice(0, 8).map((word) => <Tag key={word} color="blue">{word}</Tag>)}
        </Space>
      </Space>
    );
  }
  if (step.tool === "build_visual_brief") {
    const experts = (output.experts as Array<Record<string, unknown>>) || [];
    return (
      <Space direction="vertical" size={3}>
        <Space size={4} wrap>
          <Tag>{String(output.title || "")}</Tag>
          {experts.map((expert) => (
            <Tag key={String(expert.key)} color="purple">
              {String(expert.label)}
            </Tag>
          ))}
        </Space>
        <Text type="secondary" style={{ fontSize: 11 }}>
          分流顺序：{((output.sequence as string[]) || []).join(" → ") || "—"}
        </Text>
      </Space>
    );
  }
  if (step.tool === "review_published") {
    return (
      <Space size={4} wrap>
        <Tag>笔记 {String(output.note_count ?? 0)}</Tag>
        <Tag>成功率 {String(output.publish_success_rate ?? "—")}%</Tag>
        {output.memory_written ? <Tag color="green">已写回账号记忆</Tag> : null}
        {output.persona_updated ? <Tag color="purple">已写回人设规则</Tag> : null}
      </Space>
    );
  }
  return <Text type="secondary" style={{ fontSize: 12 }}>{JSON.stringify(output).slice(0, 160)}</Text>;
}

function resultLinks(run: AgentRun) {
  const tools = new Set(run.steps.map((step) => step.tool));
  const draftId = run.steps
    .map((step) => step.output?.draft_id)
    .find((value): value is number => typeof value === "number" && value > 0);
  const templateId = run.steps
    .map((step) => step.output?.template_id)
    .find((value): value is number => typeof value === "number" && value > 0);
  const jobId = run.steps
    .map((step) => step.output?.job_id)
    .find((value): value is number => typeof value === "number" && value > 0);
  const hasDraft = Boolean(draftId) || tools.has("generate_draft") || tools.has("generate_draft_from_images") || tools.has("convert_douyin_to_drafts");
  return (
    <Space wrap>
      {hasDraft ? (
        <Link to={draftId ? `/platforms/xhs/write/drafts?draft_id=${draftId}` : "/platforms/xhs/write/drafts"}>
          <Button type="primary" size="small">打开草稿工坊</Button>
        </Link>
      ) : null}
      {tools.has("create_template") ? (
        <Link to={templateId ? `/platforms/xhs/refine/templates?template_id=${templateId}` : "/platforms/xhs/refine/templates"}>
          <Button size="small">查看结构模板</Button>
        </Link>
      ) : null}
      {tools.has("list_library_notes") || tools.has("search_and_save_notes") ? (
        <Link to="/platforms/xhs/assets/library"><Button size="small">打开样本库</Button></Link>
      ) : null}
      {tools.has("create_douyin_extract_job") || tools.has("run_douyin_extract_job") ||
      tools.has("get_douyin_extract_job") || tools.has("list_douyin_extract_jobs") ? (
        <Link to="/platforms/xhs/assets/douyin"><Button size="small">抖音口播提取</Button></Link>
      ) : null}
      {tools.has("distill_writing_style") || tools.has("apply_style_skill") ? (
        <Link to="/platforms/xhs/refine/skills"><Button size="small">打开 Skill</Button></Link>
      ) : null}
      {tools.has("prepare_publish") && run.status === "completed" ? (
        <Link to={jobId ? `/platforms/xhs/publish-hub/jobs?job_id=${jobId}` : "/platforms/xhs/publish-hub/jobs"}>
          <Button size="small">去发布中心</Button>
        </Link>
      ) : null}
    </Space>
  );
}

function runSkillSummary(run: AgentRun) {
  const active = new Map<string, string>();
  const routed = new Map<string, string>();
  const toggles: string[] = [];
  let style = "";
  for (const step of run.steps) {
    const output = (step.output || {}) as Record<string, any>;
    if (step.tool === "get_creation_skill" && output.has_skill) {
      active.set(String(output.name || "创作 Skill"), String(output.version || ""));
    }
    if (
      (step.tool === "generate_draft" || step.tool === "generate_draft_from_images") &&
      output.skill_version
    ) {
      active.set(String(output.skill_name || "当前 Skill"), String(output.skill_version));
    }
    if (step.tool === "route_skill_library") {
      for (const item of (output.items as any[]) || []) {
        routed.set(String(item.slug), String(item.name));
      }
    }
    if (step.tool === "get_skill_library_item" && output.slug) {
      routed.set(String(output.slug), String(output.name || output.slug));
    }
    if (step.tool === "apply_style_skill" || step.tool === "activate_creation_skill") {
      style = String(output.skill_version || style);
    }
    if (step.tool === "distill_writing_style") {
      style = `${String(output.name || "蒸馏写法")}（蒸馏）`;
    }
    if (step.tool === "set_skill_library_enabled") {
      toggles.push(`${String(output.name || output.slug)}：${output.enabled ? "开" : "关"}`);
    }
  }
  return {
    active: [...active.entries()],
    routed: [...routed.values()],
    style,
    toggles,
  };
}

export function XhsAgentPage() {
  const { token } = theme.useToken();
  const [searchParams] = useSearchParams();

  function statusIcon(status: string) {
    if (status === "completed") return <CheckCircleOutlined style={{ color: token.colorSuccess }} />;
    if (status === "failed") return <CloseCircleOutlined style={{ color: token.colorError }} />;
    if (status === "running") return <LoadingOutlined style={{ color: token.colorPrimary }} />;
    return <RobotOutlined style={{ color: token.colorTextTertiary }} />;
  }

  const agentContext = useMemo(() => {
    const next: Record<string, number | string> = {};
    for (const key of ["draft_id", "topic_id", "note_id", "template_id"]) {
      const raw = searchParams.get(key);
      const value = Number(raw);
      if (raw && Number.isFinite(value) && value > 0) next[key] = value;
    }
    const section = searchParams.get("from");
    if (section) next.section = section.slice(0, 40);
    return next;
  }, [searchParams]);
  const [goal, setGoal] = useState("");
  const [running, setRunning] = useState(false);
  const [run, setRun] = useState<AgentRun | null>(null);
  const [history, setHistory] = useState<AgentRun[]>([]);
  const [accounts, setAccounts] = useState<PlatformAccount[]>([]);
  const [accountId, setAccountId] = useState<number | null>(null);
  const [attachedImages, setAttachedImages] = useState<
    Array<{ file_name: string; url: string; preview: string }>
  >([]);
  const [uploadingImage, setUploadingImage] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [planning, setPlanning] = useState(false);
  const [plan, setPlan] = useState<{ summary: string; steps: AgentPlanStep[] } | null>(null);
  const [capabilities, setCapabilities] = useState<AgentCapabilities | null>(null);
  const [overview, setOverview] = useState<AgentOverview | null>(null);
  const [currentSkill, setCurrentSkill] = useState<CreationSkill | null>(null);
  const [libraryTotalCount, setLibraryTotalCount] = useState(0);
  const [libraryEnabledCount, setLibraryEnabledCount] = useState(0);

  useEffect(() => {
    void fetchAgentRuns(10)
      .then((data) => setHistory(data.items))
      .catch(() => setHistory([]));
    void fetchAccounts("xhs")
      .then((items) => {
        setAccounts(items);
        setAccountId((current) => current ?? items[0]?.id ?? null);
      })
      .catch(() => setAccounts([]));
    void fetchAgentCapabilities()
      .then(setCapabilities)
      .catch(() => setCapabilities(null));
    void fetchAgentOverview()
      .then(setOverview)
      .catch(() => setOverview(null));
  }, []);

  useEffect(() => {
    const goalParam = searchParams.get("goal");
    if (goalParam) {
      setGoal(goalParam);
      document.getElementById("agent-goal")?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [searchParams]);

  useEffect(() => {
    if (run?.status && run.status !== "running") {
      void fetchAgentOverview().then(setOverview).catch(() => undefined);
    }
  }, [run?.status]);

  useEffect(() => {
    if (!accountId) {
      setCurrentSkill(null);
      setLibraryTotalCount(0);
      setLibraryEnabledCount(0);
      return;
    }
    void fetchCurrentCreationSkill(accountId)
      .then((result) => setCurrentSkill(result.skill))
      .catch(() => setCurrentSkill(null));
    void fetchSkillLibrary(undefined, accountId)
      .then((data) => {
        setLibraryTotalCount(data.total);
        setLibraryEnabledCount(
          data.items.filter((item) => item.account_enabled !== false).length,
        );
      })
      .catch(() => {
        setLibraryTotalCount(0);
        setLibraryEnabledCount(0);
      });
  }, [accountId]);

  function startScenario(goalText: string) {
    setGoal(goalText);
    document.getElementById("agent-goal")?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  useEffect(() => {
    if (!run || run.status !== "running") return;
    const timer = window.setInterval(async () => {
      try {
        const latest = await fetchAgentRun(run.id);
        setRun(latest);
        if (latest.status !== "running") {
          setHistory((prev) => {
            const exists = prev.some((item) => item.id === latest.id);
            return exists
              ? prev.map((item) => (item.id === latest.id ? latest : item))
              : [latest, ...prev];
          });
        }
      } catch {
        /* transient polling errors are ignored */
      }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [run?.id, run?.status]);

  async function handleImageUpload(file: File) {
    if (!file.type.startsWith("image/")) {
      message.warning("只支持图片文件");
      return false;
    }
    setUploadingImage(true);
    try {
      const uploaded = await uploadAssetFile(file);
      setAttachedImages((prev) =>
        [
          ...prev,
          {
            file_name: uploaded.file_name,
            url: uploaded.download_url,
            preview: URL.createObjectURL(file),
          },
        ].slice(0, 9),
      );
    } catch {
      message.error("图片上传失败");
    } finally {
      setUploadingImage(false);
    }
    return false;
  }

  async function handlePlan() {
    const trimmed = goal.trim();
    if (!trimmed) {
      message.warning("先告诉智能助手你的目标");
      return;
    }
    setPlanning(true);
    setPlan(null);
    try {
      setPlan((await planAgent(trimmed, accountId, agentContext)) as never);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || "计划生成失败，请确认已配置默认文本模型。");
    } finally {
      setPlanning(false);
    }
  }

  async function handleRun(planSteps?: AgentPlanStep[]) {
    const trimmed = goal.trim();
    if (!trimmed) {
      message.warning("先告诉智能助手你的目标");
      return;
    }
    setRunning(true);
    setRun(null);
    try {
      const result = await runAgent(trimmed, accountId, {
        images: attachedImages.map(({ file_name, url }) => ({ file_name, url })),
        plan: planSteps ?? [],
        context: agentContext,
      });
      setRun(result);
      setPlan(null);
      setAttachedImages([]);
      setHistory((prev) => [result, ...prev.filter((item) => item.id !== result.id)].slice(0, 10));
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || "智能助手执行失败，请确认已配置默认文本模型。");
    } finally {
      setRunning(false);
    }
  }

  async function handleConfirmPublish() {
    if (!run) return;
    setConfirming(true);
    try {
      const result = await confirmAgentPublish(run.id);
      setRun(result.run);
      setHistory((prev) => prev.map((item) => (item.id === result.run.id ? result.run : item)));
      message.success(`已创建发布任务 #${result.job.id}，请前往发布中心发布`);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || "创建发布任务失败");
    } finally {
      setConfirming(false);
    }
  }

  async function handleCancelRun() {
    if (!run) return;
    setCancelling(true);
    try {
      const latest = await cancelAgentRun(run.id);
      setRun(latest);
      message.info("已请求取消，当前步骤结束后停止");
    } catch {
      message.error("取消失败");
    } finally {
      setCancelling(false);
    }
  }

  const pendingPublish =
    run?.steps.find((step) => step.tool === "prepare_publish" && step.status === "completed") ?? null;
  const runAccount = accounts.find((account) => account.id === run?.platform_account_id) ?? null;
  const skillSummary = run
    ? runSkillSummary(run)
    : { active: [] as Array<[string, string]>, routed: [] as string[], style: "", toggles: [] as string[] };

  return (
    <div>
      <PageHeader
        eyebrow="智能助手"
        title="智能助手"
        description="跨模块执行：采集、选题、生成草稿、创建发布任务；发布始终需要你手动确认。只改某一篇草稿，去草稿工坊的「草稿助手」。"
      />

      {overview ? (
        <Card size="small" style={{ marginBottom: 16 }}>
          <Space wrap size={8}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              当前工作台：账号 {(overview.counts?.accounts ?? 0)} · 样本 {(overview.counts?.notes ?? 0)} · 草稿{" "}
              {(overview.counts?.drafts ?? 0)} · 待审 {(overview.counts?.pending_drafts ?? 0)}
            </Text>
            {(overview.recent_extract_jobs ?? []).length ? (
              <Tag
                color={(overview.recent_extract_jobs?.[0]?.completed ?? 0) >= 3 ? "green" : "default"}
                style={{ cursor: "pointer" }}
                onClick={() =>
                  startScenario(
                    `把抖音提取任务 #${overview.recent_extract_jobs?.[0]?.id ?? ""} 蒸馏成写法，并生成 3 篇小红书草稿`,
                  )
                }
              >
                最近提取 #{overview.recent_extract_jobs[0].id} · 完成{" "}
                {overview.recent_extract_jobs[0].completed}
              </Tag>
            ) : null}
          </Space>
        </Card>
      ) : null}

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={16}>
          <Card title="目标" style={{ marginBottom: 16 }}>
            <Row gutter={[8, 8]} style={{ marginBottom: 12 }}>
              {SCENARIOS.map((scenario) => (
                <Col xs={24} md={12} key={scenario.key}>
                  <Card
                    size="small"
                    hoverable
                    onClick={() => startScenario(scenario.goal)}
                    style={{ height: "100%", cursor: "pointer" }}
                  >
                    <Space direction="vertical" size={2}>
                      <Space size={6}>
                        <span style={{ color: token.colorPrimary }}>{scenario.icon}</span>
                        <Text strong style={{ fontSize: 13 }}>{scenario.label}</Text>
                      </Space>
                      <Text type="secondary" style={{ fontSize: 11 }}>{scenario.description}</Text>
                    </Space>
                  </Card>
                </Col>
              ))}
            </Row>
            <Select
              allowClear
              value={accountId ?? undefined}
              onChange={(value) => setAccountId(value ?? null)}
              placeholder="绑定要运营的账号（推荐）"
              style={{ width: "100%", marginBottom: 8 }}
              options={accounts.map((account) => ({
                value: account.id,
                label: `${account.nickname || `账号 ${account.id}`} · ${
                  account.sub_type === "creator" ? "Creator" : account.sub_type === "pc" ? "PC" : "未知"
                }`,
              }))}
            />
            <div style={{ marginBottom: 8 }}>
              {accountId ? (
                <Space wrap size={4}>
                  <Text type="secondary" style={{ fontSize: 12 }}>当前创作 Skill：</Text>
                  {currentSkill ? (
                    <Tag color="blue">
                      {currentSkill.name} {currentSkill.version}
                      {currentSkill.status === "active" ? " · 生效中" : ""}
                    </Tag>
                  ) : (
                    <Tag>未设置</Tag>
                  )}
                  <Link to="/platforms/xhs/refine/skills" style={{ fontSize: 12 }}>
                    管理 Skill
                  </Link>
                  <Tag>模块 Skill {libraryEnabledCount}/{libraryTotalCount}</Tag>
                </Space>
              ) : (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  未绑定账号：生成草稿时不会读取账号的创作 Skill。
                </Text>
              )}
            </div>
            {Object.keys(agentContext).length ? (
              <Space wrap size={4} style={{ marginBottom: 8 }}>
                <Text type="secondary" style={{ fontSize: 12 }}>当前上下文：</Text>
                {agentContext.draft_id ? <Tag color="blue">草稿 #{agentContext.draft_id}</Tag> : null}
                {agentContext.topic_id ? <Tag color="gold">选题 #{agentContext.topic_id}</Tag> : null}
                {agentContext.note_id ? <Tag color="cyan">样本 #{agentContext.note_id}</Tag> : null}
                {agentContext.template_id ? <Tag color="purple">模板 #{agentContext.template_id}</Tag> : null}
                {agentContext.section ? <Tag>{agentContext.section}</Tag> : null}
              </Space>
            ) : null}
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
              <Upload
                accept="image/*"
                showUploadList={false}
                beforeUpload={(file) => handleImageUpload(file as File)}
              >
                <Button size="small" icon={<UploadOutlined />} loading={uploadingImage}>
                  上传图片（可选）
                </Button>
              </Upload>
              {attachedImages.map((image) => (
                <div key={image.file_name} style={{ position: "relative", width: 48, height: 48 }}>
                  <img
                    src={image.preview}
                    style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: 8 }}
                  />
                  <Button
                    size="small"
                    type="text"
                    danger
                    icon={<CloseCircleOutlined />}
                    style={{ position: "absolute", top: -8, right: -8 }}
                    onClick={() =>
                      setAttachedImages((prev) => prev.filter((item) => item.file_name !== image.file_name))
                    }
                  />
                </div>
              ))}
              {attachedImages.length > 0 ? (
                <Text type="secondary" style={{ fontSize: 12 }}>有图时会优先用图片写文案</Text>
              ) : null}
            </div>
            <TextArea
              id="agent-goal"
              rows={3}
              value={goal}
              onChange={(event) => setGoal(event.target.value)}
              placeholder="直接说你要什么，例如：把抖音提取任务 #4 蒸馏成写法，再生成 3 篇小红书草稿"
              maxLength={500}
              showCount
            />
            <Space wrap style={{ marginTop: 8 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>也可以直接输入，例如：</Text>
              <Tag style={{ cursor: "pointer" }} onClick={() => startScenario("搜索低粉高赞的通勤穿搭笔记，入库后生成模板")}>
                搜索低粉高赞笔记并建模板
              </Tag>
              <Tag style={{ cursor: "pointer" }} onClick={() => startScenario("给最近一篇草稿做体检并推荐话题")}>
                给草稿做体检
              </Tag>
              <Tag style={{ cursor: "pointer" }} onClick={() => startScenario("复盘这周发布的数据")}>
                复盘这周数据
              </Tag>
            </Space>
            <div style={{ marginTop: 12 }}>
              <Button
                type="primary"
                icon={<SendOutlined />}
                loading={running}
                onClick={() => void handleRun()}
              >
                {running ? "执行中…" : "开始执行"}
              </Button>
              <Button
                style={{ marginLeft: 8 }}
                loading={planning}
                disabled={running}
                onClick={() => void handlePlan()}
              >
                预览计划
              </Button>
              <Text type="secondary" style={{ fontSize: 12, marginLeft: 12 }}>
                只读与建草稿自动执行；不会发布、删除或修改账号。
              </Text>
            </div>
          </Card>

          {plan ? (
            <Card
              title={
                <Space>
                  <RobotOutlined />
                  计划预览
                  <Tag color="blue">{plan.steps.length} 步</Tag>
                </Space>
              }
              extra={
                <Button size="small" loading={planning} onClick={() => void handlePlan()}>
                  重新规划
                </Button>
              }
              style={{ marginBottom: 16 }}
            >
              <Paragraph type="secondary">{plan.summary}</Paragraph>
              <List
                dataSource={plan.steps}
                renderItem={(step, index) => (
                  <List.Item
                    actions={[
                      <Button
                        key="remove"
                        type="link"
                        size="small"
                        danger
                        onClick={() =>
                          setPlan((current) =>
                            current
                              ? { ...current, steps: current.steps.filter((_, i) => i !== index) }
                              : current,
                          )
                        }
                      >
                        移除
                      </Button>,
                    ]}
                  >
                    <List.Item.Meta
                      title={
                        <Space wrap>
                          <Tag color="blue">{index + 1}</Tag>
                          <Text strong>{TOOL_LABELS[step.tool] || step.tool}</Text>
                        </Space>
                      }
                      description={String(step.reason ?? "") || "按工具默认参数执行"}
                    />
                  </List.Item>
                )}
              />
              <Button
                type="primary"
                disabled={!plan.steps.length || running}
                loading={running}
                onClick={() => void handleRun(plan.steps)}
              >
                按此计划执行
              </Button>
            </Card>
          ) : null}

          {running || run?.status === "running" ? (
            <Card>
              <div style={{ textAlign: "center", padding: 32 }}>
                <Spin indicator={<LoadingOutlined style={{ fontSize: 28 }} spin />} />
                <Paragraph type="secondary" style={{ marginTop: 16, marginBottom: 12 }}>
                  正在规划并执行，最多 6 步，通常需要 10–40 秒。
                </Paragraph>
                <Button danger loading={cancelling} onClick={() => void handleCancelRun()}>
                  取消运行
                </Button>
              </div>
            </Card>
          ) : run ? (
            <Card
              title={
                <Space>
                  <RobotOutlined />
                  执行过程
                  <Tag
                    color={
                      run.status === "completed"
                        ? "green"
                        : run.status === "awaiting_confirmation"
                          ? "orange"
                          : run.status === "cancelled"
                            ? "default"
                            : "red"
                    }
                  >
                    {run.status === "completed"
                      ? "已完成"
                      : run.status === "awaiting_confirmation"
                        ? "待确认"
                        : run.status === "cancelled"
                          ? "已取消"
                          : "失败"}
                  </Tag>
                </Space>
              }
            >
              <Card
                size="small"
                style={{ marginBottom: 16, background: token.colorPrimaryBg, borderColor: token.colorPrimaryBorder }}
              >
                <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <Text type="secondary" style={{ fontSize: 11 }}>原始目标</Text>
                    <Paragraph style={{ margin: "4px 0 0", whiteSpace: "pre-wrap", fontSize: 13 }}>
                      {run.goal}
                    </Paragraph>
                  </div>
                  <Space size={4} wrap>
                    <Button
                      size="small"
                      icon={<EditOutlined />}
                      onClick={() => {
                        setGoal(run.goal);
                        window.scrollTo({ top: 0, behavior: "smooth" });
                      }}
                    >
                      复用目标
                    </Button>
                    <Button
                      size="small"
                      icon={<CopyOutlined />}
                      onClick={() => {
                        void navigator.clipboard.writeText(run.goal).then(
                          () => message.success("目标已复制"),
                          () => message.warning("复制失败，请手动选择"),
                        );
                      }}
                    >
                      复制
                    </Button>
                  </Space>
                </div>
                <Text type="secondary" style={{ fontSize: 11, display: "block", marginTop: 8 }}>
                  账号：{runAccount?.nickname || "未绑定"} · 时间：{formatShanghaiTime(run.created_at)}
                </Text>
              </Card>

              <Card
                size="small"
                title="本次用到的 Skill"
                style={{ marginBottom: 16, background: token.colorPrimaryBg, borderColor: token.colorPrimaryBorder }}
              >
                <Space direction="vertical" size={6} style={{ width: "100%" }}>
                  <Space wrap size={4}>
                    <Text type="secondary" style={{ fontSize: 12 }}>账号创作 Skill：</Text>
                    {skillSummary.active.length ? (
                      skillSummary.active.map(([name, version]) => (
                        <Tag key={`${name}-${version}`} color="blue">
                          {name} {version}
                        </Tag>
                      ))
                    ) : currentSkill ? (
                      <Tag color="blue">{currentSkill.name} {currentSkill.version}</Tag>
                    ) : (
                      <Tag>未读取</Tag>
                    )}
                    <Link to="/platforms/xhs/refine/skills" style={{ fontSize: 12 }}>
                      管理
                    </Link>
                  </Space>
                  {skillSummary.style ? (
                    <Space wrap size={4}>
                      <Text type="secondary" style={{ fontSize: 12 }}>风格 Skill：</Text>
                      <Tag color="purple">{skillSummary.style}</Tag>
                    </Space>
                  ) : null}
                  {skillSummary.routed.length ? (
                    <Space wrap size={4}>
                      <Text type="secondary" style={{ fontSize: 12 }}>模块 Skill：</Text>
                      {skillSummary.routed.map((name) => <Tag key={name}>{name}</Tag>)}
                    </Space>
                  ) : null}
                  {skillSummary.toggles.length ? (
                    <Space wrap size={4}>
                      <Text type="secondary" style={{ fontSize: 12 }}>本次切换：</Text>
                      {skillSummary.toggles.map((item) => <Tag key={item}>{item}</Tag>)}
                    </Space>
                  ) : null}
                  {!skillSummary.active.length && !skillSummary.style && !skillSummary.routed.length && !skillSummary.toggles.length ? (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      本次没有读取或切换 Skill；生成草稿时会自动读取账号当前的 active Skill。
                    </Text>
                  ) : null}
                </Space>
              </Card>

              {run.summary ? (
                <Alert type={run.status === "completed" ? "success" : "warning"} showIcon message={run.summary} style={{ marginBottom: 16 }} />
              ) : null}
              {pendingPublish && run.status === "awaiting_confirmation" ? (
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginBottom: 16 }}
                  message={`待发布：${String(pendingPublish.output.title || "")}`}
                  description={`账号：${String(pendingPublish.output.account_name || "")}。智能助手不会自动发布，确认后只创建发布任务。`}
                  action={
                    <Button
                      type="primary"
                      size="small"
                      loading={confirming}
                      onClick={() => void handleConfirmPublish()}
                    >
                      确认并创建任务
                    </Button>
                  }
                />
              ) : null}
              {run.error ? <Alert type="error" showIcon message={run.error} style={{ marginBottom: 16 }} /> : null}

              <List
                dataSource={run.steps}
                renderItem={(step) => (
                  <List.Item>
                    <Space direction="vertical" size={6} style={{ width: "100%" }}>
                      <Space>
                        {statusIcon(step.status)}
                        <Text strong>{TOOL_LABELS[step.tool] || step.tool}</Text>
                        <Text type="secondary" style={{ fontSize: 12 }}>第 {step.step_index} 步</Text>
                        {step.status === "failed" ? <Tag color="red">失败</Tag> : null}
                      </Space>
                      {step.error ? (
                        <Text type="danger" style={{ fontSize: 12 }}>{step.error}</Text>
                      ) : (
                        stepOutput(step)
                      )}
                    </Space>
                  </List.Item>
                )}
              />
              <div style={{ marginTop: 12 }}>{resultLinks(run)}</div>
            </Card>
          ) : (
            <Card>
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="输入目标后，智能助手会给出每一步执行结果"
              />
            </Card>
          )}
        </Col>

        <Col xs={24} lg={8}>
          <Card
            title="能做什么"
            style={{ marginBottom: 16 }}
            extra={<Text type="secondary" style={{ fontSize: 11 }}>点示例直接填入目标</Text>}
          >
            <div style={{ marginBottom: 10 }}>
              <Text type="secondary" style={{ fontSize: 11, display: "block", marginBottom: 4 }}>可接管</Text>
              <Space wrap size={4}>
                {NAV_SECTIONS
                  .filter((section) => section.key !== "/agent" && section.key !== "/settings")
                  .map((section) => (
                    <Tag key={section.key} color="blue" style={{ marginInlineEnd: 0 }}>
                      {section.label}
                    </Tag>
                  ))}
              </Space>
              <Text type="secondary" style={{ fontSize: 11, display: "block", marginTop: 6 }}>
                不接管：批量生成 / 多账号矩阵 / 自动任务 / 设置
              </Text>
            </div>
            <Divider style={{ margin: "8px 0" }} />
            {capabilities ? (
              <Space direction="vertical" size={8} style={{ width: "100%" }}>
                {capabilities.groups
                  .filter((group) => group.primary)
                  .map((group) => (
                    <div key={group.key}>
                      <Button
                        block
                        onClick={() => startScenario(group.examples[0] || group.label)}
                        style={{
                          display: "flex",
                          justifyContent: "flex-start",
                          alignItems: "flex-start",
                          textAlign: "left",
                          height: "auto",
                          padding: "8px 10px",
                        }}
                      >
                        <div style={{ width: "100%", textAlign: "left" }}>
                          <div>
                            <Text strong style={{ fontSize: 13 }}>{group.label}</Text>
                          </div>
                          <div style={{ textAlign: "left" }}>
                            <Text type="secondary" style={{ fontSize: 11 }}>
                              {group.description}
                            </Text>
                          </div>
                        </div>
                      </Button>
                    </div>
                  ))}

                <Collapse
                  size="small"
                  ghost
                  items={[
                    {
                      key: "advanced",
                      label: (
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          高级：查看具体工具和示例
                        </Text>
                      ),
                      children: (
                        <Collapse
                          size="small"
                          ghost
                          items={capabilities.groups.map((group) => ({
                            key: group.key,
                            label: (
                              <Space size={6}>
                                <Text style={{ fontSize: 12 }}>{group.label}</Text>
                                <Tag style={{ marginInlineEnd: 0 }}>{group.items.length}</Tag>
                              </Space>
                            ),
                            children: (
                              <Space direction="vertical" size={6} style={{ width: "100%" }}>
                                <Space size={4} wrap>
                                  {group.examples.map((example) => (
                                    <Button
                                      key={example}
                                      size="small"
                                      onClick={() => startScenario(example)}
                                      style={{ textAlign: "left", height: "auto", whiteSpace: "normal", padding: "2px 8px" }}
                                    >
                                      {example}
                                    </Button>
                                  ))}
                                </Space>
                                <Space size={4} wrap>
                                  {group.items.map((item) => (
                                    <Tag key={item.tool} style={{ fontSize: 11 }} title={item.description}>
                                      {item.label}
                                    </Tag>
                                  ))}
                                </Space>
                              </Space>
                            ),
                          }))}
                        />
                      ),
                    },
                  ]}
                />
              </Space>
            ) : (
              <Text type="secondary" style={{ fontSize: 12 }}>
                能力清单加载失败，可以直接在左侧输入目标。
              </Text>
            )}
            <Divider style={{ margin: "10px 0" }} />
            <Space direction="vertical" size={2}>
              {(capabilities?.safety || [
                "不会自动发布",
                "不会自动私信、评论或关注",
                "不会删除账号、笔记或草稿",
              ]).map((item) => (
                <Text key={item} type="secondary" style={{ fontSize: 11 }}>
                  · {item}
                </Text>
              ))}
            </Space>
          </Card>

          <Card title="最近运行" extra={<Button size="small" onClick={() => void fetchAgentRuns(10).then((data) => setHistory(data.items))}>刷新</Button>}>
            {history.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有运行记录" />
            ) : (
              <List
                dataSource={history}
                renderItem={(item) => (
                  <List.Item
                    style={{ cursor: "pointer" }}
                    onClick={() => {
                      setRun(item);
                      if (item.platform_account_id) setAccountId(item.platform_account_id);
                    }}
                    actions={[
                      <Button
                        key="reuse"
                        type="link"
                        size="small"
                        onClick={(event) => {
                          event.stopPropagation();
                          setGoal(item.goal);
                          if (item.platform_account_id) setAccountId(item.platform_account_id);
                          window.scrollTo({ top: 0, behavior: "smooth" });
                        }}
                      >
                        复用
                      </Button>,
                    ]}
                  >
                    <List.Item.Meta
                      avatar={<ThunderboltOutlined style={{ color: item.status === "completed" ? token.colorSuccess : item.status === "cancelled" ? token.colorTextTertiary : token.colorError }} />}
                      title={<Paragraph ellipsis={{ rows: 2 }} style={{ margin: 0, fontSize: 13 }}>{item.goal}</Paragraph>}
                      description={
                        <Text type="secondary" style={{ fontSize: 11 }}>
                          {formatShanghaiTime(item.created_at)} · {item.steps.length} 步
                        </Text>
                      }
                    />
                  </List.Item>
                )}
              />
            )}
          </Card>
        </Col>
      </Row>

      <NextStepBar
        description="Agent 产出先进入草稿工坊；确认内容和素材后，再送入发布队列。"
        actions={[
          { label: "去草稿工坊", to: "/platforms/xhs/write/drafts", primary: true },
          { label: "去发布队列", to: "/platforms/xhs/publish-hub/jobs" },
        ]}
      />
    </div>
  );
}
