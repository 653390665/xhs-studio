/**
 * Modal.tsx — 居中弹窗（表单类）
 *
 * 和 ConfirmDialog 的区别：那个只问一句话、两个按钮；
 * 这个要装一个有几行的表单，所以更宽、有标题栏、有页脚。
 *
 * 规范要点（查过主流做法，见下）：
 *   - 宽度上限 560px。Material / Home Assistant / Mirakl 三家都说表单类弹窗
 *     不超过 ~560，字段不超过 5 个；再复杂就该给它一个整页。
 *   - 遮罩点击关闭、Esc 关闭、焦点陷阱、关闭后焦点归位。
 *   - 打开时焦点落在第一个输入框（不是取消按钮——这是新建表单，不是危险确认）。
 *   - 底部按钮固定：左取消、右确认，确认按钮写明动作（「建」而不是「确定」）。
 */

import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import type { ReactNode } from "react";
import "./Modal.css";

export interface ModalProps {
  open: boolean;
  title: string;
  /** 一句话说清这个弹窗是干嘛的，放在标题下面 */
  hint?: string;
  /** 页脚左侧的补充说明，比如「建完就能在素材页选它」 */
  footNote?: ReactNode;
  children: ReactNode;
  footer: ReactNode;
  /** 内容区最大宽度，默认 560 */
  width?: number;
  onClose: () => void;
}

export default function Modal({
  open,
  title,
  hint,
  footNote,
  children,
  footer,
  width = 560,
  onClose,
}: ModalProps) {
  const panel = useRef<HTMLDivElement | null>(null);
  const lastFocused = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;

    lastFocused.current = document.activeElement as HTMLElement | null;

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key !== "Tab") return;

      const root = panel.current;
      if (!root) return;
      const items = root.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (items.length === 0) return;

      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKey);

    /* 焦点落在第一个可输入的地方，用户进来就能打字 */
    const field = panel.current?.querySelector<HTMLElement>(
      "[data-autofocus], input:not([disabled])",
    );
    field?.focus();

    /* 弹窗后面那层不要跟着滚 */
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
      lastFocused.current?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;

  /*
   * 挂到 body 上，不留在页面容器里：
   * 外壳的切页动画带 transform，会把它变成 fixed 的包含块，
   * 遮罩就只盖住内容区、盖不住侧栏，看着像"弹窗漏了一块"。
   */
  return createPortal(
    <div
      className="mdd-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="mdd"
        style={{ maxWidth: width }}
        role="dialog"
        aria-modal="true"
        aria-labelledby="mdd-title"
        ref={panel}
      >
        <header className="mdd__head">
          <h2 className="mdd__title" id="mdd-title">
            {title}
          </h2>
          {hint ? <p className="mdd__hint">{hint}</p> : null}
          <button
            type="button"
            className="mdd__x"
            onClick={onClose}
            aria-label="关闭"
          >
            ×
          </button>
        </header>

        <div className="mdd__body">{children}</div>

        <footer className="mdd__foot">
          <span className="mdd__note">{footNote}</span>
          <span className="mdd__acts">{footer}</span>
        </footer>
      </div>
    </div>,
    document.body,
  );
}
