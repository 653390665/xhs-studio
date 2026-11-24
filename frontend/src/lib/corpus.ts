/**
 * corpus.ts — 素材/提炼两页共用的取数与判断
 *
 * 为什么单独抽出来：
 *   「这篇正文够不够长」「封面路径怎么拼」这两件事，素材页和提炼页都要用。
 *   各写一份，早晚会出现一边判 200、一边判 150，用户看到的数字对不上。
 */

import { get, post, del, unwrapList, API_BASE } from "./api";

/*
 * 提炼要求的最小正文长度。
 *
 * 这个 50 不是拍脑袋定的：后端排除的是"去掉话题标签、去空白之后正文太短"的笔记，
 * 而话题标签常常占掉大半字数——原文 154 字、去掉标签只剩 36 字的笔记后端是不收的。
 * 拿 63 篇真实样本逐篇灌进 /style-distill/from-library 反推，
 * 阈值落在"去标签后 50 字"，按这条规则筛出 19 篇，后端正好也认 19 篇，一篇不差。
 *
 * 以前这里写 200，用的是原始字数，于是前端把大量后端明明能用的笔记标成"正文短"，
 * 用户勾 7 篇、界面说还差 2 篇——差的那两篇其实一点问题都没有。
 */
export const MIN_BODY = 50;

