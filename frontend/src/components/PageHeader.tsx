/**
 * PageHeader.tsx — 页头
 * 40px 标题 + 一句话副标 + 右侧动作区（BRIEF 第 3 节布局）
 */

import type { ReactNode } from "react";
import "./PageHeader.css";

export interface PageHeaderProps {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  /** 标题右侧的极小号状态标记，如"演示数据" */
  tag?: ReactNode;
}

export default function PageHeader({
  title,
  subtitle,
  actions,
  tag,
}: PageHeaderProps) {
  return (
    <header className="ph">
      <div className="ph__main">
        <div className="ph__title-row">
          <h1 className="ph__title">{title}</h1>
          {tag ? <span className="ph__tag">{tag}</span> : null}
        </div>
        {subtitle ? <p className="ph__subtitle">{subtitle}</p> : null}
      </div>
      {actions ? <div className="ph__actions">{actions}</div> : null}
    </header>
  );
}
