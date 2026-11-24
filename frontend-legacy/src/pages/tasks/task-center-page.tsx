import {
  ClockCircleOutlined,
  CloseCircleOutlined,
  DashboardOutlined,
  ReloadOutlined,
  SyncOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Progress,
  Row,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  Typography,
  theme,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { PageHeader } from "../../components/layout/app-shell";
import { NextStepBar } from "../../components/layout/next-step-bar";
import { taskTypeLabel } from "../../app/labels";
import {
  cancelTask,
  fetchSchedulerStatus,
  fetchSystemDiagnostics,
  fetchTasks,
  retryTask,
  runDueTasks,
} from "../../lib/api";
import type { SystemDiagnostics } from "../../lib/api";
import { formatShanghaiTime } from "../../lib/time";
import type { SchedulerStatus, TaskRecord } from "../../types";

const { Text } = Typography;



function businessTaskTarget(type: string): { to: string; label: string } | null {
  if (type.startsWith("creator_publish") || type === "publish") {
    return { to: "/platforms/xhs/publish-hub/jobs", label: "去发布队列" };
  }
  if (type === "auto_ops_run") {
    return { to: "/platforms/xhs/write/batch?mode=auto", label: "去批量生成" };
  }
  if (type.startsWith("douyin_") || type === "extract") {
    return { to: "/platforms/xhs/assets/douyin", label: "去抖音口播提取" };
  }
  return null;
}


function formatTaskTime(value: string): string {
  return formatShanghaiTime(value);
}

const taskStatusLabels: Record<string, string> = {
  pending: "待执行",
  running: "执行中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
  exhausted: "已重试耗尽",
};

function statusColor(status: string): string {
  switch (status) {
    case "running":
      return "processing";
    case "completed":
      return "success";
    case "failed":
    case "exhausted":
      return "error";
    case "cancelled":
      return "default";
    case "pending":
      return "warning";
    default:
      return "default";
  }
}

export function TaskCenterPage() {
  const navigate = useNavigate();
  const { token } = theme.useToken();
  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isActionLoading, setIsActionLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [schedulerStatus, setSchedulerStatus] =
    useState<SchedulerStatus | null>(null);
  const [diagnostics, setDiagnostics] = useState<SystemDiagnostics | null>(null);

  async function loadTasks() {
    setIsLoading(true);
    setError(null);
    try {
      const [taskResult, statusResult, diagnosticsResult] = await Promise.all([
        fetchTasks("xhs", "system"),
        fetchSchedulerStatus(),
        fetchSystemDiagnostics().catch(() => null),
      ]);
      setTasks(taskResult.items);
      setSchedulerStatus(statusResult);
      setDiagnostics(diagnosticsResult);
    } catch {
      setError("任务列表加载失败。");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void loadTasks();
  }, []);

  function replaceTask(updatedTask: TaskRecord) {
    setTasks((currentTasks) =>
      currentTasks.map((task) =>
        task.id === updatedTask.id ? updatedTask : task
      )
    );
  }

  async function cancelSelectedTask(taskId: number) {
    setIsActionLoading(true);
    try {
      replaceTask(await cancelTask(taskId));
      message.success(`任务 #${taskId} 已取消。`);
    } catch {
      message.error(`任务 #${taskId} 取消失败。`);
    } finally {
      setIsActionLoading(false);
    }
  }

  async function retrySelectedTask(taskId: number) {
    setIsActionLoading(true);
    try {
      replaceTask(await retryTask(taskId));
      message.success(`任务 #${taskId} 已重新入队。`);
    } catch {
      message.error(`任务 #${taskId} 重试失败。`);
    } finally {
      setIsActionLoading(false);
    }
  }

  async function runDueXhsTasks() {
    setIsActionLoading(true);
    try {
      const result = await runDueTasks("xhs");
      const summary = `到期任务执行完成：执行 ${result.executed_count} 个，失败 ${result.failed_count} 个。`;
      if (result.failed_count > 0) message.warning(summary);
      else message.success(summary);
      await loadTasks();
    } catch {
      message.error("到期任务执行失败。");
    } finally {
      setIsActionLoading(false);
    }
  }

  const columns: ColumnsType<TaskRecord> = [
    {
      title: "类型",
      dataIndex: "task_type",
      key: "task_type",
      width: 140,
      render: (type: string) => taskTypeLabel(type),
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 100,
      render: (status: string) => (
        <Tag color={statusColor(status)}>{taskStatusLabels[status] || status}</Tag>
      ),
    },
    {
      title: "进度",
      dataIndex: "progress",
      key: "progress",
      width: 160,
      render: (progress: number) => (
        <Progress percent={progress} size="small" />
      ),
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 180,
      render: (value: string) => formatTaskTime(value),
    },
    {
      title: "操作",
      key: "actions",
      width: 180,
      render: (_: unknown, record: TaskRecord) => {
        const target = businessTaskTarget(record.task_type);
        if (target) {
          return (
            <Button size="small" type="link" onClick={() => navigate(target.to)}>
              {target.label}
            </Button>
          );
        }
        return (
          <Space>
            <Button
              size="small"
              icon={<CloseCircleOutlined />}
              disabled={
                isActionLoading ||
                !["pending", "running"].includes(record.status)
              }
              onClick={() => cancelSelectedTask(record.id)}
            >
              取消
            </Button>
            <Button
              size="small"
              icon={<ReloadOutlined />}
              disabled={isActionLoading || record.status !== "failed"}
              onClick={() => retrySelectedTask(record.id)}
            >
              重试
            </Button>
          </Space>
        );
      },
    },
  ];

  const cardStyle = { background: token.colorBgContainer, borderColor: token.colorBorderSecondary };

  return (
    <div>
      <PageHeader
        eyebrow="自动化"
        title="运行记录"
        description="抓取、AI、导出等系统任务的统一队列；发布、提取、批量生成的失败请回各自领域页处理。"
        action={
          <Space>
            <Button
              icon={<ThunderboltOutlined />}
              onClick={runDueXhsTasks}
              disabled={isLoading || isActionLoading}
            >
              执行到期任务
            </Button>
            <Button
              icon={<ReloadOutlined />}
              onClick={loadTasks}
              loading={isLoading}
            >
              刷新
            </Button>
          </Space>
        }
      />

      {error && (
        <Alert
          type="error"
          message={error}
          showIcon
          closable
          style={{ marginBottom: 16 }}
        />
      )}

      {schedulerStatus && (
        <Card
          title={
            <Space>
              <Text>后台调度</Text>
              <Tag
                color={
                  schedulerStatus.enabled && schedulerStatus.running
                    ? "success"
                    : "default"
                }
              >
                {schedulerStatus.enabled
                  ? schedulerStatus.running
                    ? "运行中"
                    : "已启用"
                  : "未启用"}
              </Tag>
            </Space>
          }
          style={{ ...cardStyle, marginBottom: 24 }}
        >
          <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
            <Col xs={12} sm={6}>
              <Statistic
                title="运行状态"
                value={schedulerStatus.running ? "Running" : "Stopped"}
                prefix={<DashboardOutlined />}
              />
            </Col>
            <Col xs={12} sm={6}>
              <Statistic
                title="调度间隔"
                value={schedulerStatus.interval_seconds}
                suffix="s"
                prefix={<ClockCircleOutlined />}
              />
            </Col>
            <Col xs={12} sm={6}>
              <Statistic
                title="注册任务"
                value={schedulerStatus.jobs.length}
                prefix={<SyncOutlined />}
              />
            </Col>
            <Col xs={12} sm={6}>
              <Statistic
                title="最近记录"
                value={schedulerStatus.recent_tasks.length}
                prefix={<CloseCircleOutlined />}
              />
            </Col>
          </Row>
          {schedulerStatus.jobs.length === 0 ? (
            <Text type="secondary">
              调度器当前未注册后台 job。本地默认关闭，开启需设置
              SCHEDULER_ENABLED=true。
            </Text>
          ) : (
            schedulerStatus.jobs.map((job) => (
              <div key={job.id}>
                <Text type="secondary">
                  {job.id} · 下次运行{" "}
                  {job.next_run_time
                    ? formatTaskTime(job.next_run_time)
                    : "-"}
                </Text>
              </div>
            ))
          )}
        </Card>
      )}

      {diagnostics ? (
        <Card
          title={`系统诊断（近 ${diagnostics.window_days} 天）`}
          style={{ ...cardStyle, marginBottom: 24 }}
        >
          <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
            <Col xs={12} sm={6}>
              <Statistic title="API 错误" value={diagnostics.summary.api_errors} />
            </Col>
            <Col xs={12} sm={6}>
              <Statistic title="失败任务" value={diagnostics.summary.failed_tasks} />
            </Col>
            <Col xs={12} sm={6}>
              <Statistic title="账号异常" value={diagnostics.summary.account_issues} />
            </Col>
            <Col xs={12} sm={6}>
              <Statistic title="模板失效任务" value={diagnostics.summary.template_issues} />
            </Col>
          </Row>

          {diagnostics.api_errors.length ? (
            <div style={{ marginBottom: 12 }}>
              <Text strong>最近 API 错误</Text>
              {diagnostics.api_errors.slice(0, 5).map((item) => (
                <div key={item.id}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {item.method || "-"} {item.endpoint} · {item.status_code || "-"} ·{" "}
                    {formatTaskTime(item.created_at)}
                  </Text>
                </div>
              ))}
            </div>
          ) : null}

          {diagnostics.failed_tasks.length ? (
            <div style={{ marginBottom: 12 }}>
              <Text strong>最近失败任务</Text>
              {diagnostics.failed_tasks.slice(0, 5).map((item) => (
                <div key={item.id}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    #{item.id} {taskTypeLabel(item.task_type)} ·{" "}
                    {item.error_type || "失败"} · {formatTaskTime(item.created_at)}
                  </Text>
                </div>
              ))}
            </div>
          ) : null}

          {diagnostics.account_issues.length || diagnostics.template_issues.length ? (
            <div>
              <Text strong>需要处理</Text>
              {diagnostics.account_issues.map((item) => (
                <div key={`account-${item.id}`}>
                  <Text type="warning" style={{ fontSize: 12 }}>
                    账号 {item.nickname || item.id}（{item.sub_type}）状态为 {item.status}
                  </Text>
                </div>
              ))}
              {diagnostics.template_issues.map((item) => (
                <div key={`template-${item.auto_task_id}`}>
                  <Text type="warning" style={{ fontSize: 12 }}>
                    自动任务「{item.name}」的模板 #{item.template_id}：{item.reason}
                  </Text>
                </div>
              ))}
            </div>
          ) : null}

          {!diagnostics.api_errors.length &&
          !diagnostics.failed_tasks.length &&
          !diagnostics.account_issues.length &&
          !diagnostics.template_issues.length ? (
            <Text type="success">近 {diagnostics.window_days} 天没有发现可处理的异常。</Text>
          ) : null}
        </Card>
      ) : null}

      <Card style={cardStyle}>
        {isLoading ? (
          <div style={{ textAlign: "center", padding: 48 }}>
            <Spin tip="正在加载任务..." />
          </div>
        ) : tasks.length === 0 ? (
          <Empty
            image={<ClockCircleOutlined style={{ fontSize: 48, color: token.colorTextTertiary }} />}
            description={
              <div>
                <Text strong>暂无任务记录</Text>
                <br />
                <Text type="secondary">
                  执行抓取、AI 改写或发布后，任务会出现在这里。
                </Text>
              </div>
            }
          />
        ) : (
          <Table<TaskRecord>
            columns={columns}
            dataSource={tasks}
            rowKey="id"
            size="small"
            pagination={{ pageSize: 20, size: "small" }}
          />
        )}
      </Card>

      <NextStepBar
        description="失败任务重试后会回到原流程；自动生成去批量页，发布去发布中心。"
        actions={[
          { label: "去自动任务", to: "/platforms/xhs/write/batch?mode=auto" },
          { label: "去发布队列", to: "/platforms/xhs/publish-hub/jobs", primary: true },
        ]}
      />
    </div>
  );
}
