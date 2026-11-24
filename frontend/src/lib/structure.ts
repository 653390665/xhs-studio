/**
 * structure.ts — 从正文里数出这批复盘的「结构」
 *
 * 为什么不交给模型写：
 *   让模型描述结构，它会顺口给出「三段式」「金字塔」这种听着对、但对不上这批笔记的话；
 *   而且要再等十几秒。这些特征是我们自己能从正文里数出来的——段数、每段多长、
 *   结尾是不是问句、有没有编号分点。数出来的东西能指着原文说「就是这篇」，
 *   用户能一眼验证真伪，模型做不到。
 *
 * 只做计数和归类，不评价好坏：这不负责判断写得行不行，只负责把这批长什么样的。
 */

import type { CorpusNote } from "./corpus";

/** 一个位置（开头 / 中段 / 结尾）的画像 */
export interface Spot {
  /** 一句话说这里通常怎么写 */
  hint: string;
  /** 原文例子，取一篇真有的 */
  example: string;
  /** 例子出自哪篇 */
  from: string;
}

export interface Structure {
  /** 参与统计的篇数 */
  notes: number;
  opening: Spot;
  middle: Spot;
  ending: Spot;
  /** 标题习惯 */
  title: { hint: string; examples: string[] };
}

/* ---------------- 取正文 ---------------- */

