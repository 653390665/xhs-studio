/**
 * Stat.tsx — 统计数字（带滚动）
 *
 * 规范（BRIEF 第 4 节 #5）：数字变化时 200ms 滚动，tabular-nums，
 * 只用 transform，不用 JS 逐帧。
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import "./Stat.css";

export interface StatProps {
  label: string;
  value: ReactNode;
  /** 单位或后缀，如"条" */
  unit?: string;
  /** 变化时的语义色 */
  tone?: "default" | "ok" | "warn" | "danger";
  hint?: string;
}

export function Stat({ label, value, unit, tone = "default", hint }: StatProps) {
  return (
    <div className={`stat stat--${tone}`}>
      <span className="stat__label">{label}</span>
      <span className="stat__value-row">
        <span className="stat__value">{value}</span>
        {unit ? <span className="stat__unit">{unit}</span> : null}
      </span>
      {hint ? <span className="stat__hint">{hint}</span> : null}
    </div>
  );
}

/** 数字滚动：变化时向上推进一格 */
export function RollNumber({ value }: { value: number }) {
  const prev = useRef(value);
  const [direction, setDirection] = useState<"up" | "down" | "none">("none");
  const [display, setDisplay] = useState(value);

  useEffect(() => {
    if (value === prev.current) return;
    setDirection(value > prev.current ? "up" : "down");
    // 等位移动画走完再换成新值（200ms）
    const timer = window.setTimeout(() => {
      setDisplay(value);
      setDirection("none");
      prev.current = value;
    }, 200);
    return () => window.clearTimeout(timer);
  }, [value]);

  return (
    <span
      className={`roll${direction !== "none" ? ` roll--${direction}` : ""}`}
      aria-live="polite"
    >
      {display}
    </span>
  );
}

/** 统计条：横排多个 Stat，栏线分隔 */
export function StatRow({ children }: { children: React.ReactNode }) {
  return <div className="stat-row">{children}</div>;
}
