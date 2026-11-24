/**
 * Notifications.tsx — 侧栏底部的通知入口
 *
 * 后端一直在写通知（任务失败、重试耗尽、Cookie 过期、发布失败、监控暂停），
 * 前端从来没有读过一条。结果是：**所有后台失败都静默**。
 *
 * 这里的定位不是「消息中心」，而是一个**未读徽标**：
 *   有未读 → 红点 + 数字；点开 → 列表；点一条 → 去能解决它的页面。
 *
 * 不做的：实时推送（没有 SSE）、分类筛选（量小到不需要）、
 * 「已读」的撤销（后端没有端点）。
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import Button from "./Button";
import { useToast } from "./Toast";
import { invalidate, useQuery } from "../lib/query";
import {
  LEVEL_TEXT,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  notificationTarget,
  type AppNotification,
} from "../lib/notifications";
import { IconAlert } from "./Icon";
import "./Notifications.css";

export default function Notifications() {
  const toast = useToast();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const panel = useRef<HTMLDivElement | null>(null);

  const q = useQuery(() => listNotifications({ pageSize: 30 }), [], {
    key: "shell|notifications",
    // 后台失败不是「实时」需求，一分钟一次足够；主要靠切页时重取
    staleTime: 60_000,
  });

  const items = useMemo(() => q.data?.items ?? [], [q.data]);
  const unread = useMemo(() => items.filter((n) => !n.read), [items]);

  // 点外面关掉。不做成抽屉：通知少，浮一层就够。
  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (panel.current && !panel.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  async function openItem(item: AppNotification) {
    // 先跳再标已读：跳转是用户的主诉求，标记失败不该挡住它
    const target = notificationTarget(item);
    setOpen(false);
    navigate(target);
    if (!item.read) {
      try {
        await markNotificationRead(item.id);
        invalidate("shell|notifications");
      } catch {
        /* 标不上已读不算错误，下次还会显示 */
      }
    }
  }

  async function markAll() {
    if (unread.length === 0) return;
    try {
      await markAllNotificationsRead();
      invalidate("shell|notifications");
      toast.success("已全部标为已读");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "标记失败");
    }
  }

  /*
   * 读不到通知时不显示徽标，但也不假装「没有通知」。
   * 侧栏空间小，这里只能保持安静；详情在「设置 → 运行状态」里能看到
   * 任务失败数，那里是更合适的排错入口。
   */
  if (q.error) return null;

  return (
    <div className="notif" ref={panel}>
      <button
        type="button"
        className={`notif__bell${unread.length > 0 ? " is-unread" : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={
          unread.length > 0 ? `通知，${unread.length} 条未读` : "通知，无未读"
        }
        title={unread.length > 0 ? `${unread.length} 条未读通知` : "没有新通知"}
      >
        <IconAlert size={15} />
        {unread.length > 0 ? (
          <span className="notif__badge">
            {unread.length > 9 ? "9+" : unread.length}
          </span>
        ) : null}
      </button>

      {open ? (
        <div className="notif__panel" role="dialog" aria-label="通知">
          <div className="notif__head">
            <span className="notif__title">
              通知{unread.length > 0 ? `（${unread.length} 条未读）` : ""}
            </span>
            {unread.length > 0 ? (
              <Button size="sm" variant="ghost" onClick={() => void markAll()}>
                全部已读
              </Button>
            ) : null}
          </div>

          {q.initialLoading ? (
            <p className="notif__empty">正在读…</p>
          ) : items.length === 0 ? (
            <p className="notif__empty">
              没有通知。任务失败、Cookie 过期、发布失败时会出现在这里。
            </p>
          ) : (
            <ul className="notif__list">
              {items.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    className={`notif__item${item.read ? "" : " is-unread"}`}
                    onClick={() => void openItem(item)}
                  >
                    <span className={`notif__level is-${item.level}`}>
                      {LEVEL_TEXT[item.level] ?? item.level}
                    </span>
                    <span className="notif__item-main">
                      <span className="notif__item-title">{item.title}</span>
                      {item.body ? (
                        <span className="notif__item-body">{item.body}</span>
                      ) : null}
                    </span>
                    <span className="notif__item-time">
                      {item.created_at.replace("T", " ").slice(5, 16)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
