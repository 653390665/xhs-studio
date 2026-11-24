/**
 * notesCache.ts — 笔记详情缓存 + 同一篇只抓一次
 *
 * 为什么要单独一层（实测数据）：
 *   · /api/xhs/pc/search/notes 返回的 20 条 content 全是空的，正文必须
 *     另外调 /api/xhs/pc/notes/detail 逐条取。
 *   · 这个详情接口没有服务端缓存：同一篇笔记连调两次，第二次照样 3 秒。
 *     用户在卡片和抽屉之间来回点，等于每次都重新爬一遍。
 *   · 单条 2–3 秒，并发超过 3 条反而更慢（抓取端串行限流）。所以 20 篇
 *     正文补全要一分多钟，用户会以为坏了。
 *
 * 做两件事：
 *   1. 已经取到的正文存起来（内存 + sessionStorage），同一篇永远只抓一次。
 *      搜索同一个关键词、关掉抽屉再点开、切页回来，都是秒出。
 *   2. 同一篇正在抓的时候再来一个请求，合并到同一个 Promise 上，
 *      不发第二遍——点卡片触发的补全和后台补全常常撞在同一篇。
 */

import { post } from "./api";

export interface NoteBody {
  note_id: string;
  note_url?: string;
  title?: string;
  content?: string;
  author_id?: string;
  author_name?: string;
  cover_url?: string;
  image_urls?: string[];
  likes?: number;
  collects?: number;
  comments?: number;
  shares?: number;
  raw?: unknown;
}

const K = "xhs.notes.cache.v1";

/** 内存里那份：进程内最快，跨页面切来切去都命中 */
const mem = new Map<string, NoteBody>();
/** 正在抓的：url -> Promise，用来合并重复请求 */
const inflight = new Map<string, Promise<NoteBody>>();

/** 留多少条。一条正文平均 3–6KB，300 条约 1.2MB，sessionStorage 装得下 */
const MAX = 300;

/* sessionStorage 里的那份懒加载：模块被引入时不读盘，第一次真用才读 */
let loaded = false;

function loadDisk(): void {
  if (loaded) return;
  loaded = true;
  try {
    const raw = sessionStorage.getItem(K);
    if (!raw) return;
    const rows = JSON.parse(raw) as NoteBody[];
    if (!Array.isArray(rows)) return;
    for (const r of rows) if (r?.note_id) mem.set(r.note_id, r);
  } catch {
    /* 内容坏了就当没有，不能因为缓存坏了让页面打不开 */
  }
}

let flushTimer: number | null = null;

function scheduleFlush(): void {
  if (flushTimer !== null) return;
  flushTimer = window.setTimeout(() => {
    flushTimer = null;
    flush();
  }, 800);
}

function flush(): void {
  try {
    /* 只留最近的 MAX 条：Map 是插入序，从头部裁 */
    while (mem.size > MAX) {
      const first = mem.keys().next().value;
      if (first === undefined) break;
      mem.delete(first);
    }
    sessionStorage.setItem(K, JSON.stringify(Array.from(mem.values())));
  } catch {
    /* 配额满：内存那份还在，只是刷新后要重抓，不影响本次使用 */
  }
}

/** 页面要关了，把攒着的写掉 */
export function flushNoteCache(): void {
  if (flushTimer !== null) {
    window.clearTimeout(flushTimer);
    flushTimer = null;
  }
  flush();
}

/** 取一条已缓存的正文，没有就是 undefined */
export function peekNote(noteId: string): NoteBody | undefined {
  loadDisk();
  return mem.get(noteId);
}

/** 批量看哪些已经在缓存里（卡片角标、优先补全用） */
export function peekMany(noteIds: string[]): Map<string, NoteBody> {
  loadDisk();
  const out = new Map<string, NoteBody>();
  for (const id of noteIds) {
    const hit = mem.get(id);
    if (hit) out.set(id, hit);
  }
  return out;
}

/** 塞一条（样本库抽屉里已经拿到的正文，直接回填，省一次抓取） */
export function putNote(body: NoteBody): void {
  loadDisk();
  if (!body?.note_id) return;
  mem.delete(body.note_id);
  mem.set(body.note_id, body);
  scheduleFlush();
}

/**
 * 取一条正文。命中缓存立刻返回；正在抓就搭同一趟车。
 *
 * timeoutMs：抓取端偶发卡住，不设上限会让补全队列整体停摆。
 * 超时按失败处理，用户还能重试，比无声挂着好。
 */
export async function getNoteBody(
  accountId: number,
  noteUrl: string,
  noteId: string,
  opts: { signal?: AbortSignal; timeoutMs?: number } = {},
): Promise<NoteBody> {
  loadDisk();
  const cached = mem.get(noteId);
  if (cached) return cached;

  const running = inflight.get(noteUrl);
  if (running) return running;

  const { signal, timeoutMs = 25_000 } = opts;

  const timer = new AbortController();
  const to = window.setTimeout(() => timer.abort(), timeoutMs);

  /* 外面的信号和内部的超时信号合成一个 */
  const onAbort = () => timer.abort();
  signal?.addEventListener("abort", onAbort, { once: true });

  const p = (async () => {
    try {
      const d = await post<NoteBody>(
        "/api/xhs/pc/notes/detail",
        { account_id: accountId, url: noteUrl },
        { signal: timer.signal },
      );
      const body: NoteBody = { ...d, note_id: d.note_id || noteId };
      if (body.content || (body.image_urls?.length ?? 0) > 0) putNote(body);
      return body;
    } finally {
      window.clearTimeout(to);
      signal?.removeEventListener("abort", onAbort);
      inflight.delete(noteUrl);
    }
  })();

  inflight.set(noteUrl, p);
  return p;
}

/** 清空（换账号、调试用） */
export function clearNoteCache(): void {
  mem.clear();
  inflight.clear();
  loaded = true;
  try {
    sessionStorage.removeItem(K);
  } catch {
    /* 忽略 */
  }
}
