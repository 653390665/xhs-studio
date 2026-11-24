import { get, post } from "./api";

/**
 * backendTasks.ts — 后端 `tasks` 表的取数层
 *
 * 注意与 `lib/tasks.ts` 区分：那一个是**浏览器内存**里的长任务登记处
 * （切页不丢进度），这一层读的是**后端** `tasks` 表。
 *
 * 后端早就有 `/api/tasks`、`/api/tasks/{id}`、`/api/tasks/{id}/cancel`、
 * `/api/tasks/{id}/retry`，前端零调用。后果是「生成到一半失败了」只能从
 * toast 里看到一眼，刷新就没了——失败原因（error_type、payload.error、
 * 耗时）全在库里，界面上无处可查。
 */

export interface BackendTask {
  id: number;
  platform: string;
  task_type: string;
  status: string;
  progress: number;
  payload: Record<string, unknown>;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  error_type: string | null;
  retry_count: number;
  max_retries: number;
  parent_task_id: number | null;
}

export interface TaskList {
  items: BackendTask[];
  total: number;
}

export interface TaskDetail extends BackendTask {
  children: BackendTask[];
}

/** 任务类型的用户可读名。后端存的是 `ai_generate_note` 这种内部代号 */
export const TASK_TYPE_LABEL: Record<string, string> = {
  ai_generate_note: "生成初稿",
  ai_generate_title: "生成标题",
  ai_generate_tags: "生成标签",
  ai_polish_text: "润色",
  ai_rewrite: "改写",
  ai_outline: "整理角度",
  ai_image_generate: "生成配图",
  ai_image_cover: "生成封面",
  ai_image_describe: "读图",
  creator_publish: "发布",
  creator_publish_scheduler: "定时发布",
  creator_publish_retry: "重试发布",
  creator_publish_cancel: "取消发布",
  publish: "发布",
  douyin_extract: "抖音提取",
  extract: "提取",
  monitoring_refresh: "监控刷新",
  auto_ops_run: "自动运营",
};

export function taskTypeLabel(taskType: string): string {
  return TASK_TYPE_LABEL[taskType] ?? taskType;
}

export const TASK_STATUS_LABEL: Record<string, { text: string; tone: string }> = {
  pending: { text: "排队中", tone: "muted" },
  running: { text: "进行中", tone: "warn" },
  completed: { text: "已完成", tone: "ok" },
  failed: { text: "失败", tone: "danger" },
  exhausted: { text: "重试耗尽", tone: "danger" },
  cancelled: { text: "已取消", tone: "muted" },
};

export async function getTasks(limit = 40): Promise<TaskList> {
  const payload = await get<unknown>(`/api/tasks?page_size=${limit}`);
  // 后端返回 `{total, page, page_size, items}`；这里只取两个要用的
  const obj = (payload ?? {}) as Record<string, unknown>;
  const items = Array.isArray(obj.items) ? (obj.items as BackendTask[]) : [];
  return { items, total: typeof obj.total === "number" ? obj.total : items.length };
}

export function getTask(taskId: number): Promise<TaskDetail> {
  return get<TaskDetail>(`/api/tasks/${taskId}`);
}

export function cancelTask(taskId: number): Promise<BackendTask> {
  return post<BackendTask>(`/api/tasks/${taskId}/cancel`, {});
}

export function retryTask(taskId: number): Promise<BackendTask> {
  return post<BackendTask>(`/api/tasks/${taskId}/retry`, {});
}

/** 从 payload 里读失败原因：后端把异常字符串放在 payload.error */
export function taskError(task: BackendTask): string {
  const fromPayload = task.payload?.error;
  if (typeof fromPayload === "string" && fromPayload.trim()) return fromPayload;
  if (task.error_type) return task.error_type;
  return "";
}

/** 耗时：后端算好的 duration_ms，退化到 started/finished 之差 */
export function taskDurationMs(task: BackendTask): number | null {
  if (typeof task.duration_ms === "number") return task.duration_ms;
  if (task.started_at && task.finished_at) {
    const ms =
      new Date(task.finished_at).getTime() - new Date(task.started_at).getTime();
    return Number.isFinite(ms) ? ms : null;
  }
  return null;
}
