import {notifyWriterMaterialSave,writerSessionMaterialSignature} from './writerMaterials';
/**
 * studioState.ts — 工作台的现场（跨页面存活）
 *
 * 工作台现在只做一件事：把提炼页勾中的那批素材，整理成一份能反复用的
 * Markdown 模板，存进草稿箱。
 *
 * 为什么需要这一层（你提的要求：切页不能中断）：
 *   提炼要调最多两次模型，十多秒。填的要求、生成的 MD、写了一半的标题，
 *   原来挂在页面组件的 useState 里：一切到写稿页，React 把组件卸掉，
 *   回来就是一片空白，前面那次提炼白等。
 *
 * 做法：
 *   和 lib/formState.ts / lib/tasks.ts 同一套——模块级 store，
 *   组件只订阅、只写，不持有。切页不走丢。
 *
 * 为什么还写 sessionStorage：
 *   切页是常态，刷新和"从别处点回来"也是。写进 session 之后连刷新都还在；
 *   关掉标签页才清——这是"这一次浏览的现场"，不是资产。
 *
 * 为什么按 profileId 分槽：
 *   一次提炼对应一批素材。换一批就是另一份模板，不能互相覆盖。
 */

import { useCallback, useEffect, useSyncExternalStore } from "react";
import type { CorpusNote } from "./corpus";

/**
 * 提炼成什么。
 * 这四种是按"一份能反复用的东西"切的，不是按文章体裁切的：
 * 拿去做标题的、拿去起头的、拿去排正文的、拿去配图的，各用各的。
 */
export type TplKind = "full" | "title" | "hook" | "image";
export type DraftFilter = TplKind | "all" | "unclassified";

/** 历史未知值只归入未分类，不猜类型、不改原记录。 */
export function draftCategory(kind: unknown): Exclude<DraftFilter, "all"> {
  return kind === "full" || kind === "title" || kind === "hook" || kind === "image"
    ? kind : "unclassified";
}

export function draftFilterOf(value: unknown): DraftFilter {
  return value === "all" || value === "unclassified" || draftCategory(value) !== "unclassified"
    ? value as DraftFilter : "all";
}

export function countDrafts(drafts: StudioDraft[]): Record<DraftFilter, number> {
  const counts = { all: drafts.length, full: 0, title: 0, hook: 0, image: 0, unclassified: 0 };
  for (const draft of drafts) counts[draftCategory(draft.kind)] += 1;
  return counts;
}

export function filterDrafts(drafts: StudioDraft[], filter: DraftFilter): StudioDraft[] {
  return filter === "all" ? drafts : drafts.filter((draft) => draftCategory(draft.kind) === filter);
}

/** 一条草稿。at 是它在这儿的唯一身份，也当排序用 */
export interface StudioDraft {
  at: number;
  /** 存的是哪种模板，列表上标一下 */
  kind: TplKind | null;
  title: string;
  /** Markdown 正文 */
  body: string;
  /** 后端草稿 id：存过才有 */
  id?: number;
  /**
   * 从哪批素材提炼来的。
   *
   * 草稿箱不分批次了（见下方 readLocalDrafts 的说明），所以每一条得自己
   * 记住出处，列表上标出来，人才能对上"这份是拿哪批素材做的"。
   */
  batch?: string;
  batchName?: string;
}

/**
 * 四个板块各自最近一次的提炼结果。
 *
 * 为什么按类型分开存：一份 md 顶不住"整篇提炼一次、再提炼一次标题"——
 * 第二次写进同一个字段，第一次那份还没存就已经没了。用户看到的就是
 * "上一份直接消失"。现在四种各占一格，互不覆盖，切回哪个板块就显示哪个。
 */
export interface StudioResult {
  md: string;
  /** 提炼出来时还没起名字，存草稿时才写 */
  title: string;
  at: number;
  /**
   * 这份结果是用哪批素材 + 哪个板块算出来的（`kind|dump` 的哈希）。
   *
   * 用途：同一批素材再点一次「提炼成模板」时，能认出「输入没变」，
   * 直接把上次那份摆回来，而不是再调一次模型拿到另一版。
   * 模型本身不保证可复现（本地这个端点的 `seed` 实测无效），
   * 所以「同一输入同一结果」只能靠这一层缓存兑现，不能只靠温度。
   */
  inputKey?: string;
}

export interface StudioSummary {
  works?: number;
  chars?: number;
  positioning?: string;
  tone?: string;
  sample_titles?: string[];
  avg_sentence_chars?: number;
  question_ratio?: number;
  top_phrases?: Array<{ phrase: string; count: number }>;
  hooks?: Array<{ label: string; count: number }>;
}

