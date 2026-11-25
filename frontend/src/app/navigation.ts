/**
 * navigation.ts — 侧栏与子页的唯一事实来源
 *
 * 为什么单独抽出来：
 *   以前侧栏写在 Shell.tsx、子标签写在每个页面里、路由写在 App.tsx。
 *   三者各改一处，先出现「侧栏能点但路由不存在」，再出现「页面里有一套标签、
 *   外壳里又有一套」。现在只有这一份声明，Shell 和 App 都从它派生。
 *
 * 五个一级入口（2026-11 v2）：
 *   今日 / 素材 / 写稿 / 发布 / 设置
 *
 * 相比老前端的 8 个入口，合并的是：
 *   · 选题  → 素材（都是「写什么」的输入）
 *   · 提炼与能力 → 写稿（写法的值只在写稿时才兑现）
 *   · 智能助手 → 写稿下的子页（跑完落在草稿箱）
 *
 * platforms 字段是为第二个平台留的：抖音上线时只改这一处，
 * 不用动 Shell、不用动路由。现在只有 xhs 是 enabled。
 */

export type PlatformId = "xhs" | "douyin" | "kuaishou" | "weibo" | "xianyu" | "taobao";

export interface PlatformMeta {
  id: PlatformId;
  label: string;
  /** 只有 enabled 的平台会出现在界面；后端 registry 也返回同样的语义 */
  enabled: boolean;
}

export const PLATFORMS: PlatformMeta[] = [
  { id: "xhs", label: "小红书", enabled: true },
  { id: "douyin", label: "抖音", enabled: false },
  { id: "kuaishou", label: "快手", enabled: false },
  { id: "weibo", label: "微博", enabled: false },
  { id: "xianyu", label: "闲鱼", enabled: false },
  { id: "taobao", label: "淘宝", enabled: false },
];

export type NavIconKey = "today" | "assets" | "write" | "publish" | "settings";

export interface SectionTab {
  key: string;
  label: string;
  path: string;
  /** 用于判断激活；路径更长者优先 */
  match?: string;
}

export interface Section {
  key: string;
  label: string;
  /** 点侧栏去哪 */
  to: string;
  icon: NavIconKey;
  /** 该入口下所有子路径前缀，用于判断激活 */
  match: string[];
  /** 哪些平台显示这个板块。抖音只做采集，所以只有素材列了 douyin */
  platforms: PlatformId[];
  tabs: SectionTab[];
}

export const SECTIONS: Section[] = [
  {
    key: "today",
    label: "今日",
    to: "/",
    icon: "today",
    // 只有精确的 "/" 才算今日，否则 startsWith("/") 会在任何页面点亮
    match: ["/"],
    platforms: ["xhs"],
    tabs: [],
  },
  {
    key: "assets",
    label: "素材",
    to: "/assets",
    icon: "assets",
    match: ["/assets"],
    platforms: ["xhs", "douyin"],
    tabs: [
      { key: "collect", label: "采集", path: "/assets", match: "/assets" },
      { key: "library", label: "样本库", path: "/assets/library" },
      { key: "topics", label: "选题", path: "/assets/topics" },
      { key: "search", label: "找资料", path: "/assets/search" },
    ],
  },
  {
    key: "write",
    label: "写稿",
    to: "/write",
    icon: "write",
    match: ["/write"],
    platforms: ["xhs"],
    tabs: [
      { key: "drafts", label: "草稿", path: "/write", match: "/write" },
      { key: "batches", label: "提炼批次", path: "/write/batches" },
      { key: "cards", label: "批量出图", path: "/write/cards" },
      { key: "studio", label: "工作台", path: "/write/studio" },
      { key: "capabilities", label: "写法与能力", path: "/write/capabilities" },
      { key: "assistant", label: "助手", path: "/write/assistant" },
    ],
  },
  {
    key: "publish",
    label: "发布",
    to: "/publish",
    icon: "publish",
    match: ["/publish"],
    platforms: ["xhs"],
    tabs: [
      { key: "jobs", label: "队列", path: "/publish", match: "/publish" },
      { key: "calendar", label: "排期", path: "/publish/calendar" },
    ],
  },
  {
    key: "settings",
    label: "设置",
    to: "/settings",
    icon: "settings",
    match: ["/settings"],
    platforms: ["xhs", "douyin"],
    tabs: [
      { key: "models", label: "模型", path: "/settings/models" },
      { key: "image", label: "图片模型", path: "/settings/image" },
      { key: "accounts", label: "账号", path: "/settings/accounts" },
      { key: "positioning", label: "账号定位", path: "/settings/positioning" },
      { key: "auto-ops", label: "自动运营", path: "/settings/auto-ops" },
      { key: "matrix", label: "账号矩阵", path: "/settings/matrix" },
      { key: "risk", label: "风险开关", path: "/settings/risk" },
      { key: "status", label: "运行状态", path: "/settings/status" },
    ],
  },
];

/** 当前启用的平台（后端 registry 与这里保持一致；两边都不启用就不显示） */
export const ENABLED_PLATFORMS = PLATFORMS.filter((p) => p.enabled);

/** 某个板块是否应该出现 */
export function sectionVisible(section: Section): boolean {
  return section.platforms.some((id) =>
    ENABLED_PLATFORMS.some((platform) => platform.id === id),
  );
}

/** 当前路径属于哪个板块 */
export function sectionOf(pathname: string): Section | undefined {
  return SECTIONS.filter((section) => sectionVisible(section))
    .filter((section) => {
      if (section.key === "today") return pathname === "/" || pathname === "";
      return section.match.some(
        (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
      );
    })
    .sort((a, b) => (b.match[0] ?? "").length - (a.match[0] ?? "").length)[0];
}

/** 当前路径命中的子页（最长匹配优先） */
export function tabOf(section: Section, pathname: string): SectionTab | undefined {
  return [...section.tabs]
    .sort((a, b) => (b.match ?? b.path).length - (a.match ?? a.path).length)
    .find((tab) => {
      const key = tab.match ?? tab.path;
      if (tab.key === "drafts") {
        // 草稿是默认页：/write 与 /write/<草稿 id> 都算，
        // 但 /write/batches 这类具名子页不算
        return pathname === "/write" || /^\/write\/\d+(\/|$)/.test(pathname);
      }
      if (tab.key === "collect") {
        // 采集是素材的默认页：/assets 与 /assets/collect 都算
        return pathname === "/assets" || pathname === "/assets/collect";
      }
      if (tab.key === "jobs") {
        // 队列是发布的默认页：/publish 与老的 /publish/jobs 都算
        return pathname === "/publish" || pathname === "/publish/jobs";
      }
      if (tab.key === "models") {
        // 设置本身没有独立内容，落到第一页「模型」；
        // 否则 /settings 这条路径一个子页都命中不了，标签全是灰的
        return pathname === "/settings";
      }
      return pathname === key || pathname.startsWith(`${key}/`);
    });
}
