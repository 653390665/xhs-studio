import { Spin } from "antd";
import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "../components/layout/app-shell";
import { AssetSectionShell } from "../components/layout/asset-section-shell";
import { SectionShell } from "../components/layout/section-shell";
import { ProtectedRoute, PublicOnlyRoute } from "../components/ui/protected-route";
import {
  DASHBOARD_TABS,
  PUBLISH_TABS,
  REFINE_TABS,
  SETTINGS_TABS,
  WRITE_TABS,
} from "./navigation";

/**
 * Pages are split into separate chunks: the first paint only ships the shell,
 * login and platform picker instead of every Xhs page.
 */
const LoginPage = lazy(() =>
  import("../pages/login/login-page").then((module) => ({ default: module.LoginPage })),
);
const ModelConfigPage = lazy(() =>
  import("../pages/models/model-config-page").then((module) => ({ default: module.ModelConfigPage })),
);
const PlatformSelectPage = lazy(() =>
  import("../pages/platform-select/platform-select-page").then((module) => ({
    default: module.PlatformSelectPage,
  })),
);
const SettingsPage = lazy(() =>
  import("../pages/settings/settings-page").then((module) => ({ default: module.SettingsPage })),
);
const SettingsRiskPage = lazy(() =>
  import("../pages/settings/settings-page").then((module) => ({ default: module.SettingsRiskPage })),
);
const TaskCenterPage = lazy(() =>
  import("../pages/tasks/task-center-page").then((module) => ({ default: module.TaskCenterPage })),
);
const XhsAccountsPage = lazy(() =>
  import("../pages/platforms/xhs/accounts-page").then((module) => ({ default: module.XhsAccountsPage })),
);
const StudioBatchPage = lazy(() =>
  import("../pages/platforms/xhs/studio-batch-page").then((module) => ({
    default: module.StudioBatchPage,
  })),
);
const XhsAnalyticsPage = lazy(() =>
  import("../pages/platforms/xhs/analytics-page").then((module) => ({
    default: module.XhsAnalyticsPage,
  })),
);
const XhsCardStudioPage = lazy(() =>
  import("../pages/platforms/xhs/card-studio-page").then((module) => ({
    default: module.XhsCardStudioPage,
  })),
);
const ContentCalendarPage = lazy(() =>
  import("../pages/platforms/xhs/content-calendar-page").then((module) => ({
    default: module.ContentCalendarPage,
  })),
);
const XhsTemplatesPage = lazy(() =>
  import("../pages/platforms/xhs/templates-page").then((module) => ({
    default: module.XhsTemplatesPage,
  })),
);
const TopicBankPage = lazy(() =>
  import("../pages/platforms/xhs/topic-bank-page").then((module) => ({
    default: module.TopicBankPage,
  })),
);
const XhsTrendsPage = lazy(() =>
  import("../pages/platforms/xhs/trends-page").then((module) => ({ default: module.XhsTrendsPage })),
);
const XhsDashboard = lazy(() =>
  import("../pages/platforms/xhs/xhs-dashboard").then((module) => ({ default: module.XhsDashboard })),
);
const ResearchHomePage = lazy(() =>
  import("../pages/platforms/xhs/research-home-page").then((module) => ({
    default: module.ResearchHomePage,
  })),
);
const ResearchCollectPage = lazy(() =>
  import("../pages/platforms/xhs/research-collect-page").then((module) => ({
    default: module.ResearchCollectPage,
  })),
);
const ResearchAnalysisPage = lazy(() =>
  import("../pages/platforms/xhs/research-analysis-page").then((module) => ({
    default: module.ResearchAnalysisPage,
  })),
);
const XhsDraftsPage = lazy(() =>
  import("../pages/platforms/xhs/rewrite-page").then((module) => ({ default: module.XhsDraftsPage })),
);
const XhsKeywordsPage = lazy(() =>
  import("../pages/platforms/xhs/keywords-page").then((module) => ({ default: module.XhsKeywordsPage })),
);
const XhsLibraryPage = lazy(() =>
  import("../pages/platforms/xhs/library-page").then((module) => ({ default: module.XhsLibraryPage })),
);
const XhsImageStudioPage = lazy(() =>
  import("../pages/platforms/xhs/image-studio-page").then((module) => ({
    default: module.XhsImageStudioPage,
  })),
);
const XhsPublishPage = lazy(() =>
  import("../pages/platforms/xhs/publish-page").then((module) => ({ default: module.XhsPublishPage })),
);
const XhsSkillPage = lazy(() =>
  import("../pages/platforms/xhs/skill-page").then((module) => ({ default: module.XhsSkillPage })),
);
const XhsVideoStudioPage = lazy(() =>
  import("../pages/platforms/xhs/video-studio-page").then((module) => ({
    default: module.XhsVideoStudioPage,
  })),
);
const RefinePage = lazy(() =>
  import("../pages/platforms/xhs/refine-page").then((module) => ({ default: module.RefinePage })),
);
const XhsSectionPage = lazy(() =>
  import("../pages/platforms/xhs/xhs-section-page").then((module) => ({ default: module.XhsSectionPage })),
);
const XhsAgentPage = lazy(() =>
  import("../pages/platforms/xhs/agent-page").then((module) => ({ default: module.XhsAgentPage })),
);
const DouyinExtractPage = lazy(() =>
  import("../pages/platforms/xhs/douyin-extract-page").then((module) => ({
    default: module.DouyinExtractPage,
  })),
);
const DouyinBenchmarkPage = lazy(() =>
  import("../pages/platforms/xhs/douyin-benchmark-page").then((module) => ({
    default: module.DouyinBenchmarkPage,
  })),
);