export interface StudioProfile {
  id: number;
  name: string;
  status: string;
  works_count: number;
  char_count: number;
  summary?: StudioSummary;
  profile?: { note_ids?: number[] };
  /** 后端生成的写法全文。 */
  skill_md?: string;
  source?: string;
  engine?: string;
  /**
   * 正文能不能改。内置型和证据蒸馏型都是 false——它们的正文分别是产品内容和
   * 规则的渲染视图，改了只会让一部分注入路径看到新内容、另一部分看到旧规则。
   * 由后端算好下发，前端不重复判定（`studioEditable` 只在列表页做一次兜底）。
   */
  editable?: boolean;
}

export interface StudioSnapshot {
  /** 载入过的写法和那批素材：切回来不再转圈，封面不闪 */
  profile: StudioProfile | null;
  notes: CorpusNote[];

  /** 提炼成什么 */
  kind: TplKind;
  /** 具体要求：用户自己写，也可以让 AI 帮着理顺 */
  brief: string;

  /* 跑起来的状态 */
  running: boolean;
  /** 现在跑到哪一步，直接显示给人看，不装作"马上好" */
  step: string;
  polishing: boolean;
  err: string | null;

  /* 结果 */
  md: string;
  /** 绑定生成时的类型；旧现场没有记录时不猜成当前选择。 */
  resultKind: TplKind | null;
  /** 标题由用户写，不替他编 */
  title: string;

  /**
   * 四个板块各自攒下来的那一份。
   *
   * md / resultKind / title 仍是"当下正在看的这一份"，
   * 这块是四个板块的后台存档：换板块、再提炼，之前那份都还在。
   */
  results: Partial<Record<TplKind, StudioResult>>;

  /* 草稿箱 */
  drafts: StudioDraft[];
  draftFilter: DraftFilter;
  lastSavedAt: number | null;
  /** 草稿箱里正打开哪一篇（null = 看列表） */
  openAt: number | null;
  /** 台面 / 草稿箱 */
  view: "new" | "drafts";
}

const EMPTY: StudioSnapshot = {
  profile: null,
  notes: [],
  kind: "full",
  brief: "",
  running: false,
  step: "",
  polishing: false,
  err: null,
  md: "",
  resultKind: null,
  title: "",
  results: {},
  drafts: [],
  draftFilter: "all",
  lastSavedAt: null,
  openAt: null,
  view: "new",
};

const store = new Map<string, StudioSnapshot>();
const listeners = new Set<() => void>();

const keyOf = (k: string) => `xhs.studio.${k}`;

