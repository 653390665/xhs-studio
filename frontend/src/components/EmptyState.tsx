/**
 * EmptyState.tsx — 空状态
 *
 * 规范（BRIEF 第 4 节 #9）：CSS 画的简单几何插图 + 一句话说明 + 一个明确主行动。
 * 不用 emoji 堆砌，不写"暂无数据"就完事。
 */

import type { ReactNode } from "react";
import "./EmptyState.css";

export type EmptyGlyph = "stack" | "spark" | "calendar" | "flow" | "search";

export interface EmptyStateProps {
  glyph?: EmptyGlyph;
  title: string;
  /** 说清楚这个页面是干什么的，以及为什么现在是空的 */
  description?: string;
  action?: ReactNode;
  /** 次级内容，如意向提示、示例 */
  extra?: ReactNode;
  compact?: boolean;
}

export default function EmptyState({
  title,
  description,
  action,
  extra,
  compact = false,
}: EmptyStateProps) {
  return (
    <div className={`empty${compact ? " empty--compact" : ""}`}>
      {/*
        这里原来渲染几何插图（三张叠纸 / 流程点 / 放大镜）。
        实测：44px 的框里塞三个 32×26 的描边方块，错位只有 6px，
        叠在一起就是个空格子，看起来像"组件没加载出来"。
        极简取舍：去掉插图，标题和按钮自己说话，反而更清楚。
        glyph prop 保留只是为了不改动调用方。
      */}
      <h2 className="empty__title">{title}</h2>
      {description ? <p className="empty__desc">{description}</p> : null}
      {action ? <div className="empty__action">{action}</div> : null}
      {extra ? <div className="empty__extra">{extra}</div> : null}
    </div>
  );
}
