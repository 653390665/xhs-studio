/**
 * styleApply.ts — 把提炼工作台的 4 份模板合成一份「账号写法」并应用
 *
 * 为什么需要这一层：
 *   提炼工作台产出的是 4 份分开的 Markdown（整篇 / 标题 / 开头 / 配图），
 *   存在 localStorage；写稿页当参考材料用。
 *   但后端的 generate-note 和 harness 只认 StyleProfile.skill_md（一份）。
 *   原版所有蒸馏路径（样本提炼 / 抖音 / 证据 / 试跑 / 内置 ego）
 *   写的就是这同一个字段。
 *
 *   所以这里做一次「4 份 → 1 份」的合成，走已有的 from-artifact 端点入库，
 *   再显式 apply。不新增后端接口，也不复制后端那套蒸馏逻辑。
 *
 * 合成顺序照原版 build_skill_md_from_corpus() 的骨架：
 *   定位 → 标题 → 开头 → 正文 → 配图
 * 禁区不复制：它已经在 systemPrompt 的账号定位段里，重复只会稀释预算。
 */

import { patch, post } from "./api";
import type { TplKind, StudioResult, StudioSummary } from "./studioState";

export interface ComposeInput {
  batchName: string;
  summary?: StudioSummary;
  results: Partial<Record<TplKind, StudioResult>>;
}

export interface ComposeResult {
  md: string;
  used: TplKind[];
  missing: TplKind[];
}

interface Section {
  kind: TplKind;
  /** 合成后的二级标题 */
  title: string;
  /** 在成稿里排第几（越小越靠前） */
  order: number;
}

/*
 * 顺序按「读一份写法时人关心的先后」排，不是按 TplKind 的声明顺序：
 * 先知道写给谁，再知道怎么起标题、怎么开头，然后才是正文骨架，配图最后。
 */
const SECTIONS: Section[] = [
  { kind: "title", title: "标题公式", order: 2 },
  { kind: "hook", title: "开头钩子", order: 3 },
  { kind: "full", title: "正文骨架", order: 4 },
  { kind: "image", title: "配图规范", order: 5 },
];

/**
 * 把一份 MD 收进合成稿。
 *
 * 两步处理：
 *   1. 去掉它自己的 H1（每份模板开头都是标题本身，保留会和我们的节标题打架）
 *   2. 其余标题整体降一级（## → ###），否则会在「## 4. 正文骨架」下面
 *      再出现一个同级的「## 这个账号一贯写什么」，层级读起来是断的
 */