/**
 * 信息架构（2026-10 最终版）：
 * 一级导航按「信息流向」排，不按功能性质排。
 *
 *   总览（今日+复盘）→ 素材（找输入）→ 计划（写什么）→ 提炼（怎么写）
 *   → 写稿（产出）→ 发布（执行）
 *
 * 三条关键约束：
 * 1. 素材只放「向外看」的输入，复盘只放自己的表现。
 * 2. 提炼只放「怎么写」：画像、结构模板、创作 Skill。选题属于「写什么」，在选题区。
 * 3. 账号凭证属于基础设施，进设置；画像进提炼，因为它是 Skill 的输入。
 */
// Navigation arrays live in ./navigation so the shell and router cannot drift.

/** 旧链接可能带 ?keyword=，重定向时不要丢掉查询参数。 */
function RedirectKeepingQuery({ to }: { to: string }) {
  return <Navigate to={`${to}${window.location.search}`} replace />;
}

function RouteLoading({ fullPage = false }: { fullPage?: boolean }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        minHeight: fullPage ? "100vh" : 240,
      }}
    >
      <Spin size="large" />
    </div>
  );
}

export function AppRouter() {
  return (
    <BrowserRouter>
      <Suspense fallback={<RouteLoading fullPage />}>
        <Routes>
        <Route path="/" element={<Navigate to="/platform-select" replace />} />
        <Route
          path="/login"
          element={
            <PublicOnlyRoute>
              <LoginPage />
            </PublicOnlyRoute>
          }
        />
        <Route
          path="/platform-select"
          element={
            <ProtectedRoute>
              <PlatformSelectPage />
            </ProtectedRoute>
          }
        />
        <Route path="/platforms/xhs" element={<Navigate to="/platforms/xhs/dashboard" replace />} />
        {/* Only XHS has a product surface today. Old bookmarks for other
            platforms should land on the usable workspace, not a dead
            "Coming Soon" page. */}
        <Route
          path="/platforms/:platformId/*"
          element={<Navigate to="/platforms/xhs/dashboard" replace />}
        />
        <Route
          element={
            <ProtectedRoute>
              <AppShell />
            </ProtectedRoute>
          }
        >
          {/* 总览：今日决策 + 复盘分析 + 自己的笔记 */}
          <Route path="/platforms/xhs/dashboard" element={<SectionShell tabs={DASHBOARD_TABS} />}>
            <Route index element={<XhsDashboard />} />
            <Route path="review" element={<XhsAnalyticsPage />} />
            <Route path="notes" element={<XhsLibraryPage fixedSource="own" />} />
          </Route>
          <Route path="/agent" element={<XhsAgentPage />} />

          {/* 素材：一切「向外看」的输入 */}
          <Route path="/platforms/xhs/assets" element={<AssetSectionShell />}>
            <Route index element={<ResearchHomePage />} />
            <Route path="library" element={<XhsLibraryPage fixedSource="library" />} />
            <Route path="own" element={<RedirectKeepingQuery to="/platforms/xhs/dashboard/notes" />} />
            <Route path="collect" element={<ResearchCollectPage />} />
            <Route path="search" element={<RedirectKeepingQuery to="/platforms/xhs/assets/collect" />} />
            <Route path="crawler" element={<Navigate to="/platforms/xhs/assets/collect?mode=crawler" replace />} />
            <Route path="keywords" element={<XhsKeywordsPage />} />
            <Route path="trends" element={<XhsTrendsPage />} />
            <Route path="analysis" element={<ResearchAnalysisPage />} />
            <Route path="benchmarks" element={<Navigate to="/platforms/xhs/assets/analysis?tab=competitors" replace />} />
            <Route path="douyin" element={<DouyinExtractPage />} />
            <Route path="douyin-benchmark" element={<DouyinBenchmarkPage />} />
          </Route>

          {/* 计划：写什么。只保留选题库，排期统一去发布区 */}
          <Route path="/platforms/xhs/plan" element={<TopicBankPage />} />

          {/* 提炼：怎么写。画像 + 模板 + Skill */}
          <Route path="/platforms/xhs/refine" element={<SectionShell tabs={REFINE_TABS} />}>
            <Route index element={<RefinePage />} />
            <Route path="persona" element={<RedirectKeepingQuery to="/platforms/xhs/refine/skills" />} />
            <Route path="skills" element={<XhsSkillPage />} />
            <Route path="templates" element={<XhsTemplatesPage />} />
          </Route>

          {/* 写稿：草稿与配图 */}
          <Route path="/platforms/xhs/write" element={<SectionShell tabs={WRITE_TABS} />}>
            <Route index element={<Navigate to="drafts" replace />} />
            <Route path="drafts" element={<XhsDraftsPage />} />
            <Route path="batch" element={<StudioBatchPage />} />
            <Route path="visual">
              <Route index element={<Navigate to="images" replace />} />
              <Route path="images" element={<XhsImageStudioPage embedded />} />
              <Route path="cards" element={<XhsCardStudioPage embedded />} />
              <Route path="videos" element={<XhsVideoStudioPage embedded />} />
            </Route>
          </Route>

          <Route path="/platforms/xhs/publish-hub" element={<SectionShell tabs={PUBLISH_TABS} />}>
            <Route index element={<Navigate to="jobs" replace />} />
            <Route path="jobs" element={<XhsPublishPage />} />
            <Route path="calendar" element={<ContentCalendarPage />} />
            <Route path="auto" element={<Navigate to="/platforms/xhs/write/batch?mode=auto" replace />} />
          </Route>

          {/* 账号与复盘已并入别处，旧路径一律重定向 */}
          <Route path="/platforms/xhs/account" element={<Navigate to="/settings/accounts" replace />} />
          <Route path="/platforms/xhs/account/list" element={<RedirectKeepingQuery to="/settings/accounts" />} />
          <Route path="/platforms/xhs/account/persona" element={<RedirectKeepingQuery to="/platforms/xhs/refine/skills" />} />
          <Route path="/platforms/xhs/account/matrix" element={<Navigate to="/platforms/xhs/write/batch?mode=matrix" replace />} />
          <Route path="/platforms/xhs/account/report" element={<Navigate to="/platforms/xhs/assets/analysis?tab=report" replace />} />
          <Route path="/platforms/xhs/account/benchmarks" element={<Navigate to="/platforms/xhs/assets/analysis?tab=competitors" replace />} />
          <Route path="/platforms/xhs/review" element={<RedirectKeepingQuery to="/platforms/xhs/dashboard/review" />} />
          <Route path="/platforms/xhs/plan/timeline" element={<RedirectKeepingQuery to="/platforms/xhs/publish-hub/calendar" />} />
          <Route path="/platforms/xhs/review/published" element={<RedirectKeepingQuery to="/platforms/xhs/dashboard/notes" />} />
          <Route path="/platforms/xhs/refine/topics" element={<RedirectKeepingQuery to="/platforms/xhs/plan" />} />
          <Route path="/platforms/xhs/content/topics" element={<RedirectKeepingQuery to="/platforms/xhs/plan" />} />

          {/* ---- 旧路由兼容：全部重定向到新架构，保留查询参数 ---- */}
          <Route path="/platforms/xhs/discover" element={<RedirectKeepingQuery to="/platforms/xhs/assets" />} />
          <Route path="/platforms/xhs/discover/library" element={<RedirectKeepingQuery to="/platforms/xhs/assets/library" />} />
          <Route path="/platforms/xhs/discover/collect" element={<RedirectKeepingQuery to="/platforms/xhs/assets/collect" />} />
          <Route path="/platforms/xhs/discover/search" element={<RedirectKeepingQuery to="/platforms/xhs/assets/collect" />} />
          <Route path="/platforms/xhs/discover/crawler" element={<Navigate to="/platforms/xhs/assets/collect?mode=crawler" replace />} />
          <Route path="/platforms/xhs/discover/keywords" element={<RedirectKeepingQuery to="/platforms/xhs/assets/keywords" />} />
          <Route path="/platforms/xhs/discover/trends" element={<RedirectKeepingQuery to="/platforms/xhs/assets/trends" />} />
          <Route path="/platforms/xhs/discover/analysis" element={<RedirectKeepingQuery to="/platforms/xhs/assets/analysis" />} />
          <Route path="/platforms/xhs/discover/benchmarks" element={<Navigate to="/platforms/xhs/assets/analysis?tab=competitors" replace />} />
          <Route path="/platforms/xhs/discover/douyin" element={<RedirectKeepingQuery to="/platforms/xhs/assets/douyin" />} />
          <Route path="/platforms/xhs/content" element={<SectionShell tabs={REFINE_TABS} />}>
            <Route index element={<Navigate to="notes" replace />} />
            <Route path="notes" element={<RedirectKeepingQuery to="/platforms/xhs/dashboard/notes" />} />
            <Route path="templates" element={<RedirectKeepingQuery to="/platforms/xhs/refine/templates" />} />
            <Route path="topics" element={<RedirectKeepingQuery to="/platforms/xhs/plan" />} />
            <Route path="analytics" element={<RedirectKeepingQuery to="/platforms/xhs/dashboard/review" />} />
            <Route path="skills" element={<RedirectKeepingQuery to="/platforms/xhs/refine/skills" />} />
          </Route>
          <Route path="/platforms/xhs/studio" element={<SectionShell tabs={WRITE_TABS} />}>
            <Route index element={<Navigate to="drafts" replace />} />
            <Route path="drafts" element={<RedirectKeepingQuery to="/platforms/xhs/write/drafts" />} />
            <Route path="batch" element={<RedirectKeepingQuery to="/platforms/xhs/write/batch" />} />
            <Route path="visual" element={<RedirectKeepingQuery to="/platforms/xhs/write/visual" />} />
            <Route path="visual/images" element={<RedirectKeepingQuery to="/platforms/xhs/write/visual/images" />} />
            <Route path="visual/cards" element={<RedirectKeepingQuery to="/platforms/xhs/write/visual/cards" />} />
            <Route path="visual/videos" element={<RedirectKeepingQuery to="/platforms/xhs/write/visual/videos" />} />
            <Route path="assets" element={<Navigate to="/platforms/xhs/write/visual" replace />} />
            <Route path="assets/images" element={<Navigate to="/platforms/xhs/write/visual/images" replace />} />
            <Route path="assets/cards" element={<Navigate to="/platforms/xhs/write/visual/cards" replace />} />
            <Route path="videos" element={<Navigate to="/platforms/xhs/write/visual/videos" replace />} />
          </Route>
          <Route path="/platforms/xhs/discovery" element={<RedirectKeepingQuery to="/platforms/xhs/assets/collect" />} />
          <Route path="/platforms/xhs/crawler" element={<Navigate to="/platforms/xhs/assets/collect?mode=crawler" replace />} />
          <Route path="/platforms/xhs/keywords" element={<Navigate to="/platforms/xhs/assets/keywords" replace />} />
          <Route path="/platforms/xhs/trends" element={<Navigate to="/platforms/xhs/assets/trends" replace />} />
          <Route path="/platforms/xhs/accounts" element={<Navigate to="/settings/accounts" replace />} />
          <Route path="/platforms/xhs/rewrite" element={<RedirectKeepingQuery to="/platforms/xhs/write/drafts" />} />
          <Route path="/platforms/xhs/account-report" element={<Navigate to="/platforms/xhs/assets/analysis?tab=report" replace />} />
          <Route path="/platforms/xhs/benchmarks" element={<Navigate to="/platforms/xhs/assets/analysis?tab=competitors" replace />} />
          <Route path="/platforms/xhs/library" element={<RedirectKeepingQuery to="/platforms/xhs/assets/library" />} />
          <Route path="/platforms/xhs/templates" element={<Navigate to="/platforms/xhs/refine/templates" replace />} />
          <Route path="/platforms/xhs/analytics" element={<Navigate to="/platforms/xhs/dashboard/review" replace />} />
          <Route path="/platforms/xhs/drafts" element={<RedirectKeepingQuery to="/platforms/xhs/write/drafts" />} />
          <Route path="/platforms/xhs/card-studio" element={<Navigate to="/platforms/xhs/write/visual/cards" replace />} />
          <Route path="/platforms/xhs/image-studio" element={<Navigate to="/platforms/xhs/write/visual/images" replace />} />
          <Route path="/platforms/xhs/video-studio" element={<Navigate to="/platforms/xhs/write/visual/videos" replace />} />
          <Route path="/platforms/xhs/publish" element={<Navigate to="/platforms/xhs/publish-hub/jobs" replace />} />
          <Route path="/platforms/xhs/auto-ops" element={<Navigate to="/platforms/xhs/write/batch?mode=auto" replace />} />

          <Route path="/platforms/xhs/:section" element={<XhsSectionPage />} />

          <Route path="/settings" element={<SectionShell tabs={SETTINGS_TABS} />}>
            <Route index element={<Navigate to="sources" replace />} />
            <Route path="sources" element={<SettingsPage />} />
            <Route path="accounts" element={<XhsAccountsPage />} />
            <Route path="models" element={<ModelConfigPage />} />
            <Route path="risk" element={<SettingsRiskPage />} />
            <Route path="tasks" element={<TaskCenterPage />} />
            <Route path="general" element={<Navigate to="/settings/sources" replace />} />
          </Route>
          <Route path="/models" element={<Navigate to="/settings/models" replace />} />
          <Route path="/tasks" element={<Navigate to="/settings/tasks" replace />} />
        </Route>
      </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
