import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  CompassOutlined,
  EditOutlined,
  FileTextOutlined,
  ReloadOutlined,
  SendOutlined,
  SafetyCertificateOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Divider,
  Drawer,
  Empty,
  List,
  Row,
  Space,
  Spin,
  Statistic,
  Steps,
  Tag,
  Typography,
  theme,
} from "antd";
import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Term } from "../../../components/common/term";
import { PageHeader } from "../../../components/layout/app-shell";
import { taskTypeLabel } from "../../../app/labels";
import { useAuth } from "../../../hooks/use-auth";
import {

  fetchAccounts,
  fetchCurrentCreationSkill,
  fetchDrafts,
  fetchModelConfigs,
  fetchAllPublishJobs,
  fetchSavedNotes,
  fetchSavedTopics,
  fetchTasks,
} from "../../../lib/api";
import { formatShanghaiTime } from "../../../lib/time";
import { humanizeTaskError } from "../../../lib/errors";
import type {
  Draft,
  PlatformAccount,
  PublishJob,
  TaskRecord,
} from "../../../types";
import type { SavedTopic } from "../../../lib/api";

const { Text, Paragraph } = Typography;


const JOB_STATUS: Record<string, { color: string; label: string }> = {
  pending: { color: "blue", label: "待发布" },
  scheduled: { color: "cyan", label: "已定时" },
  uploading: { color: "orange", label: "上传中" },
  publishing: { color: "orange", label: "发布中" },
  published: { color: "green", label: "已发布" },
  failed: { color: "red", label: "失败" },
  cancelled: { color: "default", label: "已取消" },
};

function jobStatus(status: string) {
  return JOB_STATUS[status] ?? { color: "default", label: status };
}

function taskTarget(type: string): { to: string; label: string } {
  if (type === "publish" || type === "creator_publish") {
    return { to: "/platforms/xhs/publish-hub/jobs", label: "去发布队列" };
  }
  if (type === "crawl" || type === "monitoring_crawl") {
    return { to: "/platforms/xhs/assets/collect", label: "去采集样本" };
  }
  if (type === "ai_image_generate" || type === "ai_image_generate_cover") {
    return { to: "/platforms/xhs/write/visual/images", label: "去图片素材" };
  }
  if (type.startsWith("ai_")) {
    return { to: "/platforms/xhs/write/drafts", label: "去草稿工坊" };
  }
  return { to: "/settings/tasks", label: "查看运行记录" };
}

function accountStatus(status: string) {
  if (status === "active" || status === "healthy") return { color: "green", label: "正常" };
  if (status === "expired" || status === "risk") return { color: "red", label: "异常" };
  return { color: "default", label: status || "未知" };
}

type TodoItem = {
  key: string;
  icon: ReactNode;
  title: string;
  description: ReactNode;
  to: string;
  actionLabel: string;
};