function emit(): void {
  listeners.forEach((fn) => fn());
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

/* ---------------- 落盘 ---------------- */

/*
 * 攒 400ms 再写一次。要求和 MD 都是逐字改的，改一个字符写一次盘没必要。
 * 卸载前还会补写一次，见下方 useStudio 的 effect。
 */
const timers = new Map<string, number>();

export function saveNow(key: string): void {
  const t = timers.get(key);
  if (t !== undefined) {
    window.clearTimeout(t);
    timers.delete(key);
  }
  const snap = store.get(key);
  if (!snap) return;
  try {
    const previousMaterial=writerSessionMaterialSignature(sessionStorage.getItem(keyOf(key)));
    sessionStorage.setItem(
      keyOf(key),
      JSON.stringify({
        ...snap,
        /* 请求状态不该跨次存活：刷新时那个请求已经没了，留着会永远转圈 */
        running: false,
        polishing: false,
        step: "",
        err: null,
        /* 只要封面的信息，不带整条笔记，省配额 */
        notes: snap.notes.slice(0, 12),
      }),
    );
    if(previousMaterial!==writerSessionMaterialSignature(JSON.stringify(snap)))notifyWriterMaterialSave([key]);
  } catch {
    /* 配额满或隐私模式：内存里那份还在，页内照常可用 */
  }
}

function schedule(key: string): void {
  const t = timers.get(key);
  if (t !== undefined) window.clearTimeout(t);
  timers.set(
    key,
    window.setTimeout(() => saveNow(key), 400),
  );
}

export function readStudio(key: string): StudioSnapshot {
  const hit = store.get(key);
  if (hit) return hit;

  /*
   * 草稿箱从 localStorage 读，其余现场（要求、md、素材）还在 sessionStorage。
   * 两者合起来才是完整快照：草稿是资产，要跨会话；过程和素材是一次浏览的现场。
   */
  const drafts = readLocalDrafts();
  const results = readLocalResults(key);

  try {
    const raw = sessionStorage.getItem(keyOf(key));
    if (raw) {
      const saved = JSON.parse(raw) as Partial<StudioSnapshot>;
      const snap: StudioSnapshot = {
        ...EMPTY,
        ...saved,
        draftFilter: draftFilterOf(saved.draftFilter),
        resultKind: draftCategory(saved.resultKind) === "unclassified" ? null : saved.resultKind as TplKind,
        /* 旧的 sessionStorage 里那份草稿搬过来用，搬完就不再用它 */
        drafts: drafts.length > 0 ? drafts : Array.isArray(saved.drafts) ? saved.drafts : [],
        /* 四个板块的存档以 localStorage 为准；它比 session 那份活得久 */
        results: Object.keys(results).length > 0
          ? results
          : saved.results && typeof saved.results === "object" ? saved.results : {},
        running: false,
        polishing: false,
        step: "",
        err: null,
      };
      /* 旧数据迁移：session 里有、local 里没有，搬一次 */
      if (drafts.length === 0 && snap.drafts.length > 0) {
        writeLocalDrafts(dedupeDrafts(snap.drafts));
      }
      if (Object.keys(results).length === 0 && Object.keys(snap.results).length > 0) {
        writeLocalResults(key, snap.results);
      }
      store.set(key, snap);
      return snap;
    }
  } catch {
    /* 内容坏了就当没有，不能让页面白屏 */
  }

  const snap: StudioSnapshot = { ...EMPTY, drafts, results };
  store.set(key, snap);
  return snap;
}

/** 写现场。先落盘再通知，不依赖组件还活着 */
export function patchStudio(key: string, patch: Partial<StudioSnapshot>): void {
  const next = { ...readStudio(key), ...patch };
  store.set(key, next);
  /* 草稿变了就同步到 localStorage：它不是会话现场，是资产 */
  if (patch.drafts !== undefined) writeLocalDrafts(next.drafts);
  /* 四个板块的存档同理，关掉标签页也不能没 */
  if (patch.results !== undefined) writeLocalResults(key, next.results);
  schedule(key);
  emit();
}

/**
 * 把一份提炼结果记到它自己那个板块里。
 *
 * 四个板块各留各的：整篇提炼过一次、再提炼标题，第一次那份不会
 * 被第二次覆盖。切回哪个板块就把它那份摆回台面上。
 */
export function keepResult(
  key: string,
  kind: TplKind,
  md: string,
  title = "",
  inputKey = "",
): void {
  const cur = readStudio(key);
  patchStudio(key, {
    results: {
      ...cur.results,
      [kind]: { md, title, at: Date.now(), ...(inputKey ? { inputKey } : {}) },
    },
  });
}

/**
 * 重来：清掉这一份模板，但留着素材、草稿箱和选好的类型。
 * 重来是"再提炼一份"，不是"把这儿清空"。
 */
export function resetStudio(key: string): void {
  const cur = readStudio(key);
  store.set(key, {
    ...EMPTY,
    profile: cur.profile,
    notes: cur.notes,
    kind: cur.kind,
    drafts: cur.drafts,
    draftFilter: cur.draftFilter,
    lastSavedAt: cur.lastSavedAt,
    /* 四个板块各自攒的那份不能跟着重置一起丢掉 */
    results: cur.results,
  });
  schedule(key);
  emit();
}

/** 丢掉整槽（换写法时用） */
export function dropStudio(key: string): void {
  store.delete(key);
  try {
    sessionStorage.removeItem(keyOf(key));
  } catch {
    /* 忽略 */
  }
  emit();
}

/* ---------------- 草稿箱 ---------------- */

/*
 * 草稿箱是全局的，不按素材批次分开。
 *
 * 为什么（2026-11-09 十八改）：原来是 `xhs.studio.drafts.<批次id>`，
 * 换一批素材就是一个空箱子。而批次名是自动起的「默认项目 · 11月9日」，
 * 一天提炼三次就有三个同名批次 —— 点进去看着一模一样，草稿却是空的，
 * 用户只会认为"存了没生效"。
 *
 * 模板本来就是攒起来的资产，不该跟着素材批次走。现在一个箱子装全部，
 * 每条记着自己是哪批来的（batch / batchName），列表上标出来。
 */
const MAX_DRAFTS = 300;

const DRAFTS_KEY = "xhs.studio.drafts";
const LEGACY_DRAFT_PREFIX = "xhs.studio.drafts.";
const resultKeyOf = (k: string) => `xhs.studio.results.${k}`;

/*
 * 四个板块各自那份提炼结果仍按批次分。
 *
 * 它描述的是"拿这批素材提炼出来的那四份"，和批次天然绑定；
 * 而且换批次台面本来就该是空的。
 */
function readLocalResults(key: string): Partial<Record<TplKind, StudioResult>> {
  try {
    const raw = localStorage.getItem(resultKeyOf(key));
    if (!raw) return {};
    const got = JSON.parse(raw);
    if (!got || typeof got !== "object") return {};
    const out: Partial<Record<TplKind, StudioResult>> = {};
    for (const k of ["full", "title", "hook", "image"] as TplKind[]) {
      const v = got[k];
      if (v && typeof v.md === "string" && v.md) {
        out[k] = {
          md: v.md,
          title: String(v.title ?? ""),
          at: typeof v.at === "number" ? v.at : Date.now(),
        };
      }
    }
    return out;
  } catch {
    return {};
  }
}

function writeLocalResults(
  key: string,
  results: Partial<Record<TplKind, StudioResult>>,
): void {
  try {
    const encoded=JSON.stringify(results),previous=localStorage.getItem(resultKeyOf(key));
    localStorage.setItem(resultKeyOf(key),encoded);if(previous!==encoded)notifyWriterMaterialSave([key]);
  } catch {
    /* 配额满：内存里那份还在 */
  }
}

/** 把一条外来记录收拾成能显示的样子；认不出来的返回 null */
function normDraft(d: unknown, batch?: string): StudioDraft | null {
  if (!d || typeof d !== "object") return null;
  const o = d as Record<string, unknown>;
  if (typeof o.at !== "number") return null;
  const kind = draftCategory(o.kind) === "unclassified" ? null : (o.kind as TplKind);
  return {
    at: o.at,
    kind,
    title: String(o.title ?? ""),
    body: String(o.body ?? ""),
    id: typeof o.id === "number" ? o.id : undefined,
    batch: typeof o.batch === "string" ? o.batch : batch,
    batchName:
      typeof o.batchName === "string" ? o.batchName : batch ? "早先那一批" : undefined,
  };
}

function readLocalDrafts(): StudioDraft[] {
  const out: StudioDraft[] = [];

  /* ① 现在的全局箱子 */
  try {
    const raw = localStorage.getItem(DRAFTS_KEY);
    const list = raw ? JSON.parse(raw) : [];
    if (Array.isArray(list)) {
      for (const d of list) {
        const n = normDraft(d);
        if (n) out.push(n);
      }
    }
  } catch {
    /* 坏了当空的，下面还有旧数据可以捞 */
  }

  /* ② 旧版按批次分开放的，捞过来合成一份，捞完删掉旧键 */
  try {
    const legacy: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith(LEGACY_DRAFT_PREFIX)) legacy.push(k);
    }
    for (const k of legacy) {
      const batch = k.slice(LEGACY_DRAFT_PREFIX.length);
      const raw = localStorage.getItem(k);
      const list = raw ? JSON.parse(raw) : [];
      if (Array.isArray(list)) {
        for (const d of list) {
          const n = normDraft(d, batch);
          if (n) out.push(n);
        }
      }
      localStorage.removeItem(k);
    }
    if (legacy.length > 0) {
      /* 搬完写回全局箱子，下次不用再搬 */
      const merged = dedupeDrafts(out);
      localStorage.setItem(DRAFTS_KEY, JSON.stringify(merged.slice(0, MAX_DRAFTS)));
      return merged.slice(0, MAX_DRAFTS);
    }
  } catch {
    /* 隐私模式之类：内存里那份照常用 */
  }

  return dedupeDrafts(out).slice(0, MAX_DRAFTS);
}

