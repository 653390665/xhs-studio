/**
 * tasks.ts — 长任务登记处（跨页面存活）
 *
 * 为什么需要这一层（问题已实测复现）：
 *   Shell 的内容区写成 <main key={location.pathname}>，换一次路由
 *   React 就把整棵页面子树卸载重建。采集 / 蒸馏 / 生成 / 生成选题
 *   这些十几秒到几分钟的任务，状态全挂在组件里，于是：
 *     切到别的页面 → 组件卸载 → 进度、结果、错误全丢；
 *     切回来 → 组件重新挂载 → 界面回到"没开始"的样子。
 *   后端请求其实还在跑，但用户看到的是"一切归零"，以为被中断了。
 *
 * 做法：
 *   把任务状态放在模块级 store 里（和 query.ts 同一套思路，不引新依赖），
 *   组件只订阅、只发起，不再持有。切页不走丢，切回来还在。
 *
 * 约定：
 *   1. 一个 kind 同时只跑一个任务（采集不要并发开两个，会被后端限流）。
 *   2. 任务结束后保留一段时间，让回到页面的用户看到"已完成/失败了"。
 *   3. 真正的取消只能由用户点，不因为组件卸载而取消。
 */

import { useSyncExternalStore } from "react";
import { invalidate } from "./query";

export type TaskKind =
  | "capture" /* 采集外部笔记 */
  | "distill" /* 蒸馏写法 */
  | "topics" /* 批量生成选题 */
  | "generate" /* 生成草稿 */
  | "rewrite" /* 批量改写成草稿 */
  | "search" /* 在线检索 */
  | "benchmark"; /* 对标抓取 */

export type TaskStatus = "running" | "done" | "failed";

export interface Task {
  id: string;
  kind: TaskKind;
  /** 一句话说现在在干什么，直接显示在界面上 */
  label: string;
  /** 更细的进度文案，比如"已抓 3 条" */
  detail: string;
  done?: number;
  total?: number;
  startedAt: number;
  endedAt?: number;
  status: TaskStatus;
  /** 失败原因，后端原话 */
  error?: string;
  /** 结果对象（每个 kind 自己定形状），页面自己解读 */
  result?: unknown;
  /** 完成后的补充说明，比如"入库 12 条" */
  note?: string;
  /** 完成后要刷新的 query key 前缀 */
  invalidates?: string[];
}

/* ============================================================
   存储与订阅
   ============================================================ */

const tasks = new Map<string, Task>();
/** 每个任务的 AbortController：取消按钮要靠它真的掐断请求 */
const controllers = new Map<string, AbortController>();
const listeners = new Set<() => void>();

/**
 * useSyncExternalStore 要求 getSnapshot 返回同一个引用直到真的变了，
 * 所以这里缓存一份数组，只在数据变动时重建。
 */
let snapshot: Task[] = [];

function rebuild(): void {
  snapshot = Array.from(tasks.values()).sort((a, b) => b.startedAt - a.startedAt);
  listeners.forEach((fn) => fn());
}

