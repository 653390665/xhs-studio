/**
 * evidenceTemplates.ts — 把证据蒸馏报告转成提炼工作台的 4 类模板
 *
 * 为什么需要这一层：
 *   证据蒸馏产出的是结构化规则（rule + coverage + verdict + examples），
 *   提炼工作台产出的是 4 份 Markdown（整篇 / 标题 / 开头 / 配图）。
 *   两条线原来各走各的：蒸馏的规则只有后端 generate-note 会用，
 *   写稿页读不到。这里做一次有损但可用的转换，让蒸馏结果能进写稿。
 *
 * 转换原则：
 *   · 只转「硬规则」和「倾向」——这正是后端 rules_for_prompt 会注入的两类；
 *     偏好未复现、设计选择、证据不足都不写进模板，避免把噪声当规律。
 *   · 每条都保留覆盖率，人能看到这条规则有多硬。
 *   · 按 hypothesis 的 dimension 归到 4 个板块；归不进去的放「其他」，
 *     不静默丢弃。
 *   · 没有对应维度时写「这次没有产出」，不编内容。
 */

import type { EvidenceItem, EvidenceProfile } from "./skills";

export type EvidenceTemplateKind = "full" | "title" | "hook" | "image";

export interface EvidenceTemplates {
  full: string;
  title: string;
  hook: string;
  image: string;
}

const KEEP_VERDICTS = new Set(["hard_rule", "tendency", "preference"]);

function pct(value?: number): string {
  return `${Math.round((value ?? 0) * 100)}%`;
}

function ruleLine(item: EvidenceItem): string {
  const coverage = pct(item.coverage);
  const support = typeof item.support === "number" ? item.support : 0;
  const total = typeof item.total === "number" ? item.total : 0;
  const tag =
    item.verdict === "hard_rule" ? "" : item.verdict === "tendency" ? "倾向：" : "（偏好，需两批复现）";
  const line = `- ${tag}${item.rule || item.label || item.key}（${coverage} 篇目成立，${support}/${total} 篇）`;
  const example = (item.examples ?? []).find((x) => x && x.trim());
  return example
    ? `${line}\n  > 例：${example.trim().slice(0, 120)}`
    : line;
}

/**
 * 输出一节。
 *
 * 入参带不带 `## ` 都能用：调用方有的写「## 开头两行怎么起」，
 * 有的写「开头两行怎么起」。统一在这里补前缀，避免出现 `## ## xxx`。
 */
function section(title: string, items: EvidenceItem[]): string {
  const head = title.startsWith("#") ? title : `## ${title}`;
  const plain = head.replace(/^#+\s*/, "");
  if (items.length === 0) {
    return `${head}\n\n这次没有产出可用的${plain.replace(/^.*?·\s*/, "")}规则。\n`;
  }
  return `${head}\n\n${items.map(ruleLine).join("\n")}\n`;
}

function byDimension(items: EvidenceItem[], names: string[]): EvidenceItem[] {
  return items.filter((item) => names.some((name) => (item.dimension ?? "").includes(name)));
}

/**
 * 生成 4 类模板。
 *
 * 维度映射来自后端 style_hypotheses.py 的 dimension 取值：
 *   结构 / 表达 / 证据 / 深度 / 节奏 / 收尾 / 人称 / 钩子 / 排版
 */
export function buildEvidenceTemplates(report: EvidenceProfile): EvidenceTemplates {
  const usable = report.items.filter(
    (item) => !item.genre_convention && KEEP_VERDICTS.has(item.verdict),
  );

  const hooks = [...byDimension(usable, ["钩子"]), ...byDimension(usable, ["开头"])];
  const structure = byDimension(usable, ["结构", "节奏", "深度"]);
  const voice = byDimension(usable, ["表达", "人称", "证据"]);
  const ending = byDimension(usable, ["收尾"]);
  const layout = byDimension(usable, ["排版", "视觉"]);

  const used = new Set([...hooks, ...structure, ...voice, ...ending, ...layout].map((i) => i.key));
  const rest = usable.filter((i) => !used.has(i.key));

  const header = [
    `# ${report.name} · 整篇模板`,
    "",
    `> 来源：证据蒸馏 ${report.works_count} 篇 / ${report.char_count} 字；`,
    `> 硬规则 ${report.summary.hard_rule ?? 0} 条，倾向 ${report.summary.tendency ?? 0} 条。`,
    `> 只收「硬规则 / 倾向 / 已复现偏好」，覆盖率写在每条后面。`,
    "",
  ].join("\n");

  const full = [
    header,
    section("## 这个账号一贯写什么", structure),
    section("## 开头两行怎么起", hooks),
    section("## 语气和用词", voice),
    section("## 收尾怎么写", ending),
    section("## 配图怎么给", layout),
    rest.length > 0 ? section("## 其他稳定选择", rest) : "",
  ]
    .filter(Boolean)
    .join("\n");

  const title = [
    `# ${report.name} · 标题公式`,
    "",
    "> 从证据蒸馏里抽出的标题相关规则；每条带覆盖率。",
    "",
    section("## 标题的共性", hooks.length > 0 ? hooks : byDimension(usable, ["标题"])),
    section("## 别这么写", []),
  ].join("\n");

  const hook = [
    `# ${report.name} · 开头钩子`,
    "",
    "> 只收前两行的做法。没有证据的写法不写进来。",
    "",
    section("## 钩子的共性", hooks),
    section("## 可套用的开法", structure.filter((i) => (i.dimension ?? "").includes("节奏"))),
  ].join("\n");

  const image = [
    `# ${report.name} · 配图规范`,
    "",
    "> 证据蒸馏只在素材文字足够时才会对排版下判断；没有就如实说没有。",
    "",
    section("## 封面与内页", layout),
    "## 比例与画质\n\n证据蒸馏不判断像素规格。出图前按 3:4 封面、16:9 内页处理。\n",
  ].join("\n");

  return { full, title, hook, image };
}

/** 报告里到底有没有可转换的规则 */
export function hasUsableRules(report: EvidenceProfile): boolean {
  return report.items.some(
    (item) => !item.genre_convention && KEEP_VERDICTS.has(item.verdict),
  );
}
