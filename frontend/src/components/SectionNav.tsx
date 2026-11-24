/**
 * SectionNav.tsx — 板块内的子页切换条
 *
 * 为什么放在外壳层而不是每个页面自己画：
 *   老前端每个页面各写一份 Tabs，路径写死在页面里，外壳又维护一套导航，
 *   两处各改一次就出现「侧栏能点、子标签还是老路径」。现在子页只在
 *   src/app/navigation.ts 声明一次，这里按当前路径渲染。
 *
 * 视觉上刻意和页面内的 Tabs 区分：这是「换板块内的哪一页」，
 * 排在内容区最上面、字号更小、贴边，不跟页面标题抢层级。
 */

import { useLocation, useNavigate } from "react-router-dom";
import { sectionOf, tabOf } from "../app/navigation";
import "./SectionNav.css";

export default function SectionNav() {
  const location = useLocation();
  const navigate = useNavigate();

  const section = sectionOf(location.pathname);
  if (!section || section.tabs.length < 2) return null;

  const active = tabOf(section, location.pathname);

  return (
    <nav className="snav" aria-label={`${section.label}子页`}>
      <span className="snav__section">{section.label}</span>
      <div className="snav__list" role="tablist">
        {section.tabs.map((tab) => {
          const isActive = active?.key === tab.key;
          return (
            <button
              key={tab.key}
              type="button"
              role="tab"
              aria-selected={isActive}
              className={`snav__tab${isActive ? " is-active" : ""}`}
              onClick={() => {
                if (!isActive) navigate(tab.path);
              }}
            >
              {tab.label}
            </button>
          );
        })}
      </div>
    </nav>
  );
}
