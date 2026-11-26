/**
 * searchSession.ts — 搜索与正文补全的后台会话
 *
 * 为什么不能留在组件里：
 *   搜索 3–5 秒，20 篇正文补全一分多钟。这些活儿一旦挂在组件上，
 *   用户切到提炼页看一眼再回来，组件卸载 → 请求被 abort → 全部白跑。
 *   用户的原话是「它这个过程中切换页面，它也不能中断」。所以：
 *
 *   · 会话状态放在模块级 store（和 tasks.ts 同一套思路），组件只订阅；
 *   · 补全用 for 循环串行推进，不绑任何组件生命周期；
 *   · 结果逐条写回 store，也逐条进 notesCache，切回来时直接读现成的。
 *
 * 并发定在 3：抓取端是串行限流的，实测 5 并发不比 3 快，只会更容易失败。
 */

import { useSyncExternalStore } from "react";
import { getNoteBody, peekMany, peekNote } from "./notesCache";
import type { NoteBody } from "./notesCache";

export type DetailState = "none" | "loading" | "done" | "error" | "cached";

export interface Hit extends NoteBody {
  detail: DetailState;
}

/** 一条搜索会话：关键词、结果、进度都在这 */
export interface SearchSession {
  /** 递增 id，组件靠它判断"是不是换了一次搜索" */
  id: number;
  keyword: string;
  hits: Hit[];
  /** 已经拿到正文的篇数 */
  done: number;
  /** 这一轮打算抓几张（只预热前几张，不是全部，见 AUTO_PREFETCH） */
  total: number;
  /** 搜索请求本身还在跑 */
  searching: boolean;
  /** 搜索失败的原因，成功时清掉 */
  error?: string;
  /** 是否还在补正文 */
  running: boolean;
  startedAt: number;
  /** 当前结果来自搜索结果的第几页（1 起）。链接模式恒为 1 */
  page: number;
  /** 后端说这次结果之后还有下一页，决定「下一页」能不能点 */
  hasMore: boolean;
  endedAt?: number;
}

const K = "xhs.search.session.v1";

/** 勾选了哪几篇。和搜索结果同生共死 */
let picked: string[] = [];

export function getPicked(): string[] {
  return picked;
}

export function setPicked(list: string[]): void {
  picked = list;
  emit();
}

let session: SearchSession = {
  id: 0,
  keyword: "",
  hits: [],
  done: 0,
  total: 0,
  searching: false,
  running: false,
  startedAt: 0,
  page: 1,
  hasMore: false,
};

/*
 * 刷新之后要能接上：卡片骨架（标题、作者、封面、赞数）连同关键词一起存进去，
 * 正文不进这里——它在 notesCache 里按 note_id 存，量级差十倍。
 */
let hydrated = false;

function hydrate(): void {
  if (hydrated) return;
  hydrated = true;
  try {
    const raw = sessionStorage.getItem(K);
    if (!raw) return;
    const saved = JSON.parse(raw) as Partial<SearchSession> & { picked?: string[] };
    if (!saved || !Array.isArray(saved.hits) || saved.hits.length === 0) return;
    /* 正文从缓存补回来：上次已经抓到的，这次直接就是 done */
    const cache = peekMany(saved.hits.map((h) => h.note_id));
    session = {
      id: saved.id ?? 1,
      keyword: saved.keyword ?? "",
      hits: saved.hits.map((h) => {
        const body = cache.get(h.note_id);
        if (body) return { ...h, ...body, detail: "done" as DetailState };
        /* 上次没抓完的，标成待补，进页面后自动接着抓 */
        return { ...h, detail: (h.detail === "error" ? "error" : "none") as DetailState };
      }),
      done: 0,
      total: saved.hits.length,
      searching: false,
      running: false,
      startedAt: saved.startedAt ?? Date.now(),
      page: saved.page ?? 1,
      hasMore: saved.hasMore ?? false,
    };
    session.done = session.hits.filter((h) => h.detail === "done").length;

    const alive = new Set(session.hits.map((h) => h.note_id));
    const savedPicked = Array.isArray(saved.picked) ? saved.picked : [];
    picked = savedPicked.filter((id) => alive.has(id));
    snapshot = { ...session, hits: session.hits };
  } catch {
    /* 存坏了就当没有，不能因为缓存让页面打不开 */
  }
}

