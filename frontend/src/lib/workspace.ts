/**
 * workspace.ts — 项目与历史记录（本地存储）
 *
 * 为什么在前端做：
 *   后端只有笔记本身带 created_at，没有「项目」这一层，也没有搜索历史接口
 *   （/api/xhs/corpus 是对标集，概念不同且实际是空的）。而用户要的
 *   「哪个项目、哪一天存了什么」本质是操作时间的账本，不是笔记内容，
 *   放在本地既够用又不会污染后端数据。
 *
 * 一条事件记什么：
 *   搜了什么词、什么时候存了几篇、提炼出了哪套写法——这三件事串起来
 *   就是"这个项目做到哪一步了"。笔记正文不进事件，只存 id 和标题，
 *   避免同一篇笔记在历史里复制一份正文。
 */

export interface Project {
  id: string;
  name: string;
  /** 创建时间，毫秒 */
  created_at: number;
  color?: string;
  /** 一句话目标，显示在项目名下面 */
  note?: string;
  /** 这个项目要用的主题（/api/tags 的 id），不填就是全部主题都算 */
  tag_ids?: number[];
}

export type EventKind = "search" | "save" | "distill" | "draft";

export interface ProjectEvent {
  id: string;
  project_id: string;
  kind: EventKind;
  /** 发生时间，毫秒 */
  at: number;
  /** 一行摘要，如「存了 3 篇」「搜了“向上管理”」 */
  title: string;
  /** 补充信息，如「主题：向上管理 · 4 篇能提炼」 */
  detail?: string;
  /** 涉及篇数，给时间线上的数字徽标用 */
  count?: number;
  /** 搜索关键词 */
  keyword?: string;
  /** 涉及的笔记标题，最多留 6 条，够在时间线上扫一眼 */
  note_titles?: string[];
  /**
   * 存进库里的笔记 note_id。
   *
   * 有了它，项目页才能把"这个项目存过哪些笔记"还原成卡片墙——
   * 之前只记标题，能看到"存了 3 篇"却点不进去。
   */
  note_ids?: string[];
  /**
   * 这次提炼出来的写法 id（后端 style-distill 的 profile id）。
   *
   * 有了它，「已提炼」那一行才点得开——能看到用了几篇、数出什么结构、
   * 以及切换"用在写稿上"。之前只记了个名字，提炼完就只是个名字。
   */
  profile_id?: number;
}

const K_PROJECTS = "xhs.projects";
const K_ACTIVE = "xhs.project.active";
const K_EVENTS = "xhs.project.events";

/** 事件最多留这么多条，超出丢最旧的：历史是给人翻的，不是数据库 */
const MAX_EVENTS = 500;

const COLORS = ["#c6362c", "#3f6d8f", "#7a6a3a", "#4a6b4a", "#6b4a6b"];

function uid(): string {
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;
}

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* 配额满或隐私模式：历史记不上不该让主流程崩 */
  }
}

/* ---------------- 项目 ---------------- */

export function loadProjects(): Project[] {
  const list = read<Project[]>(K_PROJECTS, []);
  return Array.isArray(list) ? list : [];
}

export function createProject(
  name: string,
  extra?: { note?: string; color?: string; tag_ids?: number[] },
): Project {
  const list = loadProjects();
  const p: Project = {
    id: uid(),
    name: name.trim() || `项目 ${list.length + 1}`,
    created_at: Date.now(),
    color: extra?.color ?? COLORS[list.length % COLORS.length],
    note: extra?.note?.trim() || undefined,
    tag_ids: extra?.tag_ids?.length ? extra.tag_ids : undefined,
  };
  write(K_PROJECTS, [...list, p]);
  if (!loadActiveProjectId()) write(K_ACTIVE, p.id);
  return p;
}

export function renameProject(id: string, name: string): void {
  write(
    K_PROJECTS,
    loadProjects().map((p) => (p.id === id ? { ...p, name: name.trim() || p.name } : p)),
  );
}

/** 改项目的其它字段（目标、颜色、主题）。名字走 renameProject */
export function updateProject(
  id: string,
  patch: Partial<Pick<Project, "name" | "note" | "color" | "tag_ids">>,
): void {
  write(
    K_PROJECTS,
    loadProjects().map((p) => {
      if (p.id !== id) return p;
      const next = { ...p, ...patch };
      /* 空数组等于"没限定主题"，存成 undefined 更好判断 */
      if (next.tag_ids && next.tag_ids.length === 0) next.tag_ids = undefined;
      if (next.note !== undefined) next.note = next.note.trim() || undefined;
      return next;
    }),
  );
}

