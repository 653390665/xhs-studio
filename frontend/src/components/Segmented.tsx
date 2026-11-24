/**
 * Segmented.tsx — 胶囊式分段切换
 *
 * 为什么需要第三种切换控件：
 *   外壳顶部已经有一条「板块内子页」的下划线导航（SectionNav）。
 *   如果页面里再用同款下划线 Tabs，屏幕上会出现两条长得一样的横线，
 *   用户分不清哪条控制什么。分段控件形状不同、贴在内容里，
 *   一眼就能看出「这是这一页内部的分类」，不是再去别的页。
 *
 * 只负责显示与回调；选中态由调用方给，不自己存状态。
 */

import "./Segmented.css";

export interface SegmentedItem {
  key: string;
  label: string;
  count?: number;
}

export default function Segmented({
  items,
  active,
  onChange,
  ariaLabel,
}: {
  items: SegmentedItem[];
  active: string;
  onChange: (key: string) => void;
  ariaLabel?: string;
}) {
  return (
    <div className="seg" role="tablist" aria-label={ariaLabel ?? "分类"}>
      {items.map((item) => {
        const isActive = item.key === active;
        return (
          <button
            key={item.key}
            type="button"
            role="tab"
            aria-selected={isActive}
            className={`seg__item${isActive ? " is-active" : ""}`}
            onClick={() => {
              if (!isActive) onChange(item.key);
            }}
          >
            {item.label}
            {typeof item.count === "number" ? (
              <span className="seg__count">{item.count}</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