/** 同一条可能既在全局箱子里、又在旧键里（保存时机不同），按 at 去重 */
function dedupeDrafts(list: StudioDraft[]): StudioDraft[] {
  const seen = new Set<number>();
  const out: StudioDraft[] = [];
  for (const d of list) {
    if (seen.has(d.at)) continue;
    seen.add(d.at);
    out.push(d);
  }
  return out.sort((a, b) => b.at - a.at);
}

function writeLocalDrafts(list: StudioDraft[]): void {
  try {
    const previous=localStorage.getItem(DRAFTS_KEY),encoded=JSON.stringify(list.slice(0,MAX_DRAFTS));let prior:Array<{batch?:string}>=[];try{const parsed=JSON.parse(previous||'[]');if(Array.isArray(parsed))prior=parsed;}catch{/* preserve normal save even if old metadata is malformed */}
    localStorage.setItem(DRAFTS_KEY,encoded);if(previous!==encoded)notifyWriterMaterialSave([...prior,...list].map(item=>item.batch).filter((value):value is string=>typeof value==='string'));
  } catch {
    /* 配额满：内存里那份还在，这一页照常用 */
  }
}

/* 清空草稿箱（目前没人调用，留着备用） */
export function clearDrafts(): void {
  try {
    localStorage.removeItem(DRAFTS_KEY);
  } catch {
    /* 忽略 */
  }
}