export function deleteProject(id: string): void {
  write(K_PROJECTS, loadProjects().filter((p) => p.id !== id));
  write(K_EVENTS, loadEvents().filter((e) => e.project_id !== id));
  if (loadActiveProjectId() === id) {
    const rest = loadProjects();
    write(K_ACTIVE, rest[0]?.id ?? "");
  }
}

/** 当前项目 id；没有就建一个「默认项目」，免得用户第一次存东西时历史没处落 */
export function loadActiveProjectId(): string {
  const id = read<string>(K_ACTIVE, "");
  if (id && loadProjects().some((p) => p.id === id)) return id;
  const list = loadProjects();
  if (list.length > 0) {
    write(K_ACTIVE, list[0].id);
    return list[0].id;
  }
  return "";
}

export function setActiveProject(id: string): void {
  write(K_ACTIVE, id);
}

/** 取当前项目；一个项目都没有时按需建默认项目 */
export function ensureActiveProject(): Project {
  const id = loadActiveProjectId();
  const found = loadProjects().find((p) => p.id === id);
  if (found) return found;
  return createProject("默认项目");
}

/* ---------------- 事件 ---------------- */

export function loadEvents(projectId?: string): ProjectEvent[] {
  const all = read<ProjectEvent[]>(K_EVENTS, []);
  const list = Array.isArray(all) ? all : [];
  return projectId ? list.filter((e) => e.project_id === projectId) : list;
}

export function addEvent(
  e: Omit<ProjectEvent, "id" | "at" | "project_id"> & {
    project_id?: string;
    at?: number;
  },
): void {
  const project = e.project_id
    ? (loadProjects().find((p) => p.id === e.project_id) ?? ensureActiveProject())
    : ensureActiveProject();

  const ev: ProjectEvent = {
    id: uid(),
    project_id: project.id,
    kind: e.kind,
    at: e.at ?? Date.now(),
    title: e.title,
    detail: e.detail,
    count: e.count,
    keyword: e.keyword,
    note_titles: e.note_titles?.slice(0, 6),
    note_ids: e.note_ids?.filter(Boolean),
  };

  const next = [...loadEvents(), ev];
  write(K_EVENTS, next.length > MAX_EVENTS ? next.slice(-MAX_EVENTS) : next);
}

/* ---------------- 项目里存过哪些笔记 ---------------- */

/**
 * 一个项目攒下来的全部笔记 note_id，按存入时间先后去重。
 *
 * 为什么从事件里推，而不单独存一份：
 *   事件本来就要记"存了 3 篇"，顺手带上 id 就够了。另存一份的话，
 *   删项目要清两处、改一处忘了另一处就会出现对不上的幽灵卡片。
 */
export function projectNoteIds(projectId: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const e of loadEvents(projectId)) {
    if (e.kind !== "save" || !e.note_ids) continue;
    for (const id of e.note_ids) {
      if (seen.has(id)) continue;
      seen.add(id);
      out.push(id);
    }
  }
  return out;
}

/** 项目里存过多少篇（去重后） */
export function projectNoteCount(projectId: string): number {
  return projectNoteIds(projectId).length;
}

/* ---------------- 按日期分组 ---------------- */

export interface DayGroup {
  /** 2026-11-07 */
  key: string;
  /** 11 月 7 日 周五 / 今天 / 昨天 */
  label: string;
  events: ProjectEvent[];
}

const WEEK = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

function dayKey(d: Date): string {
  const m = `${d.getMonth() + 1}`.padStart(2, "0");
  const day = `${d.getDate()}`.padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

export function groupByDay(events: ProjectEvent[]): DayGroup[] {
  const now = new Date();
  const today = dayKey(now);
  const yest = new Date(now.getTime() - 86_400_000);
  const yesterday = dayKey(yest);

  const map = new Map<string, ProjectEvent[]>();
  for (const e of events) {
    const k = dayKey(new Date(e.at));
    const arr = map.get(k);
    if (arr) arr.push(e);
    else map.set(k, [e]);
  }

  return Array.from(map.entries())
    .sort((a, b) => (a[0] < b[0] ? 1 : -1))
    .map(([key, list]) => {
      const d = new Date(list[0].at);
      let label: string;
      if (key === today) label = "今天";
      else if (key === yesterday) label = "昨天";
      else label = `${d.getMonth() + 1} 月 ${d.getDate()} 日 ${WEEK[d.getDay()]}`;
      return {
        key,
        label,
        events: list.sort((a, b) => b.at - a.at),
      };
    });
}

/** 时间点，如 14:32 */
export function fmtTime(ms: number): string {
  const d = new Date(ms);
  return `${`${d.getHours()}`.padStart(2, "0")}:${`${d.getMinutes()}`.padStart(2, "0")}`;
}
