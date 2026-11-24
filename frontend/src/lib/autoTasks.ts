/**
 * autoTasks.ts — 自动运营任务的取数层
 *
 * 后端 `/api/auto-tasks` 一套完整（建/改/删/手动跑/异步跑/调度器定时跑），
 * 前端**零调用**。于是「设置 → 风险开关」里 `auto_ops_enabled` 那张卡
 * 只能写「尚无入口」——打开开关不会有任何可观察的变化。
 *
 * 这一层把它接上。三个必须记住的约束：
 *
 * 1. 建任务需要 **pc 账号 + creator 账号** 两个 id（`auto_tasks.py:178-179`），
 *    少一个后端直接 404。所以界面在建任务前要先说清缺哪个。
 * 2. 手动跑还会再过四道风险开关（`_prepare_auto_task_run`）：
 *    auto_ops / competitor_rewrite / （auto_publish 时）copy_source_images。
 *    开关没开就 403，不是失败——是还没允许。
 * 3. 产出是**草稿**。建不建发布任务由 `auto_create_publish_job_enabled`
 *    决定，发不发自走由 `auto_publish_enabled` 决定。
 */

import { del, get, patch, post, unwrapList, type ListEnvelope } from "./api";

export interface AutoTask {
  id: number;
  name: string;
  keywords: string[];
  pc_account_id: number;
  creator_account_id: number;
  template_id?: number | null;
  ai_instruction: string;
  status: "active" | "paused" | "completed" | string;
  schedule_type: "manual" | "daily" | "weekly" | "interval" | string;
  schedule_time: string;
  schedule_days: string;
  schedule_interval_hours: number;
  last_run_at?: string | null;
  next_run_at?: string | null;
  total_published: number;
  created_at: string;
}

export interface AutoTaskPayload {
  name: string;
  keywords: string[];
  pc_account_id: number;
  creator_account_id: number;
  template_id?: number | null;
  ai_instruction?: string;
  schedule_type?: "manual" | "daily" | "weekly" | "interval";
  schedule_time?: string;
  schedule_days?: string;
  schedule_interval_hours?: number;
}

export interface AutoTaskRunResult {
  auto_task: AutoTask;
  keyword: string;
  source_note?: {
    note_id?: string;
    title?: string;
    likes?: number;
    collects?: number;
    comments?: number;
  };
  draft?: { id: number; title: string; body: string; created_at: string };
  publish_job?: {
    id: number;
    status: string;
    platform_account_id: number;
    publish_mode: string;
  } | null;
  auto_publish: boolean;
}

export function listAutoTasks(): Promise<AutoTask[]> {
  return get<ListEnvelope<AutoTask>>("/api/auto-tasks?page=1&page_size=100").then(
    (r) => unwrapList<AutoTask>(r).items,
  );
}

export function createAutoTask(payload: AutoTaskPayload): Promise<AutoTask> {
  return post<AutoTask>("/api/auto-tasks", payload);
}

export function updateAutoTask(
  id: number,
  payload: Partial<AutoTaskPayload> & { status?: string },
): Promise<AutoTask> {
  return patch<AutoTask>(`/api/auto-tasks/${id}`, payload);
}

export function deleteAutoTask(id: number): Promise<unknown> {
  return del(`/api/auto-tasks/${id}`);
}

/**
 * 手动跑一次（同步）。
 *
 * 一次要搜一篇、改写、可能建发布任务，10-30 秒。用同步版本而不是
 * `run-async`：这条链路的每一步都会在界面上回显（命中哪篇、出了什么草稿），
 * 用户点完就是在等这个结果。真正需要无人值守的是调度器，那条路已经走异步。
 */
export function runAutoTask(id: number): Promise<AutoTaskRunResult> {
  return post<AutoTaskRunResult>(`/api/auto-tasks/${id}/run`, {});
}

/** 调度间隔的人话 */
export function describeSchedule(task: AutoTask): string {
  switch (task.schedule_type) {
    case "manual":
      return "只在我点的时候跑";
    case "daily":
      return `每天 ${task.schedule_time}`;
    case "weekly": {
      const names = ["一", "二", "三", "四", "五", "六", "日"];
      const days = (task.schedule_days || "")
        .split(",")
        .map((d) => Number(d))
        .filter((d) => d >= 1 && d <= 7)
        .map((d) => `周${names[d - 1]}`);
      return days.length
        ? `每${days.join("、")} ${task.schedule_time}`
        : `每周 ${task.schedule_time}（未选星期）`;
    }
    case "interval":
      return `每 ${task.schedule_interval_hours} 小时`;
    default:
      return task.schedule_type;
  }
}