export function XhsDashboard() {
  const navigate = useNavigate();
  const auth = useAuth();
  const { token } = theme.useToken();
  const cardStyle = { background: token.colorBgContainer, borderColor: token.colorBorderSecondary };
  const [jobs, setJobs] = useState<PublishJob[]>([]);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [draftTotal, setDraftTotal] = useState(0);
  const [accounts, setAccounts] = useState<PlatformAccount[]>([]);
  const [savedTopics, setSavedTopics] = useState<SavedTopic[]>([]);
  const [sampleTotal, setSampleTotal] = useState(0);
  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  const [hasLoadedOnce, setHasLoadedOnce] = useState(false);
  const storageKey = `xhs-todo-done:${auth.user?.username ?? "guest"}`;
  const [doneKeys, setDoneKeys] = useState<Set<string>>(new Set());
  const [showDone, setShowDone] = useState(false);
  const [onboarding, setOnboarding] = useState({ hasModel: false, hasSkill: false });
  const [onboardingLoaded, setOnboardingLoaded] = useState(false);
  const setupStorageKey = `xhs-setup-dismissed:${auth.user?.username ?? "guest"}`;
  const [setupDismissed, setSetupDismissed] = useState(false);
  const [guideOpen, setGuideOpen] = useState(false);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(storageKey);
      setDoneKeys(new Set<string>(raw ? JSON.parse(raw) : []));
    } catch {
      setDoneKeys(new Set());
    }
  }, [storageKey]);

  function persistDone(next: Set<string>) {
    setDoneKeys(next);
    try {
      window.localStorage.setItem(storageKey, JSON.stringify([...next]));
    } catch {
      /* 忽略存储配额异常 */
    }
  }

  function markDone(key: string) {
    const next = new Set(doneKeys);
    next.add(key);
    persistDone(next);
  }

  function undoDone(key: string) {
    const next = new Set(doneKeys);
    next.delete(key);
    persistDone(next);
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      const [jobsRes, draftsRes, accountsRes, tasksRes, topicsRes, samplesRes] = await Promise.allSettled([
        fetchAllPublishJobs("xhs"),
        fetchDrafts("xhs", { page: 1, page_size: 100 }),
        fetchAccounts("xhs"),
        fetchTasks("xhs", "system"),
        fetchSavedTopics(),
        fetchSavedNotes({ platform: "xhs", source: "library", page: 1, page_size: 1 }),
      ]);
      if (cancelled) return;
      const failures: string[] = [];
      if (jobsRes.status === "fulfilled") setJobs(jobsRes.value); else failures.push("发布任务");
      if (draftsRes.status === "fulfilled") {
        setDrafts(draftsRes.value.items);
        setDraftTotal(draftsRes.value.total);
      } else failures.push("草稿");
      if (accountsRes.status === "fulfilled") setAccounts(accountsRes.value); else failures.push("账号");
      if (tasksRes.status === "fulfilled") setTasks(tasksRes.value.items); else failures.push("任务");
      if (topicsRes.status === "fulfilled") setSavedTopics(topicsRes.value.items); else failures.push("选题");
      if (samplesRes.status === "fulfilled") setSampleTotal(samplesRes.value.total); else failures.push("样本");
      setLoadError(failures.length ? `部分数据加载失败：${failures.join("、")}` : null);
      setLoading(false);
      setHasLoadedOnce(true);
    })();
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  useEffect(() => {
    let cancelled = false;
    const accountId = accounts[0]?.id;
    (async () => {
      const [models, skill] = await Promise.allSettled([
        fetchModelConfigs("text"),
        accountId ? fetchCurrentCreationSkill(accountId) : Promise.resolve({ skill: null }),
      ]);
      if (cancelled) return;
      setOnboarding({
        hasModel: models.status === "fulfilled" && models.value.items.length > 0,
        hasSkill: skill.status === "fulfilled" && Boolean(skill.value?.skill),
      });
      setOnboardingLoaded(true);
    })();
    return () => {
      cancelled = true;
    };
  }, [reloadKey, accounts]);

  useEffect(() => {
    try {
      setSetupDismissed(window.localStorage.getItem(setupStorageKey) === "1");
    } catch {
      setSetupDismissed(false);
    }
  }, [setupStorageKey]);

  function dismissSetup() {
    setSetupDismissed(true);
    try {
      window.localStorage.setItem(setupStorageKey, "1");
    } catch {
      /* 忽略存储配额异常 */
    }
  }

  const setupSteps = [
    {
      key: "account",
      title: "绑定小红书账号",
      description: "先用 PC 账号采集；发布需要再绑定 Creator 账号。",
      done: accounts.length > 0,
      to: "/settings/accounts",
    },
    {
      key: "model",
      title: "配置文本模型",
      description: "AI 改写和标题生成都需要一个可用的文本模型。",
      done: onboarding.hasModel,
      to: "/settings/models",
    },
    {
      key: "sample",
      title: "采集参考样本",
      description: "先存 1 篇外部样本；有样本后再蒸馏 Skill 或模板，不需要从零写。",
      done: sampleTotal > 0,
      to: "/platforms/xhs/assets/collect",
    },
    {
      key: "skill",
      title: "确认创作 Skill",
      description: "有样本后确认长期写法；没有样本也可以先写通用草稿。",
      done: onboarding.hasSkill,
      to: accounts[0]
        ? `/platforms/xhs/refine/skills?account_id=${accounts[0].id}`
        : "/platforms/xhs/refine/skills",
    },
    {
      key: "draft",
      title: "生成第一篇草稿",
      description: "从样本库或选题开始，走一遍审核和发布预检。",
      done: draftTotal > 0,
      to: "/platforms/xhs/write/drafts",
    },
  ];
  const setupDone = setupSteps.filter((step) => step.done).length;
  const initialLoading = loading && !hasLoadedOnce;
  const showSetup =
    hasLoadedOnce &&
    onboardingLoaded &&
    setupDone < setupSteps.length &&
    !setupDismissed;

  const allPendingJobs = jobs.filter((job) =>
    ["pending", "scheduled", "uploading", "publishing"].includes(job.status),
  );
  const pendingJobs = allPendingJobs.slice(0, 5);
  const failedTaskGroups = useMemo(() => {
    const cutoff = Date.now() - 7 * 24 * 60 * 60 * 1000;
    const grouped = new Map<string, { task: TaskRecord; count: number }>();
    tasks
      .filter((task) => task.status === "failed" && new Date(task.created_at).getTime() >= cutoff)
      .forEach((task) => {
        const key = `${task.task_type}|${task.error_type ?? ""}`;
        const existing = grouped.get(key);
        if (existing) existing.count += 1;
        else grouped.set(key, { task, count: 1 });
      });
    return Array.from(grouped.values()).slice(0, 3);
  }, [tasks]);
  const riskAccounts = accounts.filter((account) => !["active", "healthy"].includes(account.status));

  const todoItems: TodoItem[] = [
    ...pendingJobs.map((job): TodoItem => ({
      key: `job:${job.id}`,
      icon: <ClockCircleOutlined style={{ fontSize: 18, color: token.colorPrimary }} />,
      title: job.title || `发布任务 #${job.id}`,
      description: (
        <Space size={6}>
          <Tag color={jobStatus(job.status).color}>{jobStatus(job.status).label}</Tag>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {job.scheduled_at
              ? `定时：${formatShanghaiTime(job.scheduled_at)}`
              : `创建：${formatShanghaiTime(job.created_at)}`}
          </Text>
        </Space>
      ),
      to: "/platforms/xhs/publish-hub/jobs",
      actionLabel: "去发布",
    })),
    ...failedTaskGroups.map(({ task, count }): TodoItem => {
      const errorText = humanizeTaskError(task);
      const target = taskTarget(task.task_type);
      return {
        key: `task:${task.task_type}:${task.error_type ?? ""}:${task.created_at}`,
        icon: <WarningOutlined style={{ fontSize: 18, color: token.colorError }} />,
        title: `${taskTypeLabel(task.task_type)} 执行失败${count > 1 ? `（${count} 次）` : ""}`,
        description: (
          <Text type="secondary" style={{ fontSize: 12 }}>
            {errorText} · {formatShanghaiTime(task.created_at)}
          </Text>
        ),
        to: target.to,
        actionLabel: target.label,
      };
    }),
    ...riskAccounts.map((account): TodoItem => ({
      key: `account:${account.id}:${account.status}`,
      icon: <WarningOutlined style={{ fontSize: 18, color: token.colorWarning }} />,
      title: `账号「${account.nickname || `#${account.id}`}」状态异常`,
      description: (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {accountStatus(account.status).label} · 建议重新登录或检查 Cookie
        </Text>
      ),
      to: "/settings/accounts",
      actionLabel: "去处理",
    })),
  ];
  const activeTodos = todoItems.filter((item) => !doneKeys.has(item.key));
  const doneTodos = todoItems.filter((item) => doneKeys.has(item.key));

  const metrics = [
    {
      label: "待发布",
      value: allPendingJobs.length,
      icon: <SendOutlined />,
      link: "/platforms/xhs/publish-hub/jobs",
      danger: false,
    },
    {
      label: "待写草稿",
      value: draftTotal,
      icon: <FileTextOutlined />,
      link: "/platforms/xhs/write/drafts",
      danger: false,
    },
    {
      label: "账号异常",
      value: riskAccounts.length,
      icon: <WarningOutlined />,
      link: "/settings/accounts",
      danger: riskAccounts.length > 0,
    },
  ];

  const newTopicCount = savedTopics.filter((topic) => topic.status === "new").length;
  const hasPublished = jobs.some((job) => job.status === "published");
  const missingMediaCount = drafts.filter((draft) => draft.media_ready === false).length;
  const missingAccountCount = drafts.filter((draft) => draft.account_ready === false).length;
  const publishableDrafts = drafts.filter(
    (draft) => draft.media_ready !== false && draft.account_ready !== false,
  ).length;
  const primaryAction =
    accounts.length === 0
      ? {
          key: "account",
          title: "先绑定一个小红书账号",
          description: "PC 账号用于采集和保存笔记；要发布还需要 Creator 账号。",
          cta: "去绑定账号",
          to: "/settings/accounts",
          icon: <SafetyCertificateOutlined />,
          color: token.colorWarning,
        }
      : riskAccounts.length > 0
        ? {
            key: "account",
            title: `先处理 ${riskAccounts.length} 个异常账号`,
            description: "登录态异常会卡住采集和发布；恢复后再继续主路径。",
            cta: "去处理账号",
            to: "/settings/accounts",
            icon: <WarningOutlined />,
            color: token.colorError,
          }
        : allPendingJobs.length > 0
          ? {
              key: "publish",
              title: `有 ${allPendingJobs.length} 个发布任务待处理`,
              description: "总览只提醒，不在这里取消或重试；发布动作统一去发布中心完成。",
              cta: "去发布队列",
              to: "/platforms/xhs/publish-hub/jobs",
              icon: <SendOutlined />,
              color: token.colorPrimary,
            }
          : draftTotal > 0 && !hasPublished && publishableDrafts > 0
            ? {
                key: "firstPublish",
                title: `这 ${draftTotal} 篇草稿，还没发出去过一篇`,
                description: "挑一篇素材和账号都已就绪的草稿，走完预检后送进发布队列。",
                cta: "去发第一篇",
                to: "/platforms/xhs/write/drafts?intent=publish",
                icon: <SendOutlined />,
                color: token.colorPrimary,
              }
            : draftTotal > 0 && !hasPublished
            ? {
                key: "firstPublishBlocked",
                title: `这 ${draftTotal} 篇草稿还没准备好发布`,
                description: [
                  missingMediaCount ? `${missingMediaCount} 篇缺素材` : "",
                  missingAccountCount ? `${missingAccountCount} 篇缺账号` : "",
                ].filter(Boolean).join("，") + "。先补齐再送发布。",
                cta: "去补齐草稿",
                to: "/platforms/xhs/write/drafts?intent=publish&readiness=missing_media",
                icon: <WarningOutlined />,
                color: token.colorWarning,
              }
            : draftTotal > 0
            ? {
                key: "write",
                title: `继续改这 ${draftTotal} 篇草稿`,
                description: "先体检、配图，再送入发布中心；草稿不会自动发布。",
                cta: "继续写草稿",
                to: "/platforms/xhs/write/drafts",
                icon: <EditOutlined />,
                color: token.colorPrimary,
              }
            : newTopicCount > 0
              ? {
                  key: "topic",
                  title: `从 ${newTopicCount} 个待写选题里挑一个`,
                  description: "生成草稿后，再走体检、配图和发布预检。",
                  cta: "去选题库",
                  to: "/platforms/xhs/plan",
                  icon: <CompassOutlined />,
                  color: token.colorWarning,
                }
              : {
                  key: "topic",
                  title: "先找一批选题",
                  description: "从素材或选题库确定这周写什么，再开始第一篇草稿。",
                  cta: "去找选题",
                  to: "/platforms/xhs/plan",
                  icon: <CompassOutlined />,
                  color: token.colorWarning,
                };

  const mainPathSteps: Array<{
    title: string;
    description: string;
    status: "wait" | "process" | "finish" | "error";
  }> = [
    {
      title: "找选题",
      description: "素材 / 选题库",
      status: draftTotal > 0 || newTopicCount > 0 ? "finish" : "process",
    },
    {
      title: "写草稿",
      description: "草稿工坊",
      status: draftTotal > 0 ? "finish" : newTopicCount > 0 ? "process" : "wait",
    },
    {
      title: "体检配图",
      description:
        draftTotal === 0
          ? "草稿工坊 · 行内配图"
          : missingMediaCount > 0
            ? `${missingMediaCount} 篇缺素材`
            : missingAccountCount > 0
              ? `${missingAccountCount} 篇缺账号`
              : "已配齐",
      status:
        draftTotal === 0
          ? "wait"
          : missingMediaCount === 0 && missingAccountCount === 0
            ? "finish"
            : "error",
    },
    {
      title: "送发布",
      description: "发布队列",
      status: hasPublished ? "finish" : publishableDrafts > 0 ? "process" : "wait",
    },
    {
      title: "复盘",
      description: "发布后再看数据",
      status: hasPublished ? "process" : "wait",
    },
  ];
  const primaryStep = Math.max(
    0,
    mainPathSteps.findIndex((step) => step.status === "process" || step.status === "error"),
  );

  function renderSetupChecklist(drawer = false) {
    return (
      <Row gutter={[12, 12]}>
        {setupSteps.map((step) => (
          <Col xs={24} md={drawer ? 24 : 8} key={step.key}>
            <div
              style={{
                border: `1px solid ${token.colorBorderSecondary}`,
                borderRadius: 8,
                padding: 12,
                height: "100%",
              }}
            >
              <Space align="start">
                {step.done ? (
                  <CheckCircleOutlined style={{ color: token.colorSuccess, marginTop: 3 }} />
                ) : (
                  <ClockCircleOutlined style={{ color: token.colorWarning, marginTop: 3 }} />
                )}
                <div>
                  <Text strong delete={step.done}>
                    {step.title}
                  </Text>
                  <Paragraph type="secondary" style={{ margin: "4px 0 8px", fontSize: 12 }}>
                    {step.description}
                  </Paragraph>
                  {step.done ? (
                    <Tag color="green">已完成</Tag>
                  ) : (
                    <Button size="small" onClick={() => navigate(step.to)}>
                      去完成
                    </Button>
                  )}
                </div>
              </Space>
            </div>
          </Col>
        ))}
      </Row>
    );
  }

  return (
    <div>
      <PageHeader
        eyebrow="工作台"
        title="小红书工作台"
        description={
          <>
            今天该发什么、该复盘什么、该处理什么。主路径：素材 →{" "}
            <Term k="skill">Skill</Term> → 写稿 → 发布 → 复盘。
          </>
        }
        action={
          <Space>
            <Button icon={<CompassOutlined />} onClick={() => setGuideOpen(true)}>
              新手引导
            </Button>
            <Button icon={<ReloadOutlined />} loading={loading} onClick={() => setReloadKey((key) => key + 1)}>
              刷新
            </Button>
          </Space>
        }
      />

      {loadError ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message={loadError}
          description="页面上的 0 或空列表可能只是因为接口失败，不代表没有数据。"
          action={
            <Button size="small" onClick={() => setReloadKey((key) => key + 1)}>
              重试
            </Button>
          }
        />
      ) : null}

      {initialLoading ? (
        <Card style={{ ...cardStyle, marginBottom: 16 }}>
          <div style={{ textAlign: "center", padding: 28 }}>
            <Spin size="large" />
            <Paragraph type="secondary" style={{ margin: "12px 0 0" }}>
              正在读取账号、草稿和发布任务……
            </Paragraph>
          </div>
        </Card>
      ) : (
        <Card
          style={{
            ...cardStyle,
            marginBottom: 16,
            borderColor: primaryAction.color,
            background: `linear-gradient(135deg, ${primaryAction.color}14, ${token.colorBgContainer} 62%)`,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 16,
              flexWrap: "wrap",
            }}
          >
            <Space align="start" size={14}>
              <div
                style={{
                  width: 46,
                  height: 46,
                  borderRadius: 12,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  background: `${primaryAction.color}22`,
                  color: primaryAction.color,
                  fontSize: 22,
                  flex: "0 0 auto",
                }}
              >
                {primaryAction.icon}
              </div>
              <div>
                <Space size={8} wrap>
                  <Text strong style={{ fontSize: 18 }}>{primaryAction.title}</Text>
                  <Tag color="processing" style={{ marginInlineEnd: 0 }}>今天先做</Tag>
                </Space>
                <Paragraph type="secondary" style={{ margin: "6px 0 0", fontSize: 13 }}>
                  {primaryAction.description}
                </Paragraph>
              </div>
            </Space>
            <Button type="primary" size="large" onClick={() => navigate(primaryAction.to)}>
              {primaryAction.cta}
            </Button>
          </div>
          {setupDone === setupSteps.length ? (
            <>
              <Divider style={{ margin: "16px 0 14px" }} />
              <Steps size="small" current={primaryStep} items={mainPathSteps} />
              <Text type="secondary" style={{ display: "block", fontSize: 12, marginTop: 8 }}>
                日常主路径；发布前以草稿页的「发布就绪」检查为准。
              </Text>
            </>
          ) : (
            <Text type="secondary" style={{ display: "block", fontSize: 12, marginTop: 12 }}>
              先完成下方「开始使用」清单，主路径步骤会在准备完成后出现。
            </Text>
          )}
        </Card>
      )}

      {showSetup ? (
        <Card
          title={
            <Space>
              <Text strong>开始使用</Text>
              <Tag color="blue">{setupDone}/{setupSteps.length}</Tag>
            </Space>
          }
          extra={
            <Button type="link" size="small" onClick={dismissSetup}>
              不再显示此清单
            </Button>
          }
          style={{ ...cardStyle, marginBottom: 16 }}
        >
          <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 12 }}>
            顺序：账号 → 模型 → 参考样本 →{" "}
            <Term k="skill">创作 Skill</Term> → 第一篇草稿。先有样本，再蒸馏 Skill；发布前再看草稿页的{" "}
            <Term k="preflight">发布就绪</Term>。
          </Paragraph>
          {renderSetupChecklist()}
        </Card>
      ) : null}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
          gap: 16,
          marginBottom: 16,
        }}
      >
        {metrics.map((metric) => (
          <Card
            key={metric.label}
            size="small"
            hoverable
            onClick={() => navigate(metric.link)}
            style={{
              ...cardStyle,
              height: "100%",
              borderColor: metric.danger ? token.colorError : token.colorBorderSecondary,
            }}
            tabIndex={0}
            role="link"
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                navigate(metric.link);
              }
            }}
            aria-label={`${metric.label}：${metric.value}，打开详情`}
          >
            <Statistic
              title={metric.label}
              value={metric.value}
              loading={initialLoading}
              prefix={metric.icon}
              valueStyle={metric.danger ? { color: token.colorError } : undefined}
            />
          </Card>
        ))}
      </div>

      {riskAccounts.length > 0 ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={`有 ${riskAccounts.length} 个账号状态异常，建议先处理登录态再发布。`}
          action={
            <Button size="small" onClick={() => navigate("/settings/accounts")}>
              去处理
            </Button>
          }
        />
      ) : null}

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} lg={16}>
          <Card
            title="待办"
            extra={
              <Space size={8}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  已完成 {doneTodos.length}/{todoItems.length}
                </Text>
                {doneTodos.length > 0 ? (
                  <Button type="link" size="small" onClick={() => setShowDone((value) => !value)}>
                    {showDone ? "隐藏已处理" : `查看已处理 (${doneTodos.length})`}
                  </Button>
                ) : null}
              </Space>
            }
            style={{ ...cardStyle, height: "100%" }}
          >
            {loading ? (
              <Spin style={{ display: "block", textAlign: "center", padding: 24 }} />
            ) : activeTodos.length === 0 ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={todoItems.length ? "待办都处理完了，可以继续做新内容" : "今天没有待办，去发现点新选题吧"}
              />
            ) : (
              <List
                dataSource={activeTodos}
                renderItem={(item) => (
                  <List.Item
                    actions={[
                      <Button
                        key="go"
                        type="link"
                        size="small"
                        onClick={() => navigate(item.to)}
                      >
                        {item.actionLabel}
                      </Button>,
                    ]}
                  >
                    <Checkbox style={{ marginRight: 12 }} onChange={() => markDone(item.key)} />
                    <List.Item.Meta
                      avatar={item.icon}
                      title={<Text ellipsis>{item.title}</Text>}
                      description={item.description}
                    />
                  </List.Item>
                )}
              />
            )}
            {showDone && doneTodos.length > 0 ? (
              <>
                <Divider style={{ margin: "8px 0" }} />
                <List
                  size="small"
                  dataSource={doneTodos}
                  renderItem={(item) => (
                    <List.Item
                      actions={[
                        <Button key="undo" type="link" size="small" onClick={() => undoDone(item.key)}>
                          撤销
                        </Button>,
                      ]}
                    >
                      <Checkbox checked disabled style={{ marginRight: 12 }} />
                      <Text delete type="secondary">
                        {item.title}
                      </Text>
                    </List.Item>
                  )}
                />
              </>
            ) : null}
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card
            title="账号状态"
            extra={<Link to="/settings/accounts">管理</Link>}
            style={{ ...cardStyle, height: "100%" }}
          >
            {accounts.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有绑定账号" />
            ) : (
              <List
                dataSource={accounts.slice(0, 6)}
                renderItem={(account) => (
                  <List.Item>
                    <List.Item.Meta
                      avatar={
                        account.status === "active" || account.status === "healthy" ? (
                          <CheckCircleOutlined style={{ fontSize: 18, color: token.colorSuccess }} />
                        ) : (
                          <WarningOutlined style={{ fontSize: 18, color: token.colorError }} />
                        )
                      }
                      title={account.nickname || `账号 #${account.id}`}
                      description={
                        <Space size={6}>
                          <Tag>{account.sub_type === "creator" ? "Creator" : account.sub_type === "pc" ? "PC" : "未知"}</Tag>
                          <Tag color={accountStatus(account.status).color}>{accountStatus(account.status).label}</Tag>
                        </Space>
                      }
                    />
                  </List.Item>
                )}
              />
            )}
          </Card>
        </Col>
      </Row>
      <Drawer
        title="新手引导"
        placement="right"
        size="min(520px, 100vw)"
        open={guideOpen}
        onClose={() => setGuideOpen(false)}
      >
        <Paragraph type="secondary" style={{ marginBottom: 12 }}>
          顺序：账号 → 模型 → 参考样本 →{" "}
          <Term k="skill">创作 Skill</Term> → 第一篇草稿。发布前再看草稿页的{" "}
          <Term k="preflight">发布就绪</Term>。当前完成 {setupDone}/{setupSteps.length}。
        </Paragraph>
        {renderSetupChecklist(true)}
        <Divider />
        <Button block onClick={() => { dismissSetup(); setGuideOpen(false); }}>
          不再自动显示
        </Button>
      </Drawer>
    </div>
  );
}
