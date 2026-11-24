/**
 * Refine.tsx — 提炼批次（写稿 › 提炼批次）
 *
 * 这一页只有一件事：项目。
 *
 * 为什么只剩项目：
 *   原来这里分四块——项目、提炼首页、结构模板、创作 Skill。实际用下来，
 *   「提炼首页」按主题挑片子，和项目里按项目挑片子是同一件事的两种切法，
 *   两处都要维护勾选和用途，反而分不清东西存哪了；结构模板和创作 Skill
 *   是看结果的地方，不是做事的地方。
 *   现在收敛成一条线：素材页存进某个项目 → 在项目里勾几篇 → 提炼 → 写法
 *   自动进写稿时该用的那一档。项目就是唯一的入口。
 *
 * 路由：/write/batches（老地址 /refine、/refine/projects 会重定向到这儿）。
 */

import PageHeader from "../components/PageHeader";
import Projects from "./Projects";
import "./Refine.css";

export default function Refine() {
  return (
    <div className="rf">
      <PageHeader
        title="提炼批次"
        subtitle="一个项目一批素材。勾几篇正文够长的，提炼成你自己能反复用的写法；写稿时挑一批带进去。"
      />
      <Projects />
    </div>
  );
}
