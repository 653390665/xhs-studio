/**
 * Toast.tsx — 轻提示
 *
 * 规范（BRIEF 第 4 节 #6 #7）：
 * - 右上角滑入 translateY(-8px) + fade，150ms
 * - 成功 / 失败 / 进行中 三种状态
 * - 3.5s 自动消失，可手动关闭，最多同时 3 条
 * - 支持 action（如"撤销"），用于删除后的可恢复操作
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import "./Toast.css";

export type ToastKind = "success" | "error" | "pending" | "info";

export interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
  action?: ToastAction;
  /** 自动消失时长；0 表示不自动消失 */
  duration?: number;
}

interface ToastContextValue {
  push: (toast: Omit<ToastItem, "id">) => number;
  dismiss: (id: number) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const MAX_TOASTS = 3;
const DEFAULT_DURATION = 3500;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);
  const timers = useRef(new Map<number, number>());

  const dismiss = useCallback((id: number) => {
    setItems((prev) => prev.filter((t) => t.id !== id));
    const timer = timers.current.get(id);
    if (timer) {
      window.clearTimeout(timer);
      timers.current.delete(id);
    }
  }, []);

  const push = useCallback(
    (toast: Omit<ToastItem, "id">) => {
      const id = nextId.current++;
      const duration = toast.duration ?? DEFAULT_DURATION;

      setItems((prev) => {
        const next = [...prev, { ...toast, id }];
        // 超出上限：丢弃最早的一条
        return next.length > MAX_TOASTS ? next.slice(next.length - MAX_TOASTS) : next;
      });

      if (duration > 0) {
        const timer = window.setTimeout(() => dismiss(id), duration);
        timers.current.set(id, timer);
      }
      return id;
    },
    [dismiss],
  );

  // 卸载时清掉所有定时器
  useEffect(() => {
    const map = timers.current;
    return () => {
      map.forEach((t) => window.clearTimeout(t));
      map.clear();
    };
  }, []);

  const value = useMemo(() => ({ push, dismiss }), [push, dismiss]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-stack" role="status" aria-live="polite">
        {items.map((t) => (
          <ToastCard key={t.id} toast={t} onDismiss={dismiss} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function ToastCard({
  toast,
  onDismiss,
}: {
  toast: ToastItem;
  onDismiss: (id: number) => void;
}) {
  const { id, kind, message, action } = toast;

  return (
    <div className={`toast toast--${kind}`}>
      <span className="toast__glyph" aria-hidden="true">
        {kind === "success" ? "✓" : kind === "error" ? "!" : kind === "pending" ? "·" : "i"}
      </span>
      <span className="toast__message">{message}</span>
      {action ? (
        <button
          type="button"
          className="toast__action"
          onClick={() => {
            action.onClick();
            onDismiss(id);
          }}
        >
          {action.label}
        </button>
      ) : null}
      <button
        type="button"
        className="toast__close"
        onClick={() => onDismiss(id)}
        aria-label="关闭提示"
      >
        ×
      </button>
    </div>
  );
}

/** 使用 toast：const toast = useToast(); toast.success("已保存") */
export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast 必须在 ToastProvider 内使用");

  return useMemo(
    () => ({
      success: (message: string, action?: ToastAction) =>
        ctx.push({ kind: "success", message, action }),
      error: (message: string, action?: ToastAction) =>
        ctx.push({ kind: "error", message, action, duration: 5000 }),
      info: (message: string, action?: ToastAction) =>
        ctx.push({ kind: "info", message, action }),
      pending: (message: string) =>
        ctx.push({ kind: "pending", message, duration: 0 }),
      /** 删除可撤销：5s 内可点"撤销" */
      undo: (message: string, onUndo: () => void) =>
        ctx.push({
          kind: "info",
          message,
          action: { label: "撤销", onClick: onUndo },
          duration: 5000,
        }),
      dismiss: ctx.dismiss,
    }),
    [ctx],
  );
}
