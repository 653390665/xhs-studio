/**
 * noteLookup.ts — 按 note_id 把样本库里的笔记找回来
 *
 * 项目页要知道「这个项目存过哪些笔记」。项目的历史里只有 note_id，
 * 正文和封面在样本库（后端 /api/notes）。
 *
 * 为什么不给后端加个接口：后端不能改，而且 /api/notes 本来就支持分页拉全量，
 * 几十上百篇一次读完够用。这里加一层内存缓存，翻项目时不用反复拉。
 */

import { get, unwrapList } from "./api";
import type { CorpusNote } from "./corpus";

/** 一次拉多少。100 是后端上限 */
const PAGE = 100;
/** 最多翻几页，防止样本库特别大时卡住 */
const MAX_PAGES = 12;

let cache: CorpusNote[] | null = null;
let inflight: Promise<CorpusNote[]> | null = null;

/** 全库笔记（带缓存）。invalidate 之后下次重新拉 */
export function loadLibrary(): Promise<CorpusNote[]> {
  if (cache) return Promise.resolve(cache);
  if (inflight) return inflight;

  inflight = (async () => {
    const out: CorpusNote[] = [];
    for (let page = 1; page <= MAX_PAGES; page += 1) {
      const res = await get(`/api/notes?page=${page}&page_size=${PAGE}`).then((r) =>
        unwrapList<CorpusNote>(r),
      );
      out.push(...res.items);
      if (res.items.length < PAGE || out.length >= res.total) break;
    }
    cache = out;
    return out;
  })();

  try {
    return inflight;
  } finally {
    /* 失败也要把 inflight 清掉，否则一次网络抖动就永久卡在同一个 rejected promise */
    void inflight.finally(() => {
      inflight = null;
    });
  }
}

/** 丢掉缓存，下次重新拉（存完新笔记之后调） */
export function invalidateLibrary(): void {
  cache = null;
}

/**
 * 按标题认回笔记。
 *
 * 为什么需要：早先版本的保存事件只记了标题、没记 note_id。
 * 光看"存了 3 篇"却一张卡都摆不出来，用户会以为东西丢了。
 * 标题只是兜底，认不回来的就跳过，不硬凑。
 */
export function pickByTitles(
  all: CorpusNote[],
  titles: string[],
): CorpusNote[] {
  const want = new Set(titles.filter(Boolean));
  if (want.size === 0) return [];
  const out: CorpusNote[] = [];
  const got = new Set<string>();
  for (const n of all) {
    const t = n.title?.trim();
    if (!t || !want.has(t) || got.has(t)) continue;
    got.add(t);
    out.push(n);
  }
  return out;
}

/**
 * 按 note_id 取笔记，保持传入顺序。
 *
 * 找不到的（比如笔记在别处被删了）直接跳过，不返回占位对象——
 * 项目页宁可少一张卡，也不该摆一张点不开的空壳。
 */
export function pickNotes(
  all: CorpusNote[],
  noteIds: string[],
): Array<{ noteId: string; note: CorpusNote }> {
  const byNoteId = new Map<string, CorpusNote>();
  for (const n of all) {
    const key = String(n.note_id ?? n.id);
    byNoteId.set(key, n);
  }
  const out: Array<{ noteId: string; note: CorpusNote }> = [];
  for (const id of noteIds) {
    const found = byNoteId.get(id);
    if (found) out.push({ noteId: id, note: found });
  }
  return out;
}

/**
 * 同上，只要笔记本身。
 * 提炼结果页要拿正文数结构，不关心 note_id。
 */
export function loadLibraryByIds(
  all: CorpusNote[],
  noteIds: string[],
): CorpusNote[] {
  return pickNotes(all, noteIds).map((c) => c.note);
}
