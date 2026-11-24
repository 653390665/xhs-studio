/**
 * Button.tsx — 统一按钮
 *
 * 反馈规范（BRIEF 第 4 节 #1 #2）：
 * - 按压：:active scale(0.98)，80ms
 * - loading：宽度不变，文字淡出 + 内联 spinner 淡入（不跳版）
 */

import type { ButtonHTMLAttributes, ReactNode } from "react";
import "./Button.css";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  leading?: ReactNode;
  children: ReactNode;
}

export default function Button({
  variant = "secondary",
  size = "md",
  loading = false,
  leading,
  children,
  className = "",
  disabled,
  ...rest
}: ButtonProps) {
  const classes = [
    "btn",
    `btn--${variant}`,
    `btn--${size}`,
    loading ? "is-loading" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button
      {...rest}
      className={classes}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
    >
      {/* 内容层：loading 时淡出但保留尺寸，避免按钮宽度跳动 */}
      <span className="btn__content">
        {leading ? <span className="btn__leading">{leading}</span> : null}
        {children}
      </span>
      <span className="btn__spinner" aria-hidden="true">
        <span className="btn__spinner-ring" />
      </span>
    </button>
  );
}
