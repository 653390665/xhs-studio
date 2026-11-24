/**
 * Skeleton.tsx — 骨架屏
 *
 * 规范（BRIEF 第 4 节 #3）：与真实布局同构的灰块，shimmer 2s 循环，
 * prefers-reduced-motion 下静态。绝不用转圈占位。
 */

import "./Skeleton.css";

export interface SkeletonProps {
  width?: number | string;
  height?: number | string;
  /** 圆角档：text 用于单行文字，block 用于卡片，circle 用于头像 */
  shape?: "text" | "block" | "circle";
  className?: string;
}

export function Skeleton({
  width = "100%",
  height = 12,
  shape = "text",
  className = "",
}: SkeletonProps) {
  return (
    <span
      className={`skel skel--${shape} ${className}`.trim()}
      style={{ width, height }}
      aria-hidden="true"
    />
  );
}

/** 列表骨架：n 行，与真实列表行同高 */
export function SkeletonList({ rows = 5 }: { rows?: number }) {
  return (
    <div className="skel-list" role="status" aria-label="正在加载">
      {Array.from({ length: rows }).map((_, i) => (
        <div className="skel-list__row" key={i}>
          <Skeleton width={28} height={28} shape="circle" />
          <div className="skel-list__body">
            <Skeleton width={`${58 + ((i * 13) % 30)}%`} height={13} />
            <Skeleton width={`${34 + ((i * 7) % 22)}%`} height={11} />
          </div>
          <Skeleton width={54} height={11} />
        </div>
      ))}
    </div>
  );
}

/** 统计卡骨架 */
export function SkeletonStats({ count = 4 }: { count?: number }) {
  return (
    <div className="skel-stats" role="status" aria-label="正在加载">
      {Array.from({ length: count }).map((_, i) => (
        <div className="skel-stats__cell" key={i}>
          <Skeleton width={48} height={10} />
          <Skeleton width={72} height={24} />
        </div>
      ))}
    </div>
  );
}
