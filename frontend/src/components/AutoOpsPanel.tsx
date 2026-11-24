/**
 * AutoOpsPanel.tsx — 自动运营（设置 → 自动运营）
 *
 * 后端 `/api/auto-tasks` 一套完整：建/改/删/手动跑/异步跑/调度器定时跑。
 * 合并前端时这一页没搬，于是「风险开关」里 `auto_ops_enabled` 那张卡
 * 只能写「尚无入口」——打开开关不会有任何可观察的变化。
 *
 * 这一页只做一件事：**把那条链路接到界面上**，并且不撒谎。
 *
 * 三个必须说清的地方（每一处都对应后端的一条硬约束）：
 *
 * 1. 建任务要两个账号：`pc_account_id` + `creator_account_id`
 *    （`auto_tasks.py:178-179`）。只有 pc 号时后端 404，
 *    所以这里先检查，缺 creator 号就把「去绑定创作中心」摆在按钮位置。
 * 2. 跑之前还要四道风险开关（`_prepare_auto_task_run`）。开关没开是 403，
 *    不是失败——提示里直接说「去风险开关里打开哪几个」，不让人猜。
 * 3. 产出是**草稿**。建不建发布任务、发不发自走，由另外两个开关决定，
 *    列表里如实写出这一次跑完到底落在哪儿。
 */

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Button from "./Button";
import EmptyState from "./EmptyState";
import ConfirmDialog from "./ConfirmDialog";
import { Input, Select, Textarea } from "./Field";
import Modal from "./Modal";
import { SkeletonList } from "./Skeleton";
import { useToast } from "./Toast";
import { ApiError, get, unwrapList } from "../lib/api";
import { invalidate, useQuery } from "../lib/query";
import { useKeptState } from "../lib/formState";
import { loadStructureTemplates } from "../lib/skills";
import {
  createAutoTask,
  deleteAutoTask,
  describeSchedule,
  listAutoTasks,
  runAutoTask,
  updateAutoTask,
  type AutoTask,
  type AutoTaskRunResult,
} from "../lib/autoTasks";
import "./AutoOps.css";

interface AccountRow {
  id: number;
  platform?: string;
  sub_type?: string;
  nickname?: string;
  status?: string;
}

const SCHEDULE_OPTIONS = [
  { value: "manual", label: "只手动跑" },
  { value: "daily", label: "每天" },
  { value: "weekly", label: "每周" },
  { value: "interval", label: "每隔几小时" },
];

const WEEKDAYS = [
  { value: "1", label: "周一" },
  { value: "2", label: "周二" },
  { value: "3", label: "周三" },
  { value: "4", label: "周四" },
  { value: "5", label: "周五" },
  { value: "6", label: "周六" },
  { value: "7", label: "周日" },
];