let saveTimer: number | null = null;

/** 立刻把会话写进 sessionStorage（预热结束时用，不能等节流） */
function persistFlush(): void {
  if (saveTimer !== null) {
    window.clearTimeout(saveTimer);
    saveTimer = null;
  }
  writeSession();
}

/** 把会话写进 sessionStorage。正文不进这里——它在 notesCache，按 note_id 存 */
function writeSession(): void {
  try {
    /* 只存骨架：正文在 notesCache，两边各存各的 */
    const slim = session.hits.map((h) => ({
      note_id: h.note_id,
      note_url: h.note_url,
      title: h.title,
      author_name: h.author_name,
      author_id: h.author_id,
      cover_url: h.cover_url,
      image_urls: h.image_urls,
      likes: h.likes,
      collects: h.collects,
      comments: h.comments,
      shares: h.shares,
      detail: h.detail,
    }));
    sessionStorage.setItem(
      K,
      JSON.stringify({
        id: session.id,
        keyword: session.keyword,
        startedAt: session.startedAt,
        page: session.page,
        hasMore: session.hasMore,
        picked,
        hits: slim,
      }),
    );
  } catch {
    /* 配额满：内存那份还在 */
  }
}

/** 攒 600ms 再写：补全时一条一条来，不能每条都写盘 */
function persist(): void {
  if (saveTimer !== null) return;
  saveTimer = window.setTimeout(() => {
    saveTimer = null;
    writeSession();
  }, 600);
}

const listeners = new Set<() => void>();

/**
 * 每次改动都换一个新快照。
 * useSyncExternalStore 用 Object.is 比较，原地改字段它认不出来，
 * 界面就不会更新——这条踩过。
 */
function emit(): void {
  snapshot = { ...session, hits: session.hits };
  persist();
  listeners.forEach((fn) => fn());
}

let snapshot: SearchSession = { ...session };

