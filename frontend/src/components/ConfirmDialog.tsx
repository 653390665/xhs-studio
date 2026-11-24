/**
 * ConfirmDialog.tsx — 危险动作确认
 *
 * 规范（BRIEF 第 4 节 #12）：用于发布等不可逆动作；
 * 背景 backdrop-filter: blur(2px) 200ms；危险按钮用危险色。
 * 带焦点陷阱、Esc 关闭、焦点归位。
 */

import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import type { ReactNode } from "react";
import Button from "./Button";
import "./ConfirmDialog.css";

export interface ConfirmDialogProps {
  open: boolean;
  title: string;
  /** 说清这一步到底会发生什么，不要含糊 */
  description?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  loading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  children?: ReactNode;
}

export default function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "确认",
  cancelLabel = "取消",
  danger = false,
  loading = false,
  onConfirm,
  onCancel,
  children,
}: ConfirmDialogProps) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const lastFocused = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;

    lastFocused.current = document.activeElement as HTMLElement | null;

    // 焦点陷阱：Tab 循环在对话框内
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onCancel();
        return;
      }
      if (e.key !== "Tab") return;

      const root = dialogRef.current;
      if (!root) return;
      const focusables = root.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (focusables.length === 0) return;

      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const activeEl = document.activeElement;

      if (e.shiftKey && activeEl === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && activeEl === last) {
        e.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);

    // 初始焦点：取消按钮优先（避免误按回车执行危险动作）
    const cancelBtn = dialogRef.current?.querySelector<HTMLElement>(
      "[data-autofocus]",
    );
    cancelBtn?.focus();

    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      lastFocused.current?.focus();
    };
  }, [open, onCancel]);

  if (!open) return null;

  /* 挂到 body：外壳的切页动画带 transform，会把 fixed 的包含块换成内容区，
     遮罩就盖不住侧栏了 */
  return createPortal(
    <div
      className="cd-overlay"
      onMouseDown={(e) => {
        // 只有点在遮罩本身（不是内容）才关闭
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div
        className="cd"
        role="dialog"
        aria-modal="true"
        aria-labelledby="cd-title"
        ref={dialogRef}
      >
        <h2 className="cd__title" id="cd-title">
          {title}
        </h2>
        {description ? <div className="cd__desc">{description}</div> : null}
        {children ? <div className="cd__body">{children}</div> : null}
        <div className="cd__actions">
          <Button variant="ghost" onClick={onCancel} data-autofocus>
            {cancelLabel}
          </Button>
          <Button
            variant={danger ? "danger" : "primary"}
            onClick={onConfirm}
            loading={loading}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
