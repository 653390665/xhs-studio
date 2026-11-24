/**
 * Drawer.tsx — 右侧抽屉外壳
 *
 * 从素材页抽出来的。素材页和项目页都要"点一张卡，右边滑出一篇原文"，
 * 各写一份的话，遮罩层、Esc、焦点、滚轮锁定迟早会分叉。
 */

import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import "./Drawer.css";

export default function Drawer({
  open,
  title,
  onClose,
  children,
  footer,
  width,
  escGuard = false,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
  width?: number;
  /** 抽屉里的子层（比如看图）开着时，Esc 先归它，不要连抽屉一起关掉 */
  escGuard?: boolean;
}) {
  const panel = useRef<HTMLDivElement | null>(null);
  const guard = useRef(escGuard);
  guard.current = escGuard;

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !guard.current) onClose();
    };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    panel.current?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);

  if (!open) return null;

  /*
   * 挂到 body 上。
   * 页面本身带进入动画（transform），一旦祖先有 transform，
   * position: fixed 就会以那个祖先为参照系，抽屉会被撑成整页高、跟着内容滚，
   * 而不是贴着视口。portal 出去才真的是"浮在最上面一层"。
   */
  return createPortal(
    <div
      className="mat-dr"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="mat-dr__panel"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        ref={panel}
        style={width ? { width } : undefined}
      >
        <div className="mat-dr__bar">
          <h2 className="mat-dr__title">{title}</h2>
          <button
            type="button"
            className="mat-dr__x"
            onClick={onClose}
            aria-label="关闭"
          >
            ×
          </button>
        </div>
        <div className="mat-dr__body">{children}</div>
        {footer ? <div className="mat-dr__foot">{footer}</div> : null}
      </div>
    </div>,
    document.body,
  );
}