/** 话题标签和 [表情R] 这类标记不算正文，后端也不算，这里要同样剔掉 */
export function plainBody(s?: string): string {
  if (typeof s !== "string") return "";
  return s
    .replace(/#[^\s#]*\[话题\]#/g, "")
    .replace(/#[^\s#]+/g, "")
    .replace(/\[[^\]]*R\]/g, "")
    .replace(/\s+/g, "");
}

export interface CorpusTag {
  id: number;
  name: string;
  color?: string;
}

export interface CorpusNote {
  id: number | string;
  note_id?: string;
  /** xhs / douyin。抖音那批是外部导入的文字语料，没有封面 */
  platform?: string;
  title?: string;
  content?: string;
  author_name?: string;
  author_fans?: number;
  /**
   * 粉丝数是否真的采过。
   *
   * `author_fans = 0` 有两种意思：「这个作者真的 0 粉」和「我们没采到」。
   * 低粉筛选必须区分它们——0 会通过任何上限，把未知变成最强信号。
   */
  author_fans_status?: "known" | "unknown";
  like_fan_ratio?: number;
  /** 赞+藏+评+转 除以粉丝数。0 表示没算（通常因为粉丝数没采到） */
  engagement_rate?: number;
  /** 作者发布时间。`null` = 没读到，不是「今天」。 */
  published_at?: string | null;
  cover_url?: string;
  likes?: number;
  collects?: number;
  comments?: number;
  shares?: number;
  asset_urls?: string[];
  tags?: CorpusTag[];
  /** discovery=对标样本 / publish=我发的 / creator=我的创作中心 */
  source_type?: string;
  /** 后端算好的「这条是不是我自己的」 */
  is_own?: boolean;
}

/** 用于显示的正文长度：按用户看到的字数算，不剔标签 */
export function bodyLen(s?: string): number {
  return typeof s === "string" ? s.trim().length : 0;
}

/** 判断能不能提炼：按纯正文算，和后端一致 */
export function usableLen(n: { content?: string }): number {
  return plainBody(n.content).length;
}

export function isUsable(n: { content?: string }): boolean {
  return usableLen(n) >= MIN_BODY;
}

/**
 * 样本库里的封面是后端本地缓存，返回的是 "/api/files/media/..."。
 * 前端跑在 5173，直接当 src 会请求到 Vite 上，必然 404。
 * 搜索结果的封面是小红书 CDN 的绝对地址，原样返回。
 */
export function mediaUrl(u?: string): string | undefined {
  if (!u) return undefined;
  return u.startsWith("/") ? `${API_BASE}${u}` : u;
}

/**
 * 取样本库全部笔记。
 *
 * 后端 `/api/notes` 的 page_size 上限是 100，所以按页翻；但页数不能写死。
 * 以前是 `for (page = 1; page <= 10)`：超过 1000 条以后，更旧的笔记会从
 * 表格、搜索、话题计数里静默消失，而各处显示的总数仍来自后端的总数。
 *
 * 这里以 `total` 为准：翻到 `out.length >= total` 才停，同时保留
 * 「某页返空」这个兜底（否则 total 与实际不一致时会死循环）。
 *
 * 为什么还要在函数内部去重：开发模式下 React StrictMode 会把挂载 effect
 * 跑两遍，`useQuery` 那层的 promise 去重被第二次 `invalidate` 打断，
 * 于是同一份数据被完整爬两遍（实测 8 页变成 16 个请求、首屏 5.2s）。
 * 这里在模块级记住「正在爬的那一趟」，第二个调用者直接 await 同一个
 * promise。只在飞行中共享，落地就清掉——不缓存结果，失效语义不变。
 */
let allNotesInflight: Promise<CorpusNote[]> | null = null;

export function loadAllNotes(): Promise<CorpusNote[]> {
  if (allNotesInflight) return allNotesInflight;
  const run = (async () => {
    const out: CorpusNote[] = [];
    const pageSize = 100;
    for (let page = 1; page <= 200; page += 1) {
      const res = await get(`/api/notes?page=${page}&page_size=${pageSize}`).then((r) =>
        unwrapList<CorpusNote>(r),
      );
      out.push(...res.items);
      if (res.items.length === 0) break;
      if (res.items.length < pageSize || out.length >= res.total) break;
    }
    return out;
  })();
  allNotesInflight = run;
  const clear = () => {
    if (allNotesInflight === run) allNotesInflight = null;
  };
  run.then(clear, clear);
  return run;
}

/**
 * 取全部分类（主题）。
 *
 * 以前固定 `page_size=100`，活库有 151 个话题：后面 51 个既不参与「前 12 个
 * chip」的排序，也不计入「另有 N 个话题」——高频话题（38/35/34 篇）就这样
 * 永远显示不出来。这里按 `total` 翻到底。
 */
let allTagsInflight: Promise<CorpusTag[]> | null = null;

export function loadTags(): Promise<CorpusTag[]> {
  if (allTagsInflight) return allTagsInflight;
  const run = (async () => {
    const out: CorpusTag[] = [];
    const pageSize = 100;
    for (let page = 1; page <= 20; page += 1) {
      const res = await get(`/api/tags?page=${page}&page_size=${pageSize}`).then((r) =>
        unwrapList<CorpusTag>(r),
      );
      out.push(...res.items);
      if (res.items.length === 0 || res.items.length < pageSize) break;
      if (out.length >= res.total) break;
    }
    return out;
  })();
  allTagsInflight = run;
  const clear = () => {
    if (allTagsInflight === run) allTagsInflight = null;
  };
  run.then(clear, clear);
  return run;
}

/** 新建一个主题 */
export function createTag(name: string, color?: string): Promise<CorpusTag> {
  return post<CorpusTag>("/api/tags", { name: name.trim(), color });
}

/** 把笔记归到主题里。mode=add 是追加，不会把已有主题顶掉。 */
export function tagNotes(
  noteIds: Array<number | string>,
  tagIds: number[],
  mode: "add" | "replace" | "remove" = "add",
): Promise<unknown> {
  return post("/api/notes/batch-tag", {
    note_ids: noteIds.map(Number),
    tag_ids: tagIds,
    mode,
  });
}

/** 删一篇样本。后端会连带删掉它的标签关联、配图、评论。 */
export function deleteNote(noteId: number | string): Promise<unknown> {
  return del(`/api/notes/${Number(noteId)}`);
}

/** 只取某个主题下的笔记 */
export async function loadNotesByTag(tagId: number): Promise<CorpusNote[]> {
  const out: CorpusNote[] = [];
  for (let page = 1; page <= 10; page += 1) {
    const res = await get(
      `/api/notes?tag_id=${tagId}&page=${page}&page_size=100`,
    ).then((r) => unwrapList<CorpusNote>(r));
    out.push(...res.items);
    if (res.items.length < 100 || out.length >= res.total) break;
  }
  return out;
}

/** 数字写法：一万以上压成"1.2万"，扫读时不跳 */
export function fmt(n?: number): string {
  if (typeof n !== "number") return "—";
  if (n >= 10000) return `${(n / 10000).toFixed(1)}万`;
  return String(n);
}

/** 新主题的配色：按已有数量轮着取，不随机，免得两次进来颜色不一样 */
const TAG_COLORS = ["#c6362c", "#3f6d8f", "#7a6a3a", "#4a6b4a", "#6b4a6b"];

export function nextTagColor(count: number): string {
  return TAG_COLORS[count % TAG_COLORS.length];
}
