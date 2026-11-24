/**
 * agentCache.ts — 写稿助手的短时缓存
 *
 * 这一页现在会连着问后端好几次（查索引 → 读几篇原文 → 动笔）。
 * 不缓存的话，同一句话来回点两下就把钱重花一遍。
 *
 * 缓存的三层，各管各的：
 *   ① 索引结果  同一个词查第二次不重查（10 分钟）
 *   ② 单篇正文  读过的原文不再拉（30 分钟）
 *   ③ 这次读到的材料  读完之后要交给"改一版"当依据，跟着这一篇稿子走
 *
 * 为什么不放 localStorage：
 *   素材是会变的。半小时后还是不是那 79 篇，谁也不知道。
 *   sessionStorage 够用 —— 关掉标签页，这个对话也就结束了。
 *
 * 提示词缓存（这是另一个东西，别混）：
 *   DeepSeek 按"请求前缀"命中。route() 的 instruction 是固定不变的，
 *   只有 text 里放用户那句，所以每次都能吃到前缀缓存。
 *   这里改任何东西都**不要**去动 instruction 的静态部分。
 */

import { get } from "./api";

/* ---------------- 一层：带过期的键值 ---------------- */

interface Slot<T> {
  at: number;
  ttl: number;
  value: T;
}

const mem = new Map<string, Slot<unknown>>();

function readSlot<T>(k: string): T | undefined {
  const s = mem.get(k) as Slot<T> | undefined;
  if (!s) return undefined;
  if (Date.now() - s.at > s.ttl) {
    mem.delete(k);
    return undefined;
  }
  return s.value;
}

function writeSlot<T>(k: string, value: T, ttl: number): void {
  /* 别无限长：这页最多也就点几十下，超了清掉最早的 */
  if (mem.size > 80) {
    const first = mem.keys().next().value;
    if (first) mem.delete(first);
  }
  mem.set(k, { at: Date.now(), ttl, value });
}

/* ---------------- 二层：索引 ---------------- */

/** 索引里的一条。字段按后端 /api/notes 返回的挑，别照抄整个对象 */
export interface IndexHit {
  id: number;
  title: string;
  /** 正文前 90 字，卡片上够看了 */
  head: string;
  chars: number;
  likes: number;
  /** 为什么它进来：命中在标题还是正文 */
  why: string;
}

const INDEX_TTL = 10 * 60_000;

/**
 * 把一句话拆成能查的词。
 *
 * 为什么必须拆：后端的 q 是**包含匹配**，不是语义检索。
 * "立冬进补" 四个字整体丢进去一篇都命中，
 * 拆成「立冬」「进补」才各自有结果 —— 这跟人翻目录的动作是一样的。
 *
 * 优先长的片段（信息多），再补两字词（命中率高），去重保序。
 */
export function termsOf(s: string): string[] {
  const stop =
    /(帮我|写一篇|写个|想要|关于|讲一下|看看|一下|一篇|一个|的|吧|呢|啊|吗|，|。|、|！|？|\s)+/g;
  const cleaned = s.replace(stop, " ").trim();
  if (!cleaned) return [];

  const out: string[] = [];
  for (const chunk of cleaned.split(/\s+/)) {
    if (!chunk) continue;
    /* 整块先留着：正好是个词的场合不少 */
    if (chunk.length >= 2) out.push(chunk.slice(0, 8));
    /*
     * 再拆成两字词。
     * 中文里两字就是一个词的情况占大多数（立冬、进补、八字、天命），
     * 拆到两字命中率最高，拆到单字就全是噪音了。
     */
    for (let i = 0; i + 2 <= chunk.length && out.length < 6; i += 2) {
      const w = chunk.slice(i, i + 2);
      if (!out.includes(w)) out.push(w);
    }
  }
  return [...new Set(out)].slice(0, 5);
}

/**
 * 查素材索引。
 *
 * 命中过就直接给上次那批。用户常常"这句不满意，重说一遍"，
 * 第二次的关键词往往只改一两个字，不缓存就是白烧一次请求。
 */