/** 拆段，去掉纯话题标签那种尾巴 */
function paras(note: CorpusNote): string[] {
  const text = (note.content ?? "").trim();
  if (!text) return [];
  return text
    .split(/\n+/)
    .map((s) => s.trim())
    .filter((s) => s && !/^#/.test(s) && s.length > 1);
}

/** 话题标签不算正文，统计时剔掉 */
function body(note: CorpusNote): string {
  return paras(note).join("\n");
}

const MARKER = /[❶-❿]|[1-9]️⃣|^\s*[-·•]\s/m;

/* ---------------- 开头怎么起 ---------------- */

type OpeningKind = "提问" | "数字" | "纠偏" | "亲历" | "叙事";

const OPENING_RULES: Array<{ kind: OpeningKind; test: RegExp }> = [
  { kind: "提问", test: /[？?]/ },
  { kind: "纠偏", test: /不是.{0,12}而是|别再|你以为|并不是|其实不/ },
  { kind: "亲历", test: /我(以前|刚|之前|做|带|在)|这几年|那些年/ },
  { kind: "数字", test: /\d/ },
];

function openingKind(first: string): OpeningKind {
  for (const r of OPENING_RULES) if (r.test.test(first)) return r.kind;
  return "叙事";
}

const OPENING_SAY: Record<OpeningKind, string> = {
  提问: "先抛一个问题，让人带着疑问往下看",
  数字: "开头就有数字，先给量级和落点",
  纠偏: "先立一个错的说法，再翻过来",
  亲历: "从自己的经历切入，先讲发生了什么",
  叙事: "直接从一件具体的事讲起，不铺垫",
};

/* ---------------- 结尾怎么收 ---------------- */

function endingHint(items: { q: boolean; tag: number }[]): string {
  const q = items.filter((x) => x.q).length;
  const tag = items.filter((x) => x.tag > 0).length;
  const bits: string[] = [];
  if (q > 0) bits.push(`${q} 篇用问句收`);
  if (tag === items.length && items.length > 1) bits.push("都挂了话题标签");
  else if (tag > 0) bits.push(`${tag} 篇挂了话题标签`);
  if (bits.length === 0) bits.push("多数在给结论，不追问");
  return bits.join("，");
}

/* ---------------- 主函数 ---------------- */

/**
 * @param notes 参与这次提炼的那些笔记（正文已经取回来的）
 * @returns 数不出结构时返回 null，页面据此不显示这一块
 */
export function readStructure(notes: CorpusNote[]): Structure | null {
  /* 没正文的跳过：纯图笔记数段落没有意义 */
  const usable = notes.filter((n) => body(n).length >= 50);
  if (usable.length === 0) return null;

  /* --- 开头 --- */
  const openings = usable.map((n) => ({
    note: n,
    first: paras(n)[0] ?? "",
  }));
  const kindCount = new Map<OpeningKind, number>();
  for (const o of openings) {
    const k = openingKind(o.first);
    kindCount.set(k, (kindCount.get(k) ?? 0) + 1);
  }
  const topKind = [...kindCount.entries()].sort((a, b) => b[1] - a[1])[0];
  /* 例子取属于这个主流类别的那篇，不然说的和举的对不上 */
  const openEg =
    openings.find((o) => openingKind(o.first) === topKind[0]) ?? openings[0];

  const openLens = openings.map((o) => o.first.length).sort((a, b) => a - b);
  const openRange =
    openLens.length > 1
      ? `${openLens[0]}–${openLens[openLens.length - 1]} 字`
      : `${openLens[0]} 字`;

  const opening: Spot = {
    hint: `${topKind[1]}/${usable.length} 篇${OPENING_SAY[topKind[0]]}；首段 ${openRange}`,
    example: openEg.first.slice(0, 70),
    from: openEg.note.title || "无标题",
  };

  /* --- 中段 --- */
  const middleStats = usable.map((n) => {
    const ps = paras(n);
    /* 去掉首段和尾段，剩下的算中段 */
    const mid = ps.slice(1, Math.max(1, ps.length - 1));
    return {
      note: n,
      count: ps.length,
      avg: mid.length
        ? Math.round(mid.reduce((s, p) => s + p.length, 0) / mid.length)
        : 0,
      marked: MARKER.test(body(n)),
      mid,
    };
  });
  const counts = middleStats.map((m) => m.count).sort((a, b) => a - b);
  const avgOfAvg = Math.round(
    middleStats.reduce((s, m) => s + m.avg, 0) / middleStats.length,
  );
  const markedN = middleStats.filter((m) => m.marked).length;
  /* 例子优先取用编号分点的那篇，能看出它怎么分 */
  /* 每篇里挑它自己最长的一段当代表，再从各篇的候选里挑最长的一个 */
  const midCandidates = middleStats
    .map((m) => {
      const best = m.mid.reduce((a, b) => (b.length > a.length ? b : a), "");
      return { note: m.note, text: best };
    })
    .filter((x) => x.text.length >= 20)
    .sort((a, b) => b.text.length - a.text.length);

  const midEg = midCandidates[0] ?? {
    note: middleStats[0].note,
    text: paras(middleStats[0].note)[1] ?? "",
  };
  const midText = midEg.text;

  const middle: Spot = {
    hint: `全文 ${counts[0]}–${counts[counts.length - 1]} 段，中段每段约 ${avgOfAvg} 字${
      markedN > 0 ? `；${markedN} 篇用编号或列表分点` : ""
    }`,
    example: midText.slice(0, 70),
    from: midEg.note.title || "无标题",
  };

  /* --- 结尾 --- */
  const endings = usable.map((n) => {
    const ps = paras(n);
    const last = ps[ps.length - 1] ?? "";
    const raw = (n.content ?? "").trim();
    return {
      note: n,
      last,
      q: /[？?]\s*$/.test(last) || /[？?]/.test(last.slice(-30)),
      tag: (raw.match(/#[^#\s]+\[话题\]#/g) ?? []).length,
    };
  });
  const endEg = endings.find((e) => e.q) ?? endings[endings.length - 1];

  const ending: Spot = {
    hint: endingHint(endings),
    example: endEg.last.slice(0, 70),
    from: endEg.note.title || "无标题",
  };

  /* --- 标题 --- */
  const titles = usable
    .map((n) => (n.title ?? "").replace(/#\[.*?\]/g, "").trim())
    .filter(Boolean);
  const titleLens = titles.map((t) => t.length).sort((a, b) => a - b);
  const withNum = titles.filter((t) => /\d/.test(t)).length;
  const withQ = titles.filter((t) => /[？?]/.test(t)).length;
  const titleBits = [
    `平均 ${Math.round(titleLens.reduce((s, x) => s + x, 0) / Math.max(1, titles.length))} 字`,
  ];
  if (withNum > 0) titleBits.push(`${withNum} 篇带数字`);
  if (withQ > 0) titleBits.push(`${withQ} 篇用疑问句`);

  return {
    notes: usable.length,
    opening,
    middle,
    ending,
    title: {
      hint: titleBits.join("；"),
      examples: titles.slice(0, 3),
    },
  };
}
