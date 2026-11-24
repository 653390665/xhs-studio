/**
 * Single source of truth for the app's navigation.
 *
 * Routes used to define their own tab arrays; the publish section's timeline
 * tab then pointed at the plan route and its calendar route became unreachable.
 * Keep the labels and keys here, and let both the router and the shell read them.
 */

export type SectionTab = {
  key: string;
  label: string;
  /** Draw a separator before this tab to show a workflow group boundary. */
  groupStart?: boolean;
  /** Optional second-level tabs rendered directly under this tab. */
  children?: SectionTab[];
};

/**
 * Asset top-level tabs. 洞察 is flattened into peers; only 采集 keeps a
 * second row because it has two genuinely different crawlers.
 */
export const ASSET_TOP_TABS: SectionTab[] = [
  { key: "/platforms/xhs/assets", label: "总览" },
  {
    key: "/platforms/xhs/assets/collect",
    label: "采集",
    children: [
      { key: "/platforms/xhs/assets/collect", label: "小红书采集" },
      { key: "/platforms/xhs/assets/douyin", label: "抖音口播提取" },
    ],
  },
  { key: "/platforms/xhs/assets/library", label: "样本库" },
  { key: "/platforms/xhs/assets/keywords", label: "热词追踪" },
  { key: "/platforms/xhs/assets/trends", label: "榜单趋势" },
  { key: "/platforms/xhs/assets/analysis", label: "对标分析" },
  { key: "/platforms/xhs/assets/douyin-benchmark", label: "抖音对标" },
];

export const REFINE_TABS: SectionTab[] = [
  { key: "/platforms/xhs/refine", label: "提炼首页" },
  { key: "/platforms/xhs/refine/templates", label: "结构模板" },
  { key: "/platforms/xhs/refine/skills", label: "创作 Skill" },
];

export const VISUAL_TABS: SectionTab[] = [
  { key: "/platforms/xhs/write/visual/images", label: "图片素材" },
  { key: "/platforms/xhs/write/visual/cards", label: "卡片" },
  { key: "/platforms/xhs/write/visual/videos", label: "视频素材" },
];

export const WRITE_TABS: SectionTab[] = [
  { key: "/platforms/xhs/write/drafts", label: "草稿工坊" },
  { key: "/platforms/xhs/write/batch", label: "批量生成" },
  {
    key: "/platforms/xhs/write/visual",
    label: "视觉素材",
    children: VISUAL_TABS,
  },
];

export const DASHBOARD_TABS: SectionTab[] = [
  { key: "/platforms/xhs/dashboard", label: "今日" },
  { key: "/platforms/xhs/dashboard/review", label: "复盘" },
  { key: "/platforms/xhs/dashboard/notes", label: "我的笔记" },
];

export const PUBLISH_TABS: SectionTab[] = [
  { key: "/platforms/xhs/publish-hub/jobs", label: "发布队列" },
  { key: "/platforms/xhs/publish-hub/calendar", label: "发布排期" },
];

export const SETTINGS_TABS: SectionTab[] = [
  { key: "/settings/sources", label: "数据源" },
  { key: "/settings/accounts", label: "账号" },
  { key: "/settings/models", label: "模型" },
  { key: "/settings/risk", label: "风险控制" },
  { key: "/settings/tasks", label: "运行记录" },
];

export type NavIconKey =
  | "dashboard"
  | "assets"
  | "plan"
  | "refine"
  | "write"
  | "publish"
  | "agent"
  | "settings";

export type NavSection = {
  key: string;
  label: string;
  icon: NavIconKey;
  tabs: SectionTab[];
};

export const NAV_SECTIONS: NavSection[] = [
  { key: "/platforms/xhs/dashboard", label: "总览", icon: "dashboard", tabs: DASHBOARD_TABS },
  { key: "/platforms/xhs/assets", label: "素材", icon: "assets", tabs: ASSET_TOP_TABS },
  { key: "/platforms/xhs/plan", label: "选题", icon: "plan", tabs: [] },
  { key: "/platforms/xhs/refine", label: "提炼", icon: "refine", tabs: REFINE_TABS },
  { key: "/platforms/xhs/write", label: "写稿", icon: "write", tabs: WRITE_TABS },
  { key: "/platforms/xhs/publish-hub", label: "发布", icon: "publish", tabs: PUBLISH_TABS },
  { key: "/agent", label: "智能助手", icon: "agent", tabs: [] },
  { key: "/settings", label: "设置", icon: "settings", tabs: SETTINGS_TABS },
];

export type BreadcrumbItem = {
  label: string;
  to?: string;
};

/** The current item is plain text; all ancestors stay clickable. */
function finishBreadcrumb(items: BreadcrumbItem[]): BreadcrumbItem[] {
  return items.map((item, index) =>
    index === items.length - 1 ? { label: item.label } : item,
  );
}

function tabMatches(tab: SectionTab, pathname: string): boolean {
  if (pathname === tab.key || pathname.startsWith(`${tab.key}/`)) return true;
  return Boolean(tab.children?.some((child) => tabMatches(child, pathname)));
}

/** Find the deepest tab trail for a path, following `children` recursively. */
function findTabTrail(tabs: SectionTab[], pathname: string): SectionTab[] {
  const tab = [...tabs]
    .sort((a, b) => b.key.length - a.key.length)
    .find((item) => tabMatches(item, pathname));
  if (!tab) return [];
  return [tab, ...(tab.children ? findTabTrail(tab.children, pathname) : [])];
}

/**
 * Return the visible trail with optional links, e.g.
 * [{label:"写稿",to:"/write"}, {label:"视觉素材",to:"/write/visual"}, {label:"图片素材"}].
 * Any future depth is derived from SectionTab.children instead of hard-coded ifs.
 */
export function resolveBreadcrumbItems(pathname: string): BreadcrumbItem[] {
  const section = [...NAV_SECTIONS]
    .sort((a, b) => b.key.length - a.key.length)
    .find((item) => pathname === item.key || pathname.startsWith(`${item.key}/`));
  if (!section) return [];

  const items: BreadcrumbItem[] = [{ label: section.label, to: section.key }];
  for (const tab of findTabTrail(section.tabs, pathname)) {
    items.push({ label: tab.label, to: tab.key });
  }
  return finishBreadcrumb(items);
}


