/**
 * sessionTitle.ts — 给一段对话起一个极短的名字
 *
 * 复刻自 DeepSeek Harness 的 `dsh-session-title` 那一套。它的做法是三段：
 *
 *   1. 输入用 JSON 框住（`JSON.stringify([{text}])`），这样正文里的引号、
 *      冒号、换行都不会把结构撑破 —— 模型永远只看到一个规整的数组。
 *   2. 输出只取**第一个非空行**，剥掉把整行包住的 `*` `**` `***`。
 *      模型不听话在后面加解释时，第一行仍然是名字。
 *   3. 落地前过一遍 normalize：去掉终端控制序列、方向控制符、零宽字符，
 *      压成一行，按**码点**截断（不是字节，中文才不会被切一半）。
 *
 * 跟 DSH 不一样的地方只有一处，而且是被数据逼出来的：
 *
 *   DSH 的会话各聊各的，标题自然不会撞。这里二十篇稿子是同一个作者、
 *   同一个主题的变体，只问"起个标题"会得到十条一样的「向上管理三大误区」。
 *   实测下来，必须在指令里点明"抓这一篇独有的那句判断，不许只写大主题"，
 *   才会分出「带着方案去沟通」「让领导做选择题」。
 *
 *   这一句不是画蛇添足，是这个数据集的必要条件。
 */

import { post } from "./api";

/* ---------------- 输出清理（复刻 DSH 的 normalize） ---------------- */

/*
 * 这几个正则的职责就是「把终端控制字符和零宽字符剥掉」，所以字符类里必须
 * 写出 \x1b / \x07 这些码位。`no-control-regex` 在这里是误报：禁掉控制字符
 * 的规则不适用于专门清理控制字符的代码。
 */
/* eslint-disable no-control-regex */

/** 终端 OSC 序列，含未闭合的尾巴 */
const OSC = /(?:\u001B\]|\u009D)(?:(?!\u0007|\u001B\\)[\s\S])*(?:\u0007|\u001B\\|$)/gu;
/** CSI 转义（颜色码那类） */
const CSI = /(?:\u001B\[|\u009B)[0-?]*[ -/]*[@-~]/gu;
/** 其余两字节 ESC 序列 */
const ESC = /\u001B[@-_]/gu;
/** 非空白的 C0/C1 控制字符 */
const CTRL = /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F]/gu;
/** 方向控制符和零宽字符：能让显示出来的名字骗人 */
const DIR = /[\u200B\u200E\u200F\u202A-\u202E\u2060-\u2064\u2066-\u206F\uFEFF]/gu;

/** 整行被 `*` `**` `***` 包住 */
const WRAP = /^(?<m>\*{1,3})(?<inner>\S(?:.*\S)?)\k<m>$/u;

/** 洗成干净的一行 */
export function cleanLine(input: string): string {
  return input
    .replace(OSC, "")
    .replace(CSI, "")
    .replace(ESC, "")
    .replace(CTRL, "")
    .replace(DIR, "")
    .replace(/\s+/gu, " ")
    .trim();
}

/** 按码点截断：中文按字符算，不会切出半个字 */
export function clip(input: string, maxChars: number): string {
  const chars = [...input];
  return chars.length <= maxChars ? input : chars.slice(0, maxChars).join("");
}

/**
 * 从模型输出里取标题：第一个非空行，剥掉包住整行的星号。
 *
 * 为什么只取第一行：模型经常不听"只回一行"，会在后面补一句"这个标题
 * 抓住了…"。第一行永远是它真正想给的那个，后面是自言自语。
 */
export function titleFromOutput(text: string): string {
  const line =
    text
      .split(/\r?\n/u)
      .map((x) => x.trim())
      .find((x) => x.length > 0) ?? "";

  const g = WRAP.exec(line)?.groups;
  const marker = g?.m;
  const inner = g?.inner;

  /* 整行就是 **粗体**：剥掉。行内还有星号（`**a** 和 b`）：不剥，那是排版 */
  const picked =
    marker === undefined || inner === undefined || inner.includes(marker)
      ? line
      : inner;

  return clip(cleanLine(picked), 24);
}

/** 模型没接上时的兜底：正文第一句，跟 DSH 的 fallback 一个思路 */
export function fallbackTitle(body: string, maxChars = 10): string {
  const first =
    body
      .split(/[。！？\n]/u)
      .map((x) => x.trim())
      .find((x) => x.length >= 4) ?? "";
  return clip(cleanLine(first), maxChars);
}

/* ---------------- 生成 ---------------- */

/*
 * 系统指令照 DSH 的骨架写：先说"只回什么"，再列举不许出现的东西，
 * 最后给字数和"不许重名"的硬约束。这几句是按顺序起作用的，不能省。
 */
const SYSTEM =
  "You name writing drafts for one list that shares a topic. The input is a JSON array of objects with i and text. " +
  "Reply with ONLY a JSON array of objects {i, name}, one per input object, no other text. " +
  "Each name: plain text, 4 to 8 CJK characters, no quotes, no full sentence, naming that draft's own judgement or move, never the shared topic. " +
  "No two names may be the same.";

/** 空稿子不值得调模型 */
export function worthTitle(words: number): boolean {
  return words >= 20;
}

/** 一批最多几条。12 条实测 2.8 秒、12/12 全中；再多后台回 500 */
export const BATCH = 12;

/**
 * 一次给一批稿子起名，返回 id → 名字。
 *
 * 为什么不是一条一条来：单条 2 秒，二十条排队要六七十秒，左栏就一直是
 * 一片省略号。改成批量以后二十条分两批，三秒多全出来。
 *
 * 输入只送正文，**不送原标题**：送了模型就会把原标题改写成短版，
 * 十条稿子十条「向上管理三大误区」。只给正文，它才被迫去读里面说了什么。
 *
 * 每条都带一个 i，回来按 i 对号入座 —— 不靠顺序，模型漏一条也不会错位。
 */
export async function makeTitles(
  rows: { id: string; body: string }[],
  options?: { signal?: AbortSignal },
): Promise<Record<string, string>> {
  const out: Record<string, string> = {};
  if (rows.length === 0) return out;

  /*
   * 单条补名时多交代一句：模型看到只有一个元素，容易只回一个名字
   * 而不是数组，解析就落空 —— 那一条会一直是省略号。
   */
  const one = rows.length === 1;
  const input =
    JSON.stringify(rows.map((r, i) => ({ i, text: r.body.slice(0, 420) }))) +
    (one ? "\n\nThis is the only one. Reply with an array of exactly 1 object." : "");

  const r = await post<{ text: string }>(
    "/api/ai/polish-text",
    {
      text: input,
      instruction: SYSTEM,
    },
    options?.signal ? { signal: options.signal } : undefined,
  );

  let arr: unknown = null;
  try {
    /* 模型偶尔会包一层 ```json ```，剥掉再解析 */
    arr = JSON.parse(
      (r.text ?? "").replace(/^```(?:json)?\s*|\s*```$/g, "").trim(),
    );
  } catch {
    arr = null;
  }

  if (Array.isArray(arr)) {
    for (const item of arr) {
      if (!item || typeof item !== "object") continue;
      const { i, name } = item as { i?: unknown; name?: unknown };
      if (typeof i !== "number" || typeof name !== "string") continue;
      const row = rows[i];
      if (!row) continue;
      const clean = clip(cleanLine(name), 10);
      if (clean) out[row.id] = clean;
    }
  }

  /* 只回模型真给出来的。漏掉的由调用方补一次，补不上再退回正文第一句 */
  return out;
}