export async function indexNotes(q: string): Promise<IndexHit[]> {
  const terms = termsOf(q);
  if (terms.length === 0) return [];

  const key = `idx:${terms.join("|")}`;
  const hit = readSlot<IndexHit[]>(key);
  if (hit) return hit;

  /*
   * 几个词并行查，合并去重。
   * 串行查四个词就是四倍等待；这几个请求彼此无关，并发是安全的
   * （后端并发上限 6，这里最多 5 个，正好在线内）。
   */
  const lists = await Promise.all(
    terms.map((t) =>
      get<{
        items?: Array<{
          id?: number;
          title?: string;
          content?: string;
          likes?: number;
        }>;
      }>(`/api/notes?q=${encodeURIComponent(t)}&page=1&page_size=10`)
        .then((r) => ({ t, items: r.items ?? [] }))
        /* 一个词搜挂了不该拖垮整次查询 */
        .catch(() => ({ t, items: [] as Array<{ id?: number; title?: string; content?: string; likes?: number }> })),
    ),
  );

  const seen = new Map<number, { hit: IndexHit; terms: Set<string>; inTitle: number }>();
  for (const { t, items } of lists) {
    for (const n of items) {
      if (typeof n.id !== "number") continue;
      const body = String(n.content ?? "");
      /* 太短的读不出东西 */
      if (body.length < 40) continue;

      const title = String(n.title ?? "（无标题）");
      const old = seen.get(n.id);
      if (old) {
        old.terms.add(t);
        if (title.includes(t)) old.inTitle += 1;
        continue;
      }
      seen.set(n.id, {
        terms: new Set([t]),
        inTitle: title.includes(t) ? 1 : 0,
        hit: {
          id: n.id,
          title,
          head: body.replace(/\s+/g, " ").slice(0, 90),
          chars: body.length,
          likes: Number(n.likes ?? 0),
          why: "",
        },
      });
    }
  }

  /*
   * 相关度怎么算。
   *
   * "AI" "的" 这种短词几乎每篇都命中，只按"命中几个词"排，
   * 排上来一半是噪音 —— 实测「八字 + AI」搜出来的前十条里，
   * 混进了「Muse 背后 200 多人怎么汇报」「某脉：阿里AI汇报太浮夸」
   * 这种跟题目毫无关系的：它们只是在标题里带了 AI 两个字母。
   *
   * 所以两条规矩：
   *   ① 标题命中算 2 分，正文命中算 1 分，多词同时命中再加 1；
   *   ② 「弱词」不算数 —— 纯字母数字（AI、GPT）和单字，
   *      命中它们说明不了任何相关性。一篇稿子如果只命中了弱词，
   *      直接扔掉，不管它排第几。
   */
  const weak = (t: string) => /^[A-Za-z0-9]+$/.test(t) || t.length < 2;

  const scored = [...seen.values()]
    .map((v) => {
      const strong = [...v.terms].filter((t) => !weak(t));
      return {
        ...v,
        strong,
        score:
          v.inTitle * 2 +
          (v.terms.size - v.inTitle) * 1 +
          (v.terms.size > 1 ? 1 : 0),
      };
    })
    /* 只命中弱词的一律不要 */
    .filter((v) => v.strong.length > 0)
    .sort((a, b) => (b.score !== a.score ? b.score - a.score : b.hit.likes - a.hit.likes))
    .slice(0, 10);

  const out = scored.map((v) => ({
    ...v.hit,
    why:
      v.strong.length > 1
        ? `命中 ${v.strong.slice(0, 3).join("、")}`
        : v.strong[0],
  }));

  writeSlot(key, out, INDEX_TTL);
  return out;
}

/* ---------------- 三层：单篇正文 ---------------- */

const NOTE_TTL = 30 * 60_000;

export interface NoteBody {
  id: number;
  title: string;
  body: string;
}

/**
 * 读一篇原文。
 *
 * 一篇只拉一次。读原文是"点开看"这个动作本身，
 * 同一篇点开第二次还去后端要一遍，纯属浪费。
 */
export async function readNote(id: number): Promise<NoteBody> {
  const key = `note:${id}`;
  const hit = readSlot<NoteBody>(key);
  if (hit) return hit;

  const r = await get<{ id?: number; title?: string; content?: string }>(
    `/api/notes/${id}`,
  );
  const body = String(r.content ?? "");
  const out: NoteBody = {
    id,
    title: String(r.title ?? "（无标题）"),
    body,
  };
  writeSlot(key, out, NOTE_TTL);
  return out;
}

/* ---------------- 四层：这一篇稿子手上有什么材料 ---------------- */

/*
 * 读完的原文要能交到"改一版"手里，否则读了也白读 ——
 * 用户看到的是"它读了，然后写出另一篇跟这些没关系的东西"。
 *
 * 按草稿 id 存，不跨稿子串味。
 *
 * 落 localStorage，带时间戳，超过 6 小时就丢：
 *   · 只放内存 —— 刷新一下材料就没了，人再点"照着写"等于前面白读；
 *   · 放 sessionStorage —— 开新标签页又是空的，同一个毛病；
 *   · 一直留 localStorage —— 隔天打开这篇稿子还拿昨天的素材写，更糟。
 * 所以要它活得够久，但不过夜。
 */
const MAT_TTL = 6 * 60 * 60_000;

const matKey = (id: string | number) => `xhs.agent.mat.${id}`;

interface Material {
  md: string;
  titles: string[];
  at?: number;
}

const material = new Map<string, Material>();

export function rememberMaterial(
  draftId: string | number,
  md: string,
  titles: string[],
): void {
  const k = String(draftId);
  const rec: Material = { md, titles, at: Date.now() };
  material.set(k, rec);
  try {
    localStorage.setItem(matKey(k), JSON.stringify(rec));
  } catch {
    /* 配额满：内存里那份这次照常用 */
  }
}

export function peekMaterial(draftId: string | number): Material | undefined {
  const k = String(draftId);
  const hit = material.get(k);
  if (hit) return hit;

  /* 刷新/换标签页了：从 localStorage 捞回来，再塞进内存 */
  try {
    const raw = localStorage.getItem(matKey(k));
    if (!raw) return undefined;
    const got = JSON.parse(raw) as Material;
    if (typeof got?.md !== "string" || !got.md) return undefined;
    /* 过期的当没有：昨天的素材不该拿来写今天的稿 */
    if (typeof got.at !== "number" || Date.now() - got.at > MAT_TTL) {
      localStorage.removeItem(matKey(k));
      return undefined;
    }
    const out: Material = {
      md: got.md,
      titles: Array.isArray(got.titles) ? got.titles : [],
      at: got.at,
    };
    material.set(k, out);
    return out;
  } catch {
    return undefined;
  }
}

export function forgetMaterial(draftId: string | number): void {
  const k = String(draftId);
  material.delete(k);
  try {
    localStorage.removeItem(matKey(k));
  } catch {
    /* 忽略 */
  }
}