export function subscribeSearch(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export function getSearchSession(): SearchSession {
  hydrate();
  return snapshot;
}

/* 补全的开关：换一次搜索就换一个新令牌，旧的循环自己退出 */
let token = 0;

/*
 * 预热几篇正文。
 *
 * 2026-11-27: 6 → 3。
 * 采集深度已定成「一次 20 条」，而 note_detail 限额 10 次/分钟、前端串行 1 路，
 * 预热 6 篇就要 36 秒。降到 3 篇约 18 秒，用户点开任意一篇都不用排在长队后面。
 * 其余的正文本就在用户点开或勾选时才抓。
 */
const AUTO_PREFETCH = 3;

/*
 * 后台预热用 1 路。
 *
 * 实测：抓取端是串行的，3 路并发和 1 路总耗时一样（20 篇都在 60 秒上下），
 * 但并发开的越多，用户在队尾"点开某一篇"要排的队就越长。
 * 用 1 路，点开时最多只排在 1 篇后面，用户感知是"点一下，两三秒出正文"。
 */
const CONCURRENCY = 1;

/** 从缓存里能直接拿到的先拿：这一批通常能省掉一半抓取 */
function fillFromCache(hits: Hit[]): Hit[] {
  const cache = peekMany(hits.map((h) => h.note_id));
  if (cache.size === 0) return hits;
  return hits.map((h) => {
    const c = cache.get(h.note_id);
    if (!c) return h;
    const merged = { ...h, ...c };
    return { ...merged, detail: "done" as DetailState };
  });
}

/**
 * 开一次新搜索。list 是搜索接口回来的原始条目（正文全空）。
 * 返回新会话 id，调用方不必等它——补全在后台自己跑。
 *
 * page / hasMore 由调用方从响应里带进来：后端 `page` 是这次请求的页码，
 * `has_more` 决定「下一页」按钮能不能点。不带就默认第 1 页、没有下一页
 * （粘贴链接进来时就属于这种）。
 */
export function startSearch(
  accountId: number,
  keyword: string,
  list: NoteBody[],
  opts?: { page?: number; hasMore?: boolean },
): number {
  const seen = new Set<string>();
  const base: Hit[] = [];
  for (const n of list) {
    if (!n.note_id || seen.has(n.note_id)) continue;
    seen.add(n.note_id);
    base.push({ ...n, detail: n.content ? "done" : "none" });
  }

  const hits = fillFromCache(base);
  const pending = hits.filter((h) => h.detail !== "done").length;

  session = {
    id: session.id + 1,
    keyword,
    hits,
    done: hits.length - pending,
    total: Math.min(pending, AUTO_PREFETCH) + (hits.length - pending),
    /* 搜索请求本身已经结束了（结果在手），这里不是"正在搜"；
       分页按钮的显隐看 page/hasMore/hits，不看 searching */
    searching: false,
    running: pending > 0,
    startedAt: Date.now(),
    page: opts?.page && opts.page > 0 ? opts.page : 1,
    hasMore: opts?.hasMore === true,
  };
  emit();

  if (pending > 0) void fillBodies(accountId, session.id);
  else session.endedAt = Date.now();

  return session.id;
}

/**
 * 逐条补正文。串行 + 3 路并发，一路失败不挡后面。
 * 关键点：它不接收 AbortSignal —— 用户切页不该中断，只有换新搜索才停。
 */
async function fillBodies(accountId: number, myId: number): Promise<void> {
  token += 1;
  const mine = token;

  const dead = () => mine !== token || session.id !== myId;

  const queue = session.hits
    .filter((h) => h.detail === "none" || h.detail === "error")
    .slice(0, AUTO_PREFETCH);
  if (queue.length === 0) {
    session.running = false;
    session.endedAt = Date.now();
    emit();
    return;
  }

  session.running = true;
  emit();

  const queued = new Set(queue.map((h) => h.note_id));
  let cursor = 0;

  const patch = (noteId: string, next: Partial<Hit>) => {
    if (dead()) return;
    const list = session.hits.map((h) =>
      h.note_id === noteId ? { ...h, ...next } : h,
    );
    session.hits = list;
    session.done = list.filter((h) => h.detail === "done").length;
    /* 只把"排上队的"算进进度，没排队的不该拉长进度条 */
    session.running =
      queued.size > 0 && Array.from(queued).some((id) =>
        list.some((h) => h.note_id === id && h.detail !== "done" && h.detail !== "error"),
      );
    emit();
  };

  const worker = async () => {
    for (;;) {
      if (dead()) return;
      const i = cursor++;
      if (i >= queue.length) return;
      const h = queue[i];
      if (!h.note_url) {
        patch(h.note_id, { detail: "error" });
        continue;
      }

      /* 排队期间别的入口可能已经抓回来了 */
      const already = peekNote(h.note_id);
      if (already) {
        patch(h.note_id, { ...already, detail: "done" });
        continue;
      }

      patch(h.note_id, { detail: "loading" });
      try {
        const body = await getNoteBody(accountId, h.note_url, h.note_id);
        patch(h.note_id, { ...body, detail: "done" });
      } catch {
        patch(h.note_id, { detail: "error" });
      }
    }
  };

  await Promise.all(
    Array.from({ length: Math.min(CONCURRENCY, queue.length) }, worker),
  );

  if (!dead()) {
    session.running = false;
    session.endedAt = Date.now();
    emit();
  }
  /* 预热完成就写一次盘：刷新后这几张不用再抓 */
  persistFlush();
}

/**
 * 粘贴链接进来的那几篇：链接里没有 note_id，先按 url 占位摆出卡片，
 * 抓回详情后把 note_id 换成真的。走和搜索同一套补全，所以切页也不断。
 */
export function startUrlSearch(accountId: number, urls: string[]): number {
  const hits: Hit[] = urls.map((u, i) => ({
    note_id: `pending-${i}-${u.slice(-12)}`,
    note_url: u,
    detail: "none" as DetailState,
  }));

  session = {
    id: session.id + 1,
    keyword: "",
    hits,
    done: 0,
    total: hits.length,
    searching: false,
    running: true,
    startedAt: Date.now(),
    page: 1,
    hasMore: false,
  };
  picked = [];
  emit();
  void fillBodies(accountId, session.id);
  return session.id;
}

/** 用户在抽屉里点开的某一篇，正文还没到就单独催一下（插队） */
export async function ensureBody(
  accountId: number,
  hit: Hit,
): Promise<void> {
  if (!hit.note_url) return;
  if (hit.detail === "done" && hit.content) return;

  const cached = peekNote(hit.note_id);
  if (cached) {
    patchOne(hit.note_id, { ...cached, detail: "done" });
    return;
  }

  patchOne(hit.note_id, { detail: "loading" });
  try {
    const body = await getNoteBody(accountId, hit.note_url, hit.note_id);
    patchOne(hit.note_id, { ...body, detail: "done" });
  } catch {
    patchOne(hit.note_id, { detail: "error" });
  }
}

function patchOne(noteId: string, next: Partial<Hit>): void {
  if (!session.hits.some((h) => h.note_id === noteId)) return;
  session.hits = session.hits.map((h) =>
    h.note_id === noteId ? { ...h, ...next } : h,
  );
  session.done = session.hits.filter((h) => h.detail === "done").length;
  session.running = session.hits.some(
    (h) => h.detail === "loading" || h.detail === "none",
  );
  emit();
}

/** 搜索请求发出去了，界面要显示"在找" */
export function beginSearch(keyword: string): void {
  session = {
    ...session,
    id: session.id + 1,
    keyword,
    searching: true,
    error: undefined,
  };
  emit();
}

/**
 * 翻页：拿着同一个关键词换一页结果。
 *
 * 和 startSearch 的区别只有两点——不动 keyword、不计入搜索历史。
 * 正文补全照样在后台跑，切页也不断。
 */
export function applyPage(
  accountId: number,
  keyword: string,
  list: NoteBody[],
  page: number,
  hasMore: boolean,
): void {
  startSearch(accountId, keyword, list, { page, hasMore });
}

/** 翻页请求发出去了：进度条亮起、按钮禁用，但已有卡片不换成骨架 */
export function beginPage(): void {
  session = { ...session, searching: true, error: undefined };
  emit();
}

/** 搜索失败：原因留在会话里，切页回来还看得到 */
export function failSearch(message: string): void {
  session = { ...session, searching: false, error: message };
  emit();
}

/**
 * 接着抓。页面重新挂载（切页回来、刷新）时调一次：
 * 会话里还有没取到的正文就继续补，已抓到的不会再抓。
 */
export function resumeSearch(accountId: number): void {
  if (session.hits.length === 0) return;
  if (!session.hits.some((h) => h.detail === "none" || h.detail === "error")) return;
  session.running = true;
  emit();
  void fillBodies(accountId, session.id);
}

/** 换关键词前清场：旧结果不能跟新关键词混在一起 */
export function clearSearch(): void {
  token += 1;
  picked = [];
  session = {
    id: session.id + 1,
    keyword: "",
    hits: [],
    done: 0,
    total: 0,
    searching: false,
    running: false,
    startedAt: 0,
    page: 1,
    hasMore: false,
  };
  emit();
  try {
    sessionStorage.removeItem(K);
  } catch {
    /* 忽略 */
  }
}

/** 手动重试所有失败的那些 */
export function retryFailed(accountId: number): void {
  if (!session.hits.some((h) => h.detail === "error")) return;
  session.hits = session.hits.map((h) =>
    h.detail === "error" ? { ...h, detail: "none" as DetailState } : h,
  );
  session.running = true;
  emit();
  void fillBodies(accountId, session.id);
}

/* ============================================================
   Hooks
   ============================================================ */

export function useSearchSession(): SearchSession {
  return useSyncExternalStore(
    subscribeSearch,
    getSearchSession,
    getSearchSession,
  );
}

/** 勾选的订阅：返回 [id 数组, 设置函数] */
export function usePickedIds(): [string[], (next: string[]) => void] {
  const list = useSyncExternalStore(subscribeSearch, getPicked, getPicked);
  return [list, setPicked];
}