function adoptSection(md: string, ourTitle: string): string {
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  let i = 0;
  while (i < lines.length && !lines[i].trim()) i += 1;
  if (i < lines.length && /^#\s+/.test(lines[i])) {
    lines.splice(i, 1);
  }
  /*
   * 模板自己常有一个和节名重名的二级标题（「## 正文骨架」）。
   * 我们外面已经写了「## 4. 正文骨架」，里面再来一个就是重复。
   * 只在这一条确实同名时去掉，别的标题一律降一级保留。
   */
  let j = 0;
  while (j < lines.length && !lines[j].trim()) j += 1;
  if (j < lines.length && /^#{1,2}\s+/.test(lines[j])) {
    const inner = lines[j].replace(/^#{1,2}\s+/, "").trim();
    if (inner === ourTitle || inner.includes(ourTitle)) {
      lines.splice(j, 1);
    }
  }
  const shifted = lines.map((line) => {
    const match = /^(#{1,5})\s+/.exec(line);
    return match ? "#" + line : line;
  });
  return shifted.join("\n").trim();
}

export function composeSkillMd(input: ComposeInput): ComposeResult {
  const present = SECTIONS.filter((s) => {
    const value = input.results[s.kind];
    return Boolean(value && typeof value.md === "string" && value.md.trim());
  });
  const missing = SECTIONS.filter((s) => !present.includes(s)).map((s) => s.kind);
  const used = present.map((s) => s.kind);

  const lines: string[] = [];
  lines.push("> 来源：提炼工作台 · " + input.batchName);
  lines.push("> 这份写法由 4 类模板合成，一次应用后对写稿和后端生成同时生效。");
  lines.push("");

  /* 1. 定位与读者：来自蒸馏摘要，没有就如实说没有 */
  lines.push("## 1. 定位与读者");
  lines.push("");
  const positioning = input.summary?.positioning?.trim();
  const tone = input.summary?.tone?.trim();
  if (positioning) lines.push(`- 定位：${positioning}`);
  if (tone) lines.push(`- 语气：${tone}`);
  if (!positioning && !tone) {
    lines.push("- 这次没有产出定位和语气。以「设置 → 账号定位」里填的为准。");
  }
  lines.push("");

  /* 2–5. 四份模板，按 order 排 */
  for (const section of [...SECTIONS].sort((a, b) => a.order - b.order)) {
    const value = input.results[section.kind];
    lines.push(`## ${section.order}. ${section.title}`);
    lines.push("");
    if (value && value.md.trim()) {
      lines.push(adoptSection(value.md, section.title));
    } else {
      lines.push(`这次没有提炼「${section.title}」。`);
    }
    lines.push("");
  }

  lines.push("## 6. 禁区");
  lines.push("");
  lines.push("- 禁区以「设置 → 账号定位」里填的为准，这里不重复。");
  lines.push("- 不编造个人经历、收入数字、疗效或收益承诺。");
  lines.push("");

  return { md: lines.join("\n").trim() + "\n", used, missing };
}

export interface ApplyResult {
  profileId: number;
  /** 入库成功但 apply 失败时为 false，此时 profile 处于 ready，可重试 */
  applied: boolean;
  message: string;
}

/**
 * 存成 StyleProfile 并应用到这个账号。
 *
 * 有 profileId 就原地改，没有才新建。
 *
 * 为什么必须原地改：
 *   工作台打开的就是 from-library 生成的那一条。用户改完再应用，
 *   如果每次都 POST 一条新的，写法管理页会按"改了几次"膨胀，
 *   而且分不清哪条是当前版本。账号的 applied 写法只能有一份，
 *   它必须能被编辑，而不是只能被替换。
 *
 * 应用失败不回滚已保存的内容：写法已经在库里，用户在写法管理页还能再应用。
 */
export async function saveAndApplyStyle(options: {
  name: string;
  md: string;
  accountId: number;
  /** 工作台打开的那条 profile；为空才新建 */
  profileId?: number | null;
}): Promise<ApplyResult> {
  let profileId: number | null = options.profileId ?? null;

  if (profileId !== null) {
    await patch(`/api/xhs/style-distill/${profileId}`, {
      name: options.name,
      skill_md: options.md,
    });
  } else {
    const created = await post<{ id?: number }>(
      "/api/xhs/style-distill/from-artifact",
      {
        name: options.name,
        artifact_md: options.md,
        fields: [],
        values: {},
        skill_slug: "",
        account_id: options.accountId,
      },
    );
    if (typeof created?.id !== "number") {
      throw new Error("后端没有返回写法 id，未应用");
    }
    profileId = created.id;
  }

  try {
    await post(`/api/xhs/style-distill/${profileId}/apply`, {
      account_id: options.accountId,
    });
    /*
     * 写完就生效，不需要再通知谁。
     *
     * 这里原来有一次 `refreshWriterStyle()` —— 那是给已退场的写稿宿主
     * 推 systemPrompt 的。现在生成时后端直接按账号读 applied 的那份写法，
     * 应用动作只是一次 PATCH，返回即生效。
     */
    return {
      profileId,
      applied: true,
      message: "已应用到账号，写稿和后端生成都会按这份写法来",
    };
  } catch (error) {
    const detail = error instanceof Error ? error.message : "应用失败";
    return {
      profileId,
      applied: false,
      message: `写法已保存（id ${profileId}），但应用失败：${detail}。可以稍后重试。`,
    };
  }
}