export default function AutoOpsPanel() {
  const toast = useToast();

  const accountsQ = useQuery(
    () => get("/api/accounts?page_size=100").then((r) => unwrapList<AccountRow>(r)),
    [],
    { key: "autoops|accounts", staleTime: 60_000 },
  );
  const tasksQ = useQuery(() => listAutoTasks(), [], {
    key: "autoops|tasks",
    staleTime: 5_000,
  });
  const templatesQ = useQuery(() => loadStructureTemplates(), [], {
    key: "autoops|templates",
    staleTime: 60_000,
  });

  const accounts = accountsQ.data?.items ?? [];
  const tasks = tasksQ.data ?? [];
  const templates = templatesQ.data?.items ?? [];

  const pcAccounts = accounts.filter(
    (a) => (a.platform ?? "xhs") === "xhs" && (a.sub_type ?? "pc") === "pc",
  );
  const creatorAccounts = accounts.filter((a) => a.sub_type === "creator");

  const [editing, setEditing] = useState<AutoTask | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<AutoTask | null>(null);
  const [lastRun, setLastRun] = useState<{ task: AutoTask; result: AutoTaskRunResult } | null>(
    null,
  );

  const canCreate = pcAccounts.length > 0 && creatorAccounts.length > 0;

  async function run(task: AutoTask) {
    setBusy(task.id);
    try {
      const result = await runAutoTask(task.id);
      setLastRun({ task, result });
      toast.success(
        result.publish_job ? "跑完了，已建发布任务" : "跑完了，草稿已存进写稿",
      );
      invalidate("autoops|tasks");
    } catch (err) {
      /*
       * 403 是「开关没开」，不是失败。原样抛 message 会得到一句
       * 「「自动运营」未开启。请到…」——正是用户需要的那句话，所以直接显示。
       */
      toast.error(err instanceof ApiError ? err.message : "运行失败");
    } finally {
      setBusy(null);
    }
  }

  async function toggleStatus(task: AutoTask) {
    setBusy(task.id);
    try {
      await updateAutoTask(task.id, {
        status: task.status === "active" ? "paused" : "active",
      });
      invalidate("autoops|tasks");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "改状态失败");
    } finally {
      setBusy(null);
    }
  }

  async function remove(task: AutoTask) {
    setBusy(task.id);
    try {
      await deleteAutoTask(task.id);
      toast.success("已删除");
      setConfirmDelete(null);
      invalidate("autoops|tasks");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "删除失败");
    } finally {
      setBusy(null);
    }
  }

  if (accountsQ.initialLoading || tasksQ.initialLoading) {
    return <SkeletonList rows={4} />;
  }

  return (
    <div className="ao">
      <p className="ao__lead">
        按关键词找一篇对标笔记，改写成你自己的稿子。产出是<strong>草稿</strong>，
        出现在「写稿」左栏；要不要顺带建发布任务、要不要直接发出去，
        由「设置 → 风险开关」里对应的开关决定。
      </p>

      {!canCreate ? (
        <div className="ao__blocker">
          <strong>
            {pcAccounts.length === 0
              ? "还没有绑定小红书账号"
              : "还没有绑创作中心账号"}
          </strong>
          <span>
            自动运营要两个身份：一个 PC 账号负责站内搜索，一个创作中心（creator）
            账号负责承接发布。现在
            {pcAccounts.length === 0 ? " PC 账号" : ""}
            {pcAccounts.length === 0 && creatorAccounts.length === 0 ? " 和" : ""}
            {creatorAccounts.length === 0 ? " 创作中心账号" : ""}
            还没有。
            去「设置 → 账号」绑定；扫码时可以勾「同时获取创作中心账号」，
            它会用同一个手机号换一个 creator 身份，不用另扫一次。
          </span>
          {/* 说了「去哪绑」就得给一个能点的按钮，不然还是让用户自己翻 */}
          <span className="ao__blockerAct">
            <Link className="ao__link" to="/settings/accounts">
              去绑定账号 ↗
            </Link>
          </span>
        </div>
      ) : (
        <div className="ao__acts">
          <Button
            variant="primary"
            size="sm"
            onClick={() => {
              setEditing(null);
              setFormOpen(true);
            }}
          >
            新建任务
          </Button>
          <span className="ao__actsHint">
            {pcAccounts.length} 个 PC 账号 · {creatorAccounts.length} 个创作中心账号
          </span>
        </div>
      )}

      {lastRun ? <LastRunCard data={lastRun} onClose={() => setLastRun(null)} /> : null}

      {tasks.length === 0 ? (
        <EmptyState
          compact
          glyph="flow"
          title="还没有自动运营任务"
          description={
            canCreate
              ? "建一条：给几个关键词，选好两个账号，之后要么你自己点运行，要么让它按日/周/间隔自己跑。"
              : "先绑好两个账号，再回来建任务。"
          }
        />
      ) : (
        <ul className="ao__list">
          {tasks.map((task) => (
            <li className="ao__row" key={task.id}>
              <div className="ao__main">
                <span className="ao__name">
                  {task.name}
                  <span className={`ao__pill is-${task.status}`}>
                    {task.status === "active"
                      ? "运行中"
                      : task.status === "paused"
                        ? "已暂停"
                        : task.status === "completed"
                          ? "已完成"
                          : task.status}
                  </span>
                </span>
                <span className="ao__meta">
                  {(task.keywords ?? []).slice(0, 4).join(" / ") || "没有关键词"}
                  {` · ${describeSchedule(task)}`}
                </span>
                <span className="ao__meta ao__meta--dim">
                  {task.last_run_at
                    ? `上次 ${task.last_run_at.replace("T", " ").slice(0, 16)}`
                    : "还没跑过"}
                  {task.next_run_at
                    ? ` · 下次 ${task.next_run_at.replace("T", " ").slice(0, 16)}`
                    : ""}
                  {task.total_published > 0 ? ` · 已建发布任务 ${task.total_published} 条` : ""}
                </span>
              </div>
              <div className="ao__rowActs">
                <Button
                  size="sm"
                  variant="primary"
                  loading={busy === task.id}
                  onClick={() => void run(task)}
                >
                  跑一次
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  loading={busy === task.id}
                  onClick={() => void toggleStatus(task)}
                >
                  {task.status === "active" ? "暂停" : "启用"}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setEditing(task);
                    setFormOpen(true);
                  }}
                >
                  改
                </Button>
                <Button
                  size="sm"
                  variant="danger"
                  onClick={() => setConfirmDelete(task)}
                >
                  删
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <p className="ao__note">
        手动跑和定时跑用的是同一套后端逻辑，唯一区别是谁按的发送键。
        定时跑需要调度器在运行（「设置 → 风险开关」底部那行状态）。
      </p>

      <TaskForm
        open={formOpen}
        editing={editing}
        pcAccounts={pcAccounts}
        creatorAccounts={creatorAccounts}
        templates={templates}
        onClose={() => setFormOpen(false)}
        onSaved={() => {
          setFormOpen(false);
          invalidate("autoops|tasks");
        }}
      />

      <ConfirmDialog
        open={Boolean(confirmDelete)}
        title={`删掉「${confirmDelete?.name ?? ""}」？`}
        description="任务本身会删掉，已经产出的草稿和发布任务不受影响。"
        confirmLabel="删除"
        danger
        loading={busy === confirmDelete?.id}
        onConfirm={() => confirmDelete && void remove(confirmDelete)}
        onCancel={() => setConfirmDelete(null)}
      />
    </div>
  );
}

/* ---------------- 最近一次运行的结果 ---------------- */

function LastRunCard({
  data,
  onClose,
}: {
  data: { task: AutoTask; result: AutoTaskRunResult };
  onClose: () => void;
}) {
  const { result } = data;
  const where = result.auto_publish
    ? "已经直接发出去了"
    : result.publish_job
      ? "建了一条待发布任务，等你确认"
      : "只生成草稿，没有建发布任务";
  return (
    <div className="ao__result" role="status">
      <div className="ao__resultHead">
        <strong>刚跑完：命中「{result.keyword}」</strong>
        <button type="button" className="ao__resultX" onClick={onClose} aria-label="收起">
          ×
        </button>
      </div>
      <div className="ao__resultBody">
        <span>
          来源：{result.source_note?.title || "（没有标题）"}
          {typeof result.source_note?.likes === "number"
            ? ` · 赞 ${result.source_note.likes}`
            : ""}
        </span>
        <span>
          产出：
          {result.draft?.title || "（没有草稿）"}
          {typeof result.draft?.id === "number" ? `（草稿 #${result.draft.id}）` : ""}
        </span>
        <span>{where}</span>
      </div>
    </div>
  );
}

/* ---------------- 新建 / 编辑表单 ---------------- */

function TaskForm({
  open,
  editing,
  pcAccounts,
  creatorAccounts,
  templates,
  onClose,
  onSaved,
}: {
  open: boolean;
  editing: AutoTask | null;
  pcAccounts: AccountRow[];
  creatorAccounts: AccountRow[];
  templates: Array<{ id: number; name: string }>;
  onClose: () => void;
  onSaved: () => void;
}) {
  const toast = useToast();
  const [name, setName] = useState("");
  const [keywords, setKeywords] = useState("");
  const [pcId, setPcId] = useState("");
  const [creatorId, setCreatorId] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [instruction, setInstruction] = useState("");
  const [scheduleType, setScheduleType] = useKeptState("autoops|sched", "manual");
  const [scheduleTime, setScheduleTime] = useState("09:00");
  const [weekdays, setWeekdays] = useState<string[]>([]);
  const [intervalHours, setIntervalHours] = useState("24");
  const [saving, setSaving] = useState(false);

  /*
   * 用 useEffect 灌初值而不是「渲染时按 key 重置」。
   *
   * 渲染期改 state 在 React 里是允许的（文档里的 adjust-state-on-props-change），
   * 但 `setScheduleType` 走的是 useKeptState，它同时写模块级 store ——
   * 那是副作用，不能放在渲染里。所以统一在打开时灌一次。
   */
  const key = editing?.id ?? -1;
  useEffect(() => {
    if (!open) return;
    setName(editing?.name ?? "");
    setKeywords((editing?.keywords ?? []).join(", "));
    setPcId(String(editing?.pc_account_id ?? pcAccounts[0]?.id ?? ""));
    setCreatorId(String(editing?.creator_account_id ?? creatorAccounts[0]?.id ?? ""));
    setTemplateId(editing?.template_id ? String(editing.template_id) : "");
    setInstruction(editing?.ai_instruction ?? "");
    setScheduleType(editing?.schedule_type ?? "manual");
    setScheduleTime(editing?.schedule_time ?? "09:00");
    setWeekdays((editing?.schedule_days ?? "").split(",").filter(Boolean));
    setIntervalHours(String(editing?.schedule_interval_hours ?? 24));
    // key 变化（换了一条任务）才重灌；用户在表单里改的东西不回灌
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, key]);

  const words = keywords
    .split(/[,，\s]+/)
    .map((w) => w.trim())
    .filter(Boolean);

  async function save() {
    if (!name.trim()) {
      toast.error("先给任务起个名字");
      return;
    }
    if (words.length === 0) {
      toast.error("至少填一个关键词，不然没东西可搜");
      return;
    }
    if (!pcId || !creatorId) {
      toast.error("两个账号都要选");
      return;
    }
    setSaving(true);
    try {
      const base = {
        name: name.trim(),
        keywords: words,
        pc_account_id: Number(pcId),
        creator_account_id: Number(creatorId),
        template_id: templateId ? Number(templateId) : null,
        ai_instruction: instruction.trim(),
        schedule_type: scheduleType as "manual" | "daily" | "weekly" | "interval",
        schedule_time: scheduleTime,
        schedule_days: weekdays.join(","),
        schedule_interval_hours: Number(intervalHours) || 24,
      };
      if (editing) {
        await updateAutoTask(editing.id, base);
        toast.success("已保存");
      } else {
        await createAutoTask(base);
        toast.success("任务已建");
      }
      onSaved();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  const scheduleLabel = SCHEDULE_OPTIONS.find((o) => o.value === scheduleType)?.label ?? "";

  return (
    <Modal
      open={open}
      title={editing ? "改自动运营任务" : "新建自动运营任务"}
      hint="给几个关键词，系统会挑互动最高的那篇当参考，改写成你的稿子。"
      width={560}
      onClose={onClose}
      footNote={
        scheduleType === "manual"
          ? "只在你点「跑一次」的时候动"
          : "定时跑需要调度器在运行，见「风险开关」底部状态"
      }
      footer={
        <>
          <Button variant="ghost" size="sm" onClick={onClose}>
            取消
          </Button>
          <Button variant="primary" size="sm" loading={saving} onClick={() => void save()}>
            {editing ? "保存" : "建任务"}
          </Button>
        </>
      }
    >
      <div className="ao__form">
        <Input
          label="任务名"
          value={name}
          placeholder="比如：AI 工具拆解 · 日更"
          onChange={setName}
          maxLength={128}
          data-autofocus
        />
        <Input
          label="关键词"
          hint="逗号分隔。每次随机挑一个去搜。"
          value={keywords}
          placeholder="AI 工具, 效率, 副业"
          onChange={setKeywords}
        />
        <div className="ao__two">
          <Select
            label="PC 账号（搜索用）"
            value={pcId}
            options={pcAccounts.map((a) => ({
              value: String(a.id),
              label: a.nickname || `账号 ${a.id}`,
            }))}
            onChange={setPcId}
          />
          <Select
            label="创作中心账号（发布用）"
            value={creatorId}
            options={creatorAccounts.map((a) => ({
              value: String(a.id),
              label: a.nickname || `账号 ${a.id}`,
            }))}
            onChange={setCreatorId}
          />
        </div>
        <Select
          label="结构模板"
          hint="选了就按同一套开头/中段/结尾骨架写；不选由模型自己定。"
          value={templateId}
          options={[
            { value: "", label: "不指定" },
            ...templates.map((t) => ({ value: String(t.id), label: t.name })),
          ]}
          onChange={setTemplateId}
        />
        <Textarea
          label="改写要求"
          hint="留空用默认要求：保持核心信息，提升表达和语感。"
          value={instruction}
          placeholder="比如：换成第一人称，多讲一个具体场景，不要用感叹号"
          onChange={setInstruction}
          rows={3}
          maxLength={2000}
        />
        <Select
          label="什么时候跑"
          value={scheduleType}
          options={SCHEDULE_OPTIONS}
          onChange={setScheduleType}
        />
        {scheduleType === "daily" || scheduleType === "weekly" ? (
          <Input
            label="几点"
            hint="24 小时制，例如 09:30"
            value={scheduleTime}
            placeholder="09:00"
            onChange={setScheduleTime}
          />
        ) : null}
        {scheduleType === "weekly" ? (
          <div className="ao__days" role="group" aria-label="每周哪几天">
            {WEEKDAYS.map((d) => {
              const on = weekdays.includes(d.value);
              return (
                <button
                  key={d.value}
                  type="button"
                  className={`ao__day${on ? " is-on" : ""}`}
                  aria-pressed={on}
                  onClick={() =>
                    setWeekdays((prev) =>
                      on ? prev.filter((x) => x !== d.value) : [...prev, d.value],
                    )
                  }
                >
                  {d.label}
                </button>
              );
            })}
          </div>
        ) : null}
        {scheduleType === "interval" ? (
          <Input
            label="每几小时"
            hint="1 到 168 之间"
            value={intervalHours}
            onChange={setIntervalHours}
            inputMode="numeric"
          />
        ) : null}
        <p className="ao__formHint">
          当前设置：{scheduleLabel}
          {scheduleType === "daily" || scheduleType === "weekly"
            ? ` ${scheduleTime}`
            : ""}
          {scheduleType === "interval" ? ` · 每 ${intervalHours} 小时` : ""}
        </p>
      </div>
    </Modal>
  );
}
