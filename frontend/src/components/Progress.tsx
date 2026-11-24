/**
 * Progress.tsx — 进度反馈
 *
 * 规范（BRIEF 第 4 节 #11）：
 * - 顶部 2px 细线，不确定进度时往复扫光；确定进度时线性填充
 * - 长任务用 TaskProgress：阶段文案 + 可取消，绝不假进度
 */

import type { ReactNode } from "react";
import "./Progress.css";

export interface TopProgressProps {
  /** 是否显示；不确定进度就传 true */
  active: boolean;
}

/** 顶部细进度条（页面级） */
export function TopProgress({ active }: TopProgressProps) {
  return (
    <div className="tp" data-on={active ? "1" : "0"} aria-hidden="true">
      <span className="tp__bar" />
    </div>
  );
}

export interface TaskProgressProps {
  /** 0-100；传 undefined 表示不确定进度 */
  percent?: number;
  /** 当前阶段文案，如"正在采集第 3 页" */
  stage: string;
  /** 补充说明 */
  detail?: string;
  onCancel?: () => void;
  cancelLabel?: string;
  extra?: ReactNode;
}

/** 任务进度：阶段 + 可取消 */
export function TaskProgress({
  percent,
  stage,
  detail,
  onCancel,
  cancelLabel = "取消",
  extra,
}: TaskProgressProps) {
  const indeterminate = typeof percent !== "number";

  return (
    <div className="taskp" role="status" aria-live="polite">
      <div className="taskp__head">
        <span className="taskp__stage">{stage}</span>
        {indeterminate ? null : (
          <span className="taskp__percent">{Math.round(percent)}%</span>
        )}
      </div>

      <div className="taskp__track">
        {indeterminate ? (
          <span className="taskp__sweep" />
        ) : (
          <span
            className="taskp__fill"
            style={{ transform: `scaleX(${Math.min(Math.max(percent, 0), 100) / 100})` }}
          />
        )}
      </div>

      {detail ? <p className="taskp__detail">{detail}</p> : null}
      {extra}

      {onCancel ? (
        <button type="button" className="taskp__cancel" onClick={onCancel}>
          {cancelLabel}
        </button>
      ) : null}
    </div>
  );
}

/**
 * 覆盖率条：提炼页专用（证据规则覆盖率 ≥80% 才注入）
 */
export function CoverageBar({
  percent,
  threshold = 80,
  label,
}: {
  percent: number;
  threshold?: number;
  label?: string;
}) {
  const passed = percent >= threshold;
  return (
    <div className="cov">
      <div className="cov__head">
        <span className="cov__label">{label ?? "覆盖率"}</span>
        <span className={`cov__value${passed ? " is-pass" : ""}`}>
          {Math.round(percent)}%
        </span>
      </div>
      <div className="cov__track">
        <span
          className={`cov__fill${passed ? " is-pass" : ""}`}
          style={{ width: `${Math.min(Math.max(percent, 0), 100)}%` }}
        />
        {/* 阈值刻度：让"够不够"一眼可见 */}
        <span className="cov__threshold" style={{ left: `${threshold}%` }} />
      </div>
      <span className="cov__note">
        {passed ? `达到 ${threshold}% 阈值，可注入生成要求` : `未达 ${threshold}%，只记录不注入`}
      </span>
    </div>
  );
}