export function subscribeTasks(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export function getTasksSnapshot(): Task[] {
  return snapshot;
}

let seq = 0;

/** 已结束的任务保留多久再清掉（给用户留出看到结果的时间） */
const KEEP_FINISHED_MS = 120_000;

function scheduleCleanup(id: string): void {
  window.setTimeout(() => {
    const t = tasks.get(id);
    if (t && t.status !== "running") {
      tasks.delete(id);
      controllers.delete(id);
      rebuild();
    }
  }, KEEP_FINISHED_MS);
}

/* ============================================================
   任务句柄：调用方拿它更新进度、收尾
   ============================================================ */

export interface TaskHandle {
  id: string;
  signal: AbortSignal;
  /** 更新进度文案 / 条数 */
  update(patch: { detail?: string; done?: number; total?: number }): void;
  /** 成功收尾 */
  finish(result?: unknown, note?: string): void;
  /** 失败收尾，message 用后端原话 */
  fail(message: string): void;
  /** 用户主动取消 */
  cancel(): void;
  /** 是否已被取消（避免取消后又去 setState） */
  cancelled(): boolean;
}

/**
 * 开始一个任务。
 * 同一个 kind 已经有在跑的任务时，返回 null —— 调用方据此提示"已经在跑了"。
 */
export function startTask(
  kind: TaskKind,
  label: string,
  options: { detail?: string; total?: number; invalidates?: string[] } = {},
): TaskHandle | null {
  const running = Array.from(tasks.values()).find(
    (t) => t.kind === kind && t.status === "running",
  );
  if (running) return null;

  const id = `${kind}-${++seq}`;
  const controller = new AbortController();

  const task: Task = {
    id,
    kind,
    label,
    detail: options.detail ?? "",
    total: options.total,
    done: options.total === undefined ? undefined : 0,
    startedAt: Date.now(),
    status: "running",
    invalidates: options.invalidates,
  };
  tasks.set(id, task);
  controllers.set(id, controller);
  rebuild();

  let wasCancelled = false;

  return {
    id,
    signal: controller.signal,
    update(patch) {
      const cur = tasks.get(id);
      if (!cur || cur.status !== "running") return;
      if (patch.detail !== undefined) cur.detail = patch.detail;
      if (patch.done !== undefined) cur.done = patch.done;
      if (patch.total !== undefined) cur.total = patch.total;
      rebuild();
    },
    finish(result, note) {
      const cur = tasks.get(id);
      if (!cur) return;
      cur.status = "done";
      cur.result = result;
      cur.note = note;
      cur.detail = note ?? cur.detail;
      cur.endedAt = Date.now();
      rebuild();
      /*
       * 疯任务完成时发起页可能已经不在了（用户切走了）。
       * 所以刷新不能只靠页面自己调 invalidate——这里统一补一次，
       * 否则切回列表页会看到"入库 0 条"的旧数据。
       */
      cur.invalidates?.forEach((k) => invalidate(k));
      scheduleCleanup(id);
    },
    fail(message) {
      const cur = tasks.get(id);
      if (!cur) return;
      cur.status = "failed";
      cur.error = message;
      cur.detail = message;
      cur.endedAt = Date.now();
      rebuild();
      scheduleCleanup(id);
    },
    cancel() {
      wasCancelled = true;
      controller.abort();
      const cur = tasks.get(id);
      if (!cur) return;
      cur.status = "failed";
      cur.error = "已取消";
      cur.detail = "已取消";
      cur.endedAt = Date.now();
      rebuild();
      scheduleCleanup(id);
    },    cancelled() {
      return wasCancelled;
    },
  };
}

/** 某个 kind 最近一个任务（在跑的优先，否则最近结束的） */
export function latestTask(kind: TaskKind): Task | undefined {
  const ofKind = snapshot.filter((t) => t.kind === kind);
  return ofKind.find((t) => t.status === "running") ?? ofKind[0];
}

/**
 * 取消任务。
 * 取消必须由用户点，不能因为组件卸载就取消——
 * 这正是"切页任务被掐掉"的根因，这里把按钮和信号绑在一起。
 */
export function cancelTask(id: string): void {
  const controller = controllers.get(id);
  controller?.abort();
  const cur = tasks.get(id);
  if (!cur) return;
  cur.status = "failed";
  cur.error = "已取消";
  cur.detail = "已取消";
  cur.endedAt = Date.now();
  rebuild();
  scheduleCleanup(id);
}

/** 手动清掉某个 kind 的结果（用户点"知道了"/关提示时用） */
export function dismissTask(id: string): void {
  tasks.delete(id);
  controllers.delete(id);
  rebuild();
}

/* ============================================================
   Hooks
   ============================================================ */

export function useTasks(): Task[] {
  return useSyncExternalStore(
    subscribeTasks,
    getTasksSnapshot,
    getTasksSnapshot,
  );
}

export function useTask(kind: TaskKind): Task | undefined {
  const all = useTasks();
  const ofKind = all.filter((t) => t.kind === kind);
  return ofKind.find((t) => t.status === "running") ?? ofKind[0];
}

/** 是否有任何任务在跑（给外壳的状态指示用） */
export function useRunningTasks(): Task[] {
  return useTasks().filter((t) => t.status === "running");
}
