import {
  CalendarOutlined,
  ClockCircleOutlined,
  LeftOutlined,
  PlusOutlined,
  ReloadOutlined,
  RightOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Input,
  InputNumber,
  List,
  Modal,
  Popconfirm,
  Row,
  Segmented,
  Select,
  Space,
  Spin,
  Tag,
  theme,
  Typography,
  message,
} from "antd";
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  TouchSensor,
  pointerWithin,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import type { DragEndEvent, DragStartEvent } from "@dnd-kit/core";
import { CSS } from "@dnd-kit/utilities";
import { useEffect, useMemo, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { Link } from "react-router-dom";

import { PageHeader } from "../../../components/layout/app-shell";
import { NextStepBar } from "../../../components/layout/next-step-bar";
import {
  batchSendDraftsToPublish,
  cancelPublishJob,
  fetchAccounts,
  fetchAllDrafts,
  fetchAllPublishJobs,
  fetchSavedTopics,
  fetchSchedulerStatus,
  retryPublishJob,
  sendDraftToPublish,
  updatePublishJob,
} from "../../../lib/api";
import { formatShanghaiTime } from "../../../lib/time";
import type { BatchScheduleResult, SavedTopic } from "../../../lib/api";
import type {
  Draft,
  PlatformAccount,
  PublishJob,
  SchedulerStatus,
} from "../../../types";

const { Text, Paragraph } = Typography;

const STATUS_META: Record<string, { color: string; label: string }> = {
  pending: { color: "blue", label: "待发布" },
  uploading: { color: "orange", label: "上传中" },
  publishing: { color: "processing", label: "发布中" },
  scheduled: { color: "gold", label: "已排期" },
  published: { color: "green", label: "已发布" },
  failed: { color: "red", label: "失败" },
  cancelled: { color: "default", label: "已取消" },
};
const WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

function dateKey(value: string | Date): string {
  const d = value instanceof Date ? value : new Date(value);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function toLocalInput(value: Date): string {
  return `${dateKey(value)}T${pad(value.getHours())}:${pad(value.getMinutes())}`;
}

function eventDate(job: PublishJob): string {
  return job.published_at || job.scheduled_at || job.created_at;
}

function statusMeta(status: string) {
  return STATUS_META[status] || { color: "default", label: status };
}

function displayStatus(job: PublishJob): string {
  return job.status === "pending" && job.publish_mode === "scheduled" ? "scheduled" : job.status;
}

function timeText(value?: string | null): string {
  if (!value) return "";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "" : `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function EventCard({
  job,
  compact = false,
  overlay = false,
}: {
  job: PublishJob;
  compact?: boolean;
  overlay?: boolean;
}) {
  const { token } = theme.useToken();
  const meta = statusMeta(displayStatus(job));
  const status = displayStatus(job);
  const statusBorder =
    status === "published"
      ? token.colorSuccess
      : status === "failed"
        ? token.colorError
        : status === "scheduled" || status === "pending"
          ? token.colorWarning
          : token.colorPrimary;
  return (
    <div
      style={{
        padding: compact ? "3px 6px" : "5px 7px",
        borderRadius: 8,
        background: overlay ? token.colorBgElevated : token.colorFillSecondary,
        borderLeft: `3px solid ${statusBorder}`,
        boxShadow: overlay ? "0 6px 18px rgba(0,0,0,.35)" : undefined,
        width: "100%",
        overflow: "hidden",
      }}
      title={`${job.title}\n${meta.label}`}
    >
      <Text style={{ fontSize: compact ? 11 : 12, display: "block" }} ellipsis>
        {timeText(eventDate(job))} {job.title || "未命名"}
      </Text>
      <Tag color={meta.color} style={{ fontSize: 10, lineHeight: "16px", marginInlineEnd: 0 }}>
        {meta.label}
      </Tag>
    </div>
  );
}

function DraggableEvent({
  job,
  compact,
  style,
  onOpen,
}: {
  job: PublishJob;
  compact?: boolean;
  style?: CSSProperties;
  onOpen: (job: PublishJob) => void;
}) {
  const canDrag = ["pending", "scheduled"].includes(job.status);
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: `job-${job.id}`,
    data: { job },
    disabled: !canDrag,
  });
  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      onClick={(event) => {
        event.stopPropagation();
        if (!isDragging) onOpen(job);
      }}
      style={{
        ...style,
        opacity: isDragging ? 0.35 : 1,
        transform: CSS.Translate.toString(transform),
        cursor: canDrag ? "grab" : "pointer",
        touchAction: canDrag ? "none" : undefined,
      }}
    >
      <EventCard job={job} compact={compact} />
    </div>
  );
}

function DroppableDay({
  dayKey,
  style,
  onClick,
  children,
}: {
  dayKey: string;
  style: CSSProperties;
  onClick?: () => void;
  children: ReactNode;
}) {
  const { token } = theme.useToken();
  const { setNodeRef, isOver } = useDroppable({ id: `day:${dayKey}` });
  return (
    <div
      ref={setNodeRef}
      onClick={onClick}
      style={{
        ...style,
        outline: isOver ? `2px solid ${token.colorPrimary}` : undefined,
        outlineOffset: -2,
      }}
    >
      {children}
    </div>
  );
}

const HOUR_HEIGHT = 52;

function WeekSlot({ dayKey, hour, onClick }: { dayKey: string; hour: number; onClick?: () => void }) {
  const { token } = theme.useToken();
  const { setNodeRef, isOver } = useDroppable({ id: `slot:${dayKey}:${hour}` });
  return (
    <div
      ref={setNodeRef}
      onClick={onClick}
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        top: hour * HOUR_HEIGHT,
        height: HOUR_HEIGHT,
        borderTop: `1px solid ${token.colorBorderSecondary}`,
        background: isOver ? token.colorPrimaryBg : undefined,
        zIndex: 1,
        cursor: onClick ? "pointer" : undefined,
      }}
    />
  );
}

export function ContentCalendarPage() {
  const { token } = theme.useToken();
  const [searchParams] = useSearchParams();
  const [queryHandled, setQueryHandled] = useState(false);
  const [cursor, setCursor] = useState(() => {
    const now = new Date();
    return new Date(now.getFullYear(), now.getMonth(), 1);
  });
  const [jobs, setJobs] = useState<PublishJob[]>([]);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  // Topic plans live on the same timeline as publish jobs so the user can see
  // "选题 → 草稿 → 发布" in one place instead of two disconnected calendars.
  const [topics, setTopics] = useState<SavedTopic[]>([]);
  const [accounts, setAccounts] = useState<PlatformAccount[]>([]);
  const [scheduler, setScheduler] = useState<SchedulerStatus | null>(null);
  const [accountFilter, setAccountFilter] = useState<number | null>(null);
  const [viewMode, setViewMode] = useState<"month" | "week">("month");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [batchOpen, setBatchOpen] = useState(false);
  const [batchDraftIds, setBatchDraftIds] = useState<number[]>([]);
  const [batchStartAt, setBatchStartAt] = useState("");
  const [batchIntervalDays, setBatchIntervalDays] = useState(1);
  const [batchAccountId, setBatchAccountId] = useState<number | null>(null);
  const [batchSaving, setBatchSaving] = useState(false);
  const [batchResult, setBatchResult] = useState<BatchScheduleResult | null>(null);
  const [activeJob, setActiveJob] = useState<PublishJob | null>(null);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 180, tolerance: 8 } }),
  );

  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [scheduleDraftId, setScheduleDraftId] = useState<number | null>(null);
  const [scheduleAt, setScheduleAt] = useState("");
  const [scheduleAccountId, setScheduleAccountId] = useState<number | null>(null);
  const [savingSchedule, setSavingSchedule] = useState(false);

  const [selectedJob, setSelectedJob] = useState<PublishJob | null>(null);
  const [jobAt, setJobAt] = useState("");
  const [jobAccountId, setJobAccountId] = useState<number | null>(null);
  const [savingJob, setSavingJob] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [jobsResult, draftsResult, accountsResult, schedulerResult, topicsResult] = await Promise.all([
        fetchAllPublishJobs("xhs"),
        fetchAllDrafts("xhs"),
        fetchAccounts("xhs"),
        fetchSchedulerStatus().catch(() => null),
        fetchSavedTopics().catch(() => ({ items: [], total: 0 })),
      ]);
      setJobs(jobsResult);
      setDrafts(draftsResult);
      setTopics((topicsResult.items || []).filter((topic) => topic.scheduled_for));
      const publishable = accountsResult.filter(
        (account) => account.sub_type === "creator" || account.sub_type === "pc",
      );
      setAccounts(publishable);
      setScheduler(schedulerResult);
      setScheduleAccountId((current) => current ?? publishable[0]?.id ?? null);
      setAccountFilter((current) => current ?? null);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || "排期日历加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const visibleJobs = useMemo(
    () =>
      jobs.filter(
        (job) =>
          (accountFilter === null || job.platform_account_id === accountFilter) &&
          job.status !== "cancelled",
      ),
    [jobs, accountFilter],
  );

  const jobsByDay = useMemo(() => {
    const map = new Map<string, PublishJob[]>();
    for (const job of visibleJobs) {
      const raw = eventDate(job);
      if (!raw) continue;
      const key = dateKey(raw);
      const list = map.get(key) || [];
      list.push(job);
      map.set(key, list);
    }
    for (const list of map.values()) {
      list.sort((a, b) => new Date(eventDate(a)).getTime() - new Date(eventDate(b)).getTime());
    }
    return map;
  }, [visibleJobs]);

  const scheduledDraftIds = useMemo(() => {
    const ids = new Set<number>();
    for (const job of jobs) {
      if (
        job.source_draft_id &&
        ["pending", "scheduled", "uploading", "publishing", "published"].includes(job.status)
      ) {
        ids.add(job.source_draft_id);
      }
    }
    return ids;
  }, [jobs]);

  const unscheduledDrafts = useMemo(
    () => drafts.filter((draft) => !scheduledDraftIds.has(draft.id)),
    [drafts, scheduledDraftIds],
  );

  useEffect(() => {
    if (queryHandled || !unscheduledDrafts.length) return;
    const raw = searchParams.get("draft_ids") || searchParams.get("draft_id") || "";
    const ids = raw
      .split(",")
      .map((value) => Number(value.trim()))
      .filter((value) => Number.isFinite(value) && value > 0);
    if (!ids.length) {
      setQueryHandled(true);
      return;
    }
    const available = unscheduledDrafts.filter((draft) => ids.includes(draft.id));
    if (!available.length) {
      setQueryHandled(true);
      return;
    }
    if (!searchParams.get("draft_ids") && available.length === 1) {
      openSchedule(available[0]);
    } else {
      const tomorrow = new Date();
      tomorrow.setDate(tomorrow.getDate() + 1);
      tomorrow.setHours(10, 0, 0, 0);
      setBatchDraftIds(available.map((draft) => draft.id));
      setBatchStartAt(toLocalInput(tomorrow));
      setBatchIntervalDays(1);
      setBatchAccountId((current) => current ?? accounts[0]?.id ?? null);
      setBatchOpen(true);
    }
    setQueryHandled(true);
  }, [unscheduledDrafts, queryHandled, searchParams, accounts]);

  const days = useMemo(() => {
    if (viewMode === "week") {
      const start = new Date(cursor);
      const offset = (start.getDay() + 6) % 7;
      start.setDate(start.getDate() - offset);
      return Array.from({ length: 7 }, (_, index) => {
        const day = new Date(start);
        day.setDate(start.getDate() + index);
        return day;
      });
    }
    const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
    const offset = (first.getDay() + 6) % 7;
    const start = new Date(first);
    start.setDate(first.getDate() - offset);
    return Array.from({ length: 42 }, (_, index) => {
      const day = new Date(start);
      day.setDate(start.getDate() + index);
      return day;
    });
  }, [cursor, viewMode]);

  const todayKey = dateKey(new Date());
  const periodLabel =
    viewMode === "month"
      ? `${cursor.getFullYear()} 年 ${cursor.getMonth() + 1} 月`
      : (() => {
          const first = days[0];
          const last = days[days.length - 1];
          return `${first.getMonth() + 1} 月 ${first.getDate()} 日 – ${last.getMonth() + 1} 月 ${last.getDate()} 日`;
        })();
  const periodJobs = visibleJobs.filter((job) => {
    const raw = eventDate(job);
    if (!raw) return false;
    const d = new Date(raw);
    if (viewMode === "month") {
      return d.getFullYear() === cursor.getFullYear() && d.getMonth() === cursor.getMonth();
    }
    const first = days[0];
    const last = days[days.length - 1];
    last.setHours(23, 59, 59, 999);
    return d >= first && d <= last;
  });
  const periodScheduled = periodJobs.filter((job) => job.status === "scheduled" || job.status === "pending").length;
  const periodPublished = periodJobs.filter((job) => job.status === "published").length;
  const periodFailed = periodJobs.filter((job) => job.status === "failed").length;
  const periodName = viewMode === "month" ? "本月" : "本周";

  function shiftPeriod(delta: number) {
    setCursor((current) =>
      viewMode === "month"
        ? new Date(current.getFullYear(), current.getMonth() + delta, 1)
        : new Date(current.getFullYear(), current.getMonth(), current.getDate() + delta * 7),
    );
  }

  function openSchedule(draft?: Draft, day?: Date) {
    const base = day ? new Date(day) : new Date();
    if (day) base.setHours(10, 0, 0, 0);
    setScheduleDraftId(draft?.id ?? null);
    setScheduleAt(toLocalInput(base));
    setScheduleAccountId((current) => current ?? accounts[0]?.id ?? null);
    setScheduleOpen(true);
  }

  async function submitSchedule() {
    if (!scheduleDraftId) {
      message.warning("请选择一篇草稿");
      return;
    }
    if (!scheduleAt) {
      message.warning("请选择发布时间");
      return;
    }
    const when = new Date(scheduleAt);
    if (Number.isNaN(when.getTime()) || when <= new Date()) {
      message.warning("发布时间必须晚于当前时间");
      return;
    }
    if (!scheduleAccountId) {
      message.warning("请选择发布账号");
      return;
    }
    setSavingSchedule(true);
    try {
      await sendDraftToPublish(scheduleDraftId, {
        platform_account_id: scheduleAccountId,
        publish_mode: "scheduled",
        scheduled_at: when.toISOString(),
      });
      if (scheduler?.running) {
        message.success("已加入发布排期，到点会自动发布");
      } else {
        message.warning("已加入发布排期，但调度器未运行：到点不会自动发布，需要手动点发布");
      }
      setScheduleOpen(false);
      await load();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || "排期失败");
    } finally {
      setSavingSchedule(false);
    }
  }

  function openJob(job: PublishJob) {
    setSelectedJob(job);
    setJobAt(toLocalInput(new Date(job.scheduled_at || eventDate(job))));
    setJobAccountId(job.platform_account_id || accounts[0]?.id || null);
  }

  async function saveJobSchedule() {
    if (!selectedJob) return;
    const when = new Date(jobAt);
    if (Number.isNaN(when.getTime())) {
      message.warning("时间格式不正确");
      return;
    }
    setSavingJob(true);
    try {
      const updated = await updatePublishJob(selectedJob.id, {
        platform_account_id: jobAccountId,
        publish_mode: "scheduled",
        scheduled_at: when.toISOString(),
      });
      setSelectedJob(updated);
      message.success("排期已更新");
      await load();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || "更新排期失败");
    } finally {
      setSavingJob(false);
    }
  }

  async function cancelJob() {
    if (!selectedJob) return;
    setSavingJob(true);
    try {
      await cancelPublishJob(selectedJob.id);
      message.success("已取消排期");
      setSelectedJob(null);
      await load();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || "取消失败");
    } finally {
      setSavingJob(false);
    }
  }

  async function retryJob() {
    if (!selectedJob) return;
    setSavingJob(true);
    try {
      const updated = await retryPublishJob(selectedJob.id);
      setSelectedJob(updated);
      message.success("已重置为待发布");
      await load();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || "重试失败");
    } finally {
      setSavingJob(false);
    }
  }

  async function handleDrop(jobId: number, day: Date, exactTime = false) {
    const job = jobs.find((item) => item.id === jobId);
    if (!job) return;
    if (!["pending", "scheduled"].includes(job.status)) {
      message.warning("已发布或发布中的任务不能拖拽改期");
      return;
    }
    const original = new Date(eventDate(job));
    const next = new Date(day);
    if (!exactTime) {
      next.setHours(original.getHours(), original.getMinutes(), 0, 0);
    } else {
      next.setSeconds(0, 0);
    }
    if (next <= new Date()) {
      message.warning("不能拖到过去的时间");
      return;
    }
    try {
      await updatePublishJob(job.id, {
        publish_mode: "scheduled",
        scheduled_at: next.toISOString(),
      });
      message.success(`已改期到 ${formatShanghaiTime(next.toISOString())}`);
      await load();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || "改期失败");
    }
  }

  function handleDragStart(event: DragStartEvent) {
    const job = event.active.data.current?.job as PublishJob | undefined;
    setActiveJob(job ?? null);
  }

  function handleDragEnd(event: DragEndEvent) {
    setActiveJob(null);
    const job = event.active.data.current?.job as PublishJob | undefined;
    const overId = event.over?.id ? String(event.over.id) : "";
    if (!job || !overId) return;
    if (overId.startsWith("slot:")) {
      const [, datePart, hourPart] = overId.split(":");
      const [year, month, day] = datePart.split("-").map(Number);
      const next = new Date(year, month - 1, day, Number(hourPart), 0, 0, 0);
      void handleDrop(job.id, next, true);
      return;
    }
    if (overId.startsWith("day:")) {
      const datePart = overId.slice(4);
      const [year, month, day] = datePart.split("-").map(Number);
      void handleDrop(job.id, new Date(year, month - 1, day));
    }
  }

  function openBatch() {
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    tomorrow.setHours(10, 0, 0, 0);
    setBatchDraftIds([]);
    setBatchStartAt(toLocalInput(tomorrow));
    setBatchIntervalDays(1);
    setBatchAccountId(accountFilter ?? accounts[0]?.id ?? null);
    setBatchOpen(true);
  }

  async function submitBatch() {
    if (!batchDraftIds.length) {
      message.warning("请选择要排期的草稿");
      return;
    }
    if (!batchStartAt || !batchAccountId) {
      message.warning("请选择开始时间和发布账号");
      return;
    }
    const when = new Date(batchStartAt);
    if (Number.isNaN(when.getTime()) || when <= new Date()) {
      message.warning("开始时间必须晚于当前时间");
      return;
    }
    setBatchSaving(true);
    try {
      const result = await batchSendDraftsToPublish({
        draft_ids: batchDraftIds,
        platform_account_id: batchAccountId,
        start_at: when.toISOString(),
        interval_days: batchIntervalDays,
      });
      setBatchResult(result);
      if ((result.created_count ?? 0) > 0) {
        message.success(`已排期 ${(result.created_count ?? 0)} 篇，失败 ${result.failed_count} 篇`);
      } else {
        message.warning(`没有排期成功，失败 ${result.failed_count} 篇，请检查失败原因`);
      }
      setBatchOpen(false);
      await load();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || "批量排期失败");
    } finally {
      setBatchSaving(false);
    }
  }

  return (
    <div>
      <PageHeader
        eyebrow="发布排期"
        title="发布排期"
        description="把草稿排到具体时间，到点由调度器自动发布。上方同时显示已排期的选题计划：选题还不是草稿，不会自动发布。"
        action={
          <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>
            刷新
          </Button>
        }
      />

      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}

      {topics.length ? (
        <Card
          size="small"
          style={{ marginBottom: 16 }}
          title={<span><CalendarOutlined style={{ marginRight: 6 }} />已排期的选题计划（{topics.length}）</span>}
        >
          <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 10 }}>
            这些是「计划」，还没有草稿，所以不会自动发布。点「转成草稿」把它变成可排期的内容。
          </Paragraph>
          <Space direction="vertical" size={8} style={{ width: "100%" }}>
            {topics
              .slice()
              .sort((a, b) => String(a.scheduled_for).localeCompare(String(b.scheduled_for)))
              .slice(0, 12)
              .map((topic) => (
                <div
                  key={topic.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    padding: "6px 8px",
                    borderRadius: 8,
                    background: "rgba(250,173,20,0.08)",
                    border: "1px solid rgba(250,173,20,0.25)",
                  }}
                >
                  <Tag color="gold">{formatShanghaiTime(topic.scheduled_for)}</Tag>
                  <Text ellipsis style={{ flex: 1, fontSize: 13 }}>
                    {topic.title || "未命名选题"}
                  </Text>
                  {topic.type_label ? <Tag>{topic.type_label}</Tag> : null}
                  <Link to={`/platforms/xhs/plan?topic=${topic.id}`}>
                    <Button size="small" type="link">去转成草稿</Button>
                  </Link>
                </div>
              ))}
          </Space>
        </Card>
      ) : null}

      {scheduler ? (
        <Alert
          type={scheduler.running ? "success" : "warning"}
          showIcon
          style={{ marginBottom: 16 }}
          message={
            scheduler.running
              ? "自动发布调度器运行中"
              : "自动发布调度器未运行，定时任务不会执行"
          }
          description={
            scheduler.running
              ? `每 ${scheduler.interval_seconds} 秒检查一次到期任务。关闭应用后调度器会停止。`
              : "请保持应用运行；关闭控制台后，已排期任务不会自动发布。"
          }
        />
      ) : null}

      <Card style={{ marginBottom: 16 }}>
        <Row justify="space-between" align="middle" gutter={[12, 12]}>
          <Col>
            <Space wrap>
              <Button icon={<LeftOutlined />} onClick={() => shiftPeriod(-1)} />
              <Text strong style={{ fontSize: 16, minWidth: 160, display: "inline-block", textAlign: "center" }}>
                {periodLabel}
              </Text>
              <Button icon={<RightOutlined />} onClick={() => shiftPeriod(1)} />
              <Button onClick={() => setCursor(new Date())}>
                今天
              </Button>
              <Segmented
                value={viewMode}
                onChange={(value) => setViewMode(value as "month" | "week")}
                options={[
                  { label: "月", value: "month" },
                  { label: "周", value: "week" },
                ]}
              />
            </Space>
          </Col>
          <Col>
            <Space wrap>
              <Select
                allowClear
                value={accountFilter ?? undefined}
                onChange={(value) => setAccountFilter(value ?? null)}
                placeholder="全部账号"
                style={{ width: 200 }}
                options={accounts.map((account) => ({
                  value: account.id,
                  label: `${account.nickname || `账号 ${account.id}`} · ${account.sub_type || ""}`,
                }))}
              />
              <Button icon={<CalendarOutlined />} onClick={openBatch}>
                批量排期
              </Button>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => openSchedule()}>
                排一篇草稿
              </Button>
            </Space>
          </Col>
        </Row>
        <Space wrap size={16} style={{ marginTop: 12 }}>
          <Text type="secondary">{periodName}：</Text>
          <Tag color="gold">已排期 {periodScheduled}</Tag>
          <Tag color="green">已发布 {periodPublished}</Tag>
          <Tag color="red">失败 {periodFailed}</Tag>
          <Tag>待排期草稿 {unscheduledDrafts.length}</Tag>
        </Space>
      </Card>

      <Row gutter={16}>
        <Col xs={24} lg={18}>
          <Card bodyStyle={{ padding: 8 }}>
            <DndContext
              sensors={sensors}
              collisionDetection={pointerWithin}
              onDragStart={handleDragStart}
              onDragEnd={handleDragEnd}
            >
              {viewMode === "month" ? (
                <div style={{ display: "grid", gridTemplateColumns: "repeat(7, minmax(0, 1fr))", gap: 4 }}>
                  {WEEKDAYS.map((day) => (
                    <div key={day} style={{ padding: "6px 8px", textAlign: "center" }}>
                      <Text type="secondary" style={{ fontSize: 12 }}>{day}</Text>
                    </div>
                  ))}
                  {days.map((day) => {
                    const key = dateKey(day);
                    const dayJobs = jobsByDay.get(key) || [];
                    const jobSlots = 4;
                    const inMonth = day.getMonth() === cursor.getMonth();
                    const isToday = key === todayKey;
                    return (
                      <DroppableDay
                        key={key}
                        dayKey={key}
                        onClick={() => {
                          if (dayJobs.length === 0) openSchedule(undefined, day);
                        }}
                        style={{
                          minHeight: 128,
                          padding: 6,
                          borderRadius: 8,
                          border: isToday ? `1px solid ${token.colorPrimary}` : `1px solid ${token.colorBorderSecondary}`,
                          background: isToday
                            ? token.colorPrimaryBg
                            : inMonth
                              ? token.colorFillQuaternary
                              : "transparent",
                          opacity: inMonth ? 1 : 0.45,
                          cursor: dayJobs.length === 0 ? "pointer" : "default",
                        }}
                      >
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                          <Text strong={isToday} style={{ fontSize: 12, color: isToday ? token.colorPrimary : undefined }}>
                            {day.getDate()}
                          </Text>
                          {inMonth ? (
                            <Button
                              type="text"
                              size="small"
                              icon={<PlusOutlined />}
                              onClick={(event) => {
                                event.stopPropagation();
                                openSchedule(undefined, day);
                              }}
                            />
                          ) : null}
                        </div>
                        <Space direction="vertical" size={4} style={{ width: "100%" }}>
                          {dayJobs.slice(0, jobSlots).map((job) => (
                            <DraggableEvent key={job.id} job={job} compact onOpen={openJob} />
                          ))}
                          {dayJobs.length > jobSlots ? (
                            <Text type="secondary" style={{ fontSize: 10 }}>
                              还有 {dayJobs.length - jobSlots} 条发布
                            </Text>
                          ) : null}
                        </Space>
                      </DroppableDay>
                    );
                  })}
                </div>
              ) : (
                <div>
                  <div style={{ display: "flex", borderBottom: `1px solid ${token.colorBorderSecondary}`, paddingBottom: 6 }}>
                    <div style={{ width: 56, flexShrink: 0 }} />
                    {days.map((day) => (
                      <div key={dateKey(day)} style={{ flex: 1, minWidth: 0, textAlign: "center", padding: "4px 2px" }}>
                        <Text strong={dateKey(day) === todayKey} style={{ fontSize: 12 }}>
                          {WEEKDAYS[(day.getDay() + 6) % 7]} {day.getMonth() + 1}/{day.getDate()}
                        </Text>
                        <div>
                          <Button
                            type="text"
                            size="small"
                            icon={<PlusOutlined />}
                            onClick={() => openSchedule(undefined, day)}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                  <div style={{ display: "flex", maxHeight: 680, overflowY: "auto" }}>
                    <div style={{ width: 56, flexShrink: 0, height: 24 * HOUR_HEIGHT, position: "relative" }}>
                      {Array.from({ length: 24 }, (_, hour) => (
                        <div
                          key={hour}
                          style={{
                            height: HOUR_HEIGHT,
                            textAlign: "right",
                            paddingRight: 6,
                            fontSize: 10,
                            color: token.colorTextTertiary,
                            transform: "translateY(-6px)",
                          }}
                        >
                          {String(hour).padStart(2, "0")}:00
                        </div>
                      ))}
                    </div>
                    <div style={{ flex: 1, display: "grid", gridTemplateColumns: "repeat(7, minmax(0, 1fr))" }}>
                      {days.map((day) => {
                        const key = dateKey(day);
                        const dayJobs = jobsByDay.get(key) || [];
                        return (
                          <div
                            key={key}
                            style={{
                              position: "relative",
                              height: 24 * HOUR_HEIGHT,
                              borderLeft: `1px solid ${token.colorBorderSecondary}`,
                              background: key === todayKey ? token.colorPrimaryBg : undefined,
                            }}
                          >
                            {Array.from({ length: 24 }, (_, hour) => (
                              <WeekSlot
                                key={hour}
                                dayKey={key}
                                hour={hour}
                                onClick={() => {
                                  const target = new Date(day);
                                  target.setHours(hour, 0, 0, 0);
                                  openSchedule(undefined, target);
                                }}
                              />
                            ))}
                            {dayJobs.map((job, index) => {
                              const when = new Date(eventDate(job));
                              const top = when.getHours() * HOUR_HEIGHT + (when.getMinutes() / 60) * HOUR_HEIGHT;
                              return (
                                <DraggableEvent
                                  key={job.id}
                                  job={job}
                                  onOpen={openJob}
                                  style={{
                                    position: "absolute",
                                    top,
                                    left: 4 + (index % 3) * 6,
                                    right: 4,
                                    zIndex: 2 + index,
                                  }}
                                />
                              );
                            })}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>
              )}
              <DragOverlay>
                {activeJob ? <EventCard job={activeJob} overlay /> : null}
              </DragOverlay>
            </DndContext>
          </Card>
        </Col>

        <Col xs={24} lg={6}>
          <Card
            title={<span><CalendarOutlined style={{ marginRight: 6 }} />待排期草稿</span>}
            extra={<Tag>{unscheduledDrafts.length}</Tag>}
            style={{ marginBottom: 16 }}
          >
            {loading ? (
              <Spin />
            ) : unscheduledDrafts.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="所有草稿都已排期" />
            ) : (
              <List
                dataSource={unscheduledDrafts.slice(0, 20)}
                renderItem={(draft) => (
                  <List.Item
                    actions={[
                      <Button key="schedule" type="link" size="small" onClick={() => openSchedule(draft)}>
                        排期
                      </Button>,
                    ]}
                  >
                    <List.Item.Meta
                      title={<Text ellipsis style={{ fontSize: 13 }}>{draft.title || "未命名草稿"}</Text>}
                      description={
                        <Text type="secondary" style={{ fontSize: 11 }}>
                          {formatShanghaiTime(draft.created_at)}
                        </Text>
                      }
                    />
                  </List.Item>
                )}
              />
            )}
          </Card>

          <Card title="排期说明">
            <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 8 }}>
              这里统一排发布任务；选题本身在「选题 → 选题库」维护，排期后的选题会显示在上方。
            </Paragraph>
            <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 8 }}>
              排期只创建发布任务，不会立即发布。到时间后由调度器自动执行。
            </Paragraph>
            <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 8 }}>
              关闭应用后调度器停止，未执行的定时任务会保留到下次启动。
            </Paragraph>
            <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 0 }}>
              发布前请确认草稿已有图片或视频素材，并已绑定可用的 Creator 账号。
            </Paragraph>
          </Card>
        </Col>
      </Row>

      <Modal
        open={scheduleOpen}
        title="排期发布"
        onCancel={() => setScheduleOpen(false)}
        width={620}
        footer={
          <Space>
            <Button onClick={() => setScheduleOpen(false)}>取消</Button>
            <Button type="primary" loading={savingSchedule} onClick={() => void submitSchedule()}>
              加入排期
            </Button>
          </Space>
        }
      >
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <div>
            <Text type="secondary" style={{ fontSize: 12 }}>选择草稿</Text>
            <Select
              showSearch
              optionFilterProp="label"
              value={scheduleDraftId ?? undefined}
              onChange={(value) => setScheduleDraftId(value)}
              placeholder="选择一篇草稿"
              style={{ width: "100%" }}
              options={unscheduledDrafts.map((draft) => ({
                value: draft.id,
                label: draft.title || `草稿 ${draft.id}`,
              }))}
            />
          </div>
          <Row gutter={8}>
            <Col span={14}>
              <Text type="secondary" style={{ fontSize: 12 }}>发布时间</Text>
              <Input
                type="datetime-local"
                value={scheduleAt}
                onChange={(event) => setScheduleAt(event.target.value)}
              />
            </Col>
            <Col span={10}>
              <Text type="secondary" style={{ fontSize: 12 }}>发布账号</Text>
              <Select
                value={scheduleAccountId ?? undefined}
                onChange={(value) => setScheduleAccountId(value)}
                placeholder="选择账号"
                style={{ width: "100%" }}
                options={accounts.map((account) => ({
                  value: account.id,
                  label: account.nickname || `账号 ${account.id}`,
                }))}
              />
            </Col>
          </Row>
          <Alert
            type="info"
            showIcon
            icon={<ClockCircleOutlined />}
            message="到点后自动发布"
            description="应用需保持运行；发布前请确认草稿已有图片或视频素材。"
          />
        </Space>
      </Modal>

      <Modal
        open={selectedJob !== null}
        title={selectedJob ? `排期 · ${selectedJob.title || "未命名"}` : ""}
        onCancel={() => setSelectedJob(null)}
        width={620}
        footer={
          <Space wrap>
            {selectedJob?.status === "failed" ? (
              <Button onClick={() => void retryJob()} loading={savingJob}>重置重试</Button>
            ) : null}
            {selectedJob && ["pending", "scheduled"].includes(selectedJob.status) ? (
              <Popconfirm
                title="取消这个排期？"
                description="取消后任务不会自动发布，草稿仍保留。"
                okText="取消排期"
                cancelText="保留"
                okButtonProps={{ danger: true }}
                onConfirm={() => void cancelJob()}
              >
                <Button danger loading={savingJob}>取消排期</Button>
              </Popconfirm>
            ) : null}
            <Button onClick={() => setSelectedJob(null)}>关闭</Button>
            <Button
              type="primary"
              loading={savingJob}
              disabled={selectedJob?.status === "published"}
              onClick={() => void saveJobSchedule()}
            >
              保存时间
            </Button>
          </Space>
        }
      >
        {selectedJob ? (
          <Space direction="vertical" size={12} style={{ width: "100%" }}>
            <Space wrap>
              <Tag color={statusMeta(displayStatus(selectedJob)).color}>{statusMeta(displayStatus(selectedJob)).label}</Tag>
              {selectedJob.published_at ? <Tag color="green">发布于 {formatShanghaiTime(selectedJob.published_at)}</Tag> : null}
            </Space>
            {selectedJob.publish_error ? (
              <Alert type="error" showIcon message="发布失败" description={selectedJob.publish_error} />
            ) : null}
            <Row gutter={8}>
              <Col span={14}>
                <Text type="secondary" style={{ fontSize: 12 }}>发布时间</Text>
                <Input
                  type="datetime-local"
                  value={jobAt}
                  onChange={(event) => setJobAt(event.target.value)}
                />
              </Col>
              <Col span={10}>
                <Text type="secondary" style={{ fontSize: 12 }}>发布账号</Text>
                <Select
                  value={jobAccountId ?? undefined}
                  onChange={(value) => setJobAccountId(value)}
                  style={{ width: "100%" }}
                  options={accounts.map((account) => ({
                    value: account.id,
                    label: account.nickname || `账号 ${account.id}`,
                  }))}
                />
              </Col>
            </Row>
            <div>
              <Text type="secondary" style={{ fontSize: 12 }}>正文预览</Text>
              <Paragraph ellipsis={{ rows: 4, expandable: true, symbol: "展开" }} style={{ fontSize: 12, marginTop: 4 }}>
                {selectedJob.body || "（无正文）"}
              </Paragraph>
            </div>
            {selectedJob.status === "published" ? (
              <Text type="secondary" style={{ fontSize: 12 }}>
                已发布任务不能再改时间；如需调整，请新建一条排期。
              </Text>
            ) : null}
          </Space>
        ) : null}
      </Modal>

      <Modal
        open={batchOpen}
        title="批量排期"
        onCancel={() => setBatchOpen(false)}
        width={640}
        footer={
          <Space>
            <Button onClick={() => setBatchOpen(false)}>取消</Button>
            <Button type="primary" loading={batchSaving} onClick={() => void submitBatch()}>
              批量加入排期
            </Button>
          </Space>
        }
      >
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <div>
            <Text type="secondary" style={{ fontSize: 12 }}>选择草稿（最多 30 篇）</Text>
            <Select
              mode="multiple"
              showSearch
              optionFilterProp="label"
              value={batchDraftIds}
              onChange={(values) => setBatchDraftIds(values.slice(0, 30))}
              placeholder="选择要排期的草稿"
              style={{ width: "100%" }}
              options={unscheduledDrafts.map((draft) => ({
                value: draft.id,
                label: draft.title || `草稿 ${draft.id}`,
              }))}
            />
          </div>
          <Row gutter={8}>
            <Col span={12}>
              <Text type="secondary" style={{ fontSize: 12 }}>第一篇发布时间</Text>
              <Input
                type="datetime-local"
                value={batchStartAt}
                onChange={(event) => setBatchStartAt(event.target.value)}
              />
            </Col>
            <Col span={6}>
              <Text type="secondary" style={{ fontSize: 12 }}>间隔天数</Text>
              <InputNumber
                min={0}
                max={30}
                value={batchIntervalDays}
                onChange={(value) => setBatchIntervalDays(Number(value ?? 1))}
                style={{ width: "100%" }}
              />
            </Col>
            <Col span={6}>
              <Text type="secondary" style={{ fontSize: 12 }}>发布账号</Text>
              <Select
                value={batchAccountId ?? undefined}
                onChange={(value) => setBatchAccountId(value)}
                style={{ width: "100%" }}
                options={accounts.map((account) => ({
                  value: account.id,
                  label: account.nickname || `账号 ${account.id}`,
                }))}
              />
            </Col>
          </Row>
          <Alert
            type="info"
            showIcon
            message={`将创建 ${batchDraftIds.length} 条排期`}
            description={
              batchDraftIds.length
                ? `第一篇 ${batchStartAt.replace("T", " ")}，之后每 ${batchIntervalDays} 天一篇。`
                : "选择草稿后显示排期预览。"
            }
          />
        </Space>
      </Modal>

      <Modal
        open={batchResult !== null}
        title="批量排期结果"
        onCancel={() => setBatchResult(null)}
        footer={<Button onClick={() => setBatchResult(null)}>关闭</Button>}
        width={640}
      >
        {batchResult ? (
          <Space direction="vertical" size={8} style={{ width: "100%" }}>
            <Space wrap>
              <Tag color="green">成功 {batchResult.created_count}</Tag>
              <Tag color="red">失败 {batchResult.failed_count}</Tag>
            </Space>
            <List
              size="small"
              dataSource={batchResult.items}
              renderItem={(item) => (
                <List.Item style={{ padding: "6px 0", border: "none" }}>
                  <Space direction="vertical" size={2} style={{ width: "100%" }}>
                    <Space wrap>
                      <Text strong style={{ fontSize: 12 }}>草稿 #{item.draft_id}</Text>
                      {item.status === "ok" ? <Tag color="green">已排期</Tag> : <Tag color="red">失败</Tag>}
                      {item.scheduled_at ? <Text type="secondary" style={{ fontSize: 11 }}>{formatShanghaiTime(item.scheduled_at)}</Text> : null}
                    </Space>
                    {item.error ? <Text type="danger" style={{ fontSize: 12 }}>{item.error}</Text> : null}
                    {item.warnings?.length ? (
                      <Text type="warning" style={{ fontSize: 12 }}>
                        提醒：{item.warnings.map((warning: { message?: string } | string) => typeof warning === "string" ? warning : (warning.message ?? "")).join("；")}
                      </Text>
                    ) : null}
                  </Space>
                </List.Item>
              )}
            />
          </Space>
        ) : null}
      </Modal>

      <NextStepBar
        description="排期完成后去发布队列确认预检；没有素材时回草稿工坊配图。"
        actions={[
          { label: "去发布队列", to: "/platforms/xhs/publish-hub/jobs", primary: true },
          { label: "回草稿工坊", to: "/platforms/xhs/write/drafts" },
        ]}
      />
    </div>
  );
}
