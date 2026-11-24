/**
 * douyin.ts — 抖音采集的取数层
 *
 * 后端整条链路都在（采集 → 转写 → 导入对标集），新前端一处没接。
 * 这里只做薄封装，不重写任何后端逻辑。
 *
 * 三步的分工要记清：
 *   ① 建任务：给一份清单 / 链接 / 主页，后端去下载 + 转写
 *   ② 导入对标集：把转写文稿写成 Note 挂进 CorpusSet —— 这是采集和蒸馏之间
 *      唯一的桥，没有它，文稿就只是磁盘上的文件
 *   ③ 蒸馏：走 /api/xhs/evidence-distill（Skill 中心已有的那个）
 */

import { get, post } from "./api";

/* ============================================================
   环境
   ============================================================ */

export interface DouyinMeta {
  asr_ready: boolean;
  engine: string;
  hint: string;
  ffmpeg: boolean;
  ffprobe: boolean;
  ffmpeg_path?: string;
  ffprobe_path?: string;
  model_size?: string;
  device_plan?: string[];
  source_types?: string[];
  profile_note?: string;
}

export function loadMeta(): Promise<DouyinMeta> {
  return get<DouyinMeta>("/api/douyin/extract/meta");
}

/* ============================================================
   任务
   ============================================================ */

export type SourceType = "manifest" | "links" | "profile";

export interface ExtractJob {
  id: number;
  source_type: string;
  account_name: string;
  status: string;
  stage: string;
  total: number;
  completed: number;
  failed: number;
  skipped: number;
  no_speech: number;
  fetch_media: boolean;
  transcribe: boolean;
  keep_media: boolean;
  output_dir: string;
  error: string;
  created_at: string;
  started_at: string;
  finished_at: string;
  engine: string;
  running: boolean;
}

export interface ExtractWork {
  id: number;
  job_id: number;
  work_id: string;
  work_type: string;
  url: string;
  title: string;
  caption: string;
  author_name: string;
  author_id: string;
  published_at: string;
  collected_at: string;
  duration_seconds: number | null;
  image_count: number;
  status: string;
  transcript_source: string;
  transcript_chars: number;
  error: string;
  retry_count: number;
}

export interface ExtractJobDetail extends ExtractJob {
  works: ExtractWork[];
  files: Array<{ path: string; name?: string; size?: number }>;
  source_preview?: string;
  audit_text?: string;
}

export function createJob(payload: {
  source_type: SourceType;
  source: string;
  account_name?: string;
  limit?: number;
  transcribe?: boolean;
  keep_media?: boolean;
  auto_start?: boolean;
  force?: boolean;
}): Promise<ExtractJob> {
  return post<ExtractJob>("/api/douyin/extract/jobs", payload);
}

export function loadJobs(
  page = 1,
  pageSize = 20,
): Promise<{ items: ExtractJob[]; total: number }> {
  return get(`/api/douyin/extract/jobs?page=${page}&page_size=${pageSize}`);
}

export function loadJob(id: number): Promise<ExtractJobDetail> {
  return get<ExtractJobDetail>(`/api/douyin/extract/jobs/${id}`);
}

export function runJob(id: number): Promise<unknown> {
  return post(`/api/douyin/extract/jobs/${id}/run`, {});
}

export function pauseJob(id: number): Promise<unknown> {
  return post(`/api/douyin/extract/jobs/${id}/pause`, {});
}

/** 文件下载是 GET + 查询串，走浏览器直链更省事 */
export function fileUrl(jobId: number, path: string): string {
  return `/api/douyin/extract/jobs/${jobId}/file?path=${encodeURIComponent(path)}`;
}

/* ============================================================
   导入对标集（采集 → 蒸馏的桥）
   ============================================================ */

export interface ImportCorpusResult {
  set_id: number;
  imported: number;
  missing: string[];
  added_members?: number;
  created_notes?: number;
}

export function importToCorpus(
  jobId: number,
  payload: {
    name?: string;
    genre?: "experience" | "list" | "opinion" | "event" | "recruit";
    role?: "baseline" | "negative" | "neutral";
    set_id?: number | null;
  },
): Promise<ImportCorpusResult> {
  return post<ImportCorpusResult>(`/api/douyin/extract/jobs/${jobId}/corpus`, {
    name: payload.name ?? "",
    genre: payload.genre ?? "opinion",
    role: payload.role ?? "baseline",
    set_id: payload.set_id ?? null,
  });
}

/* ============================================================
   状态文案
   ============================================================ */

const STATUS_LABEL: Record<string, string> = {
  draft: "待运行",
  running: "运行中",
  paused: "已暂停",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

const STAGE_LABEL: Record<string, string> = {
  discover: "发现作品",
  download: "下载媒体",
  transcribe: "转写文稿",
  review: "整理",
  deliver: "交付",
  done: "完成",
};

export function jobStatusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status;
}

export function jobStageLabel(stage: string): string {
  return STAGE_LABEL[stage] ?? stage;
}

/** 任务是否还需要轮询：运行中或排队中 */
export function jobBusy(job: ExtractJob | null | undefined): boolean {
  if (!job) return false;
  return job.running || job.status === "running" || job.status === "queued";
}
