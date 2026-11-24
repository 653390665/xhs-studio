/**
 * notifications.ts — 通知的唯一取数层
 *
 * 后端有三个端点、有五个写入函数，前端**零调用**：
 *   GET  /api/notifications               列表（可按未读过滤）
 *   POST /api/notifications/{id}/read     标记已读
 *   POST /api/notifications/read-all      全部已读
 *
 * 后果不是「少一个功能」，而是**后台失败没人知道**：定时发布在半夜失败、
 * Cookie 过期、监控被自动暂停，这些都写进库了，但用户只有在主动去翻
 * 发布队列时才会撞见。通知存在的意义就是「不用主动翻」。
 */

import { get, post, unwrapList } from "./api";

export type NotificationLevel = "info" | "warning" | "error";

export interface AppNotification {
  id: number;
  title: string;
  body: string;
  level: NotificationLevel | string;
  /** 由哪个任务触发（如果来自任务失败） */
  source_task_id?: number | null;
  /** task / publish_job / account / target */
  source_type?: string | null;
  source_id?: number | null;
  read: boolean;
  created_at: string;
}

export interface NotificationList {
  items: AppNotification[];
  total: number;
}

export async function listNotifications(
  options: { unreadOnly?: boolean; pageSize?: number } = {},
): Promise<NotificationList> {
  const query = new URLSearchParams();
  if (options.unreadOnly) query.set("unread", "true");
  query.set("page_size", String(options.pageSize ?? 30));
  const payload = await get<unknown>(`/api/notifications?${query.toString()}`);
  const list = unwrapList<AppNotification>(payload);
  return { items: list.items, total: list.total };
}

export function markNotificationRead(id: number): Promise<AppNotification> {
  return post<AppNotification>(`/api/notifications/${id}/read`, {});
}

export function markAllNotificationsRead(): Promise<{ marked: number }> {
  return post<{ marked: number }>("/api/notifications/read-all", {});
}

/** 通知指向哪里：点一条要去能解决它的地方，而不是停在原地 */
export function notificationTarget(item: AppNotification): string {
  switch (item.source_type) {
    case "publish_job":
      return "/publish";
    case "account":
      return "/settings/accounts";
    case "target":
      return "/assets";
    case "task":
      return "/settings/status";
    default:
      return "/settings/status";
  }
}

export const LEVEL_TEXT: Record<string, string> = {
  info: "提示",
  warning: "注意",
  error: "错误",
};