export function addDraft(
  list: StudioDraft[],
  d: Omit<StudioDraft, "at">,
): StudioDraft[] {
  /* at 同时是 React key/打开/移除身份；同毫秒保存也不能碰撞。 */
  const latest = list.reduce((max, item) => Math.max(max, item.at), 0);
  const at = Math.max(Date.now(), latest + 1);
  return [{ ...d, at }, ...list].slice(0, MAX_DRAFTS);
}

/**
 * 草稿箱是全局的，任何批次都看这一份。
 *
 * 页面上的 s.drafts 只是"这一批次打开时的快照"，别拿它当数据源：
 * 换个批次再看，它跟全局箱子又不是一回事了。
 */
export function globalDrafts(): StudioDraft[] {
  return readLocalDrafts();
}

/** 删一条：动的是全局箱子，然后同步回当前批次的快照 */
export function dropDraft(key: string, at: number): void {
  const list = readLocalDrafts().filter((d) => d.at !== at);
  writeLocalDrafts(list);
  patchStudio(key, { drafts: list, openAt: null });
}

/**
 * 把当前批次的快照跟全局箱子对齐。
 *
 * 为什么需要：store 里缓存的是"上一次打开时"的草稿列表。
 * 换个批次存了一份，再切回这个批次，缓存里还是旧的。
 * 进草稿箱时调一次，保证看到的是箱子里的真实内容。
 */
export function syncDrafts(key: string): void {
  const list = readLocalDrafts();
  const cur = readStudio(key);
  /*
   * lastSavedAt 也以箱子里最新那条为准。
   * 草稿箱是全局的了，「新保存」就该标在全局最新那份上，
   * 而不是"这一批上次存的那份"。
   */
  const newest = list[0]?.at ?? null;
  if (
    list.length === cur.drafts.length &&
    list.every((d, i) => d.at === cur.drafts[i]?.at) &&
    newest === cur.lastSavedAt
  ) {
    return;
  }
  patchStudio(key, { drafts: list, lastSavedAt: newest });
}

/** 只服务本工作台：异步保存完成后原子追加到最新快照，不改存储键契约。 */
export function appendStudioDraft(
  key: string,
  draft: Omit<StudioDraft, "at">,
): void {
  const current = readStudio(key);
  /*
   * 从全局箱子取最新的，不能用 current.drafts ——
   * 那是这个批次的快照，别的批次刚存进去的它不知道。
   */
  const drafts = addDraft(globalDrafts(), draft);
  patchStudio(key, {
    drafts,
    draftFilter: draftCategory(draft.kind),
    lastSavedAt: drafts[0].at,
    view: "drafts",
    openAt: null,
    /*
     * 存完把台面清空，但只清"刚存走的这一份"。
     * 用户在别的板块还留着提炼结果时，不能被顺手清掉。
     */
    ...(current.md === draft.body && current.resultKind === draft.kind
      ? { md: "", resultKind: null as TplKind | null, title: "" }
      : {}),
  });
  /* 保存后立即同步这份快照，避免切页/刷新撞上400ms节流窗口。 */
  saveNow(key);
}

export function removeDraft(list: StudioDraft[], at: number): StudioDraft[] {
  return list.filter((x) => x.at !== at);
}

export function findDraft(
  list: StudioDraft[],
  at: number | null,
): StudioDraft | undefined {
  if (at === null) return undefined;
  return list.find((x) => x.at === at);
}

/* ---------------- 订阅 ---------------- */

export function useStudio(
  key: string,
): [StudioSnapshot, (patch: Partial<StudioSnapshot>) => void] {
  const snap = useSyncExternalStore(
    subscribe,
    () => readStudio(key),
    () => readStudio(key),
  );

  const update = useCallback(
    (patch: Partial<StudioSnapshot>) => patchStudio(key, patch),
    [key],
  );

  /*
   * 卸载时把攒着的那次写掉，不能只清定时器：
   * 用户改完最后一笔立刻切页，那次更新还在 400ms 窗口里，
   * 清掉就等于把刚写的丢了。
   */
  useEffect(() => () => saveNow(key), [key]);

  return [snap, update];
}
