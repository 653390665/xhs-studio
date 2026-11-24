/**
 * templates.ts — 内置模板与文字卡版式的只读目录
 *
 * 这些文件随包发布，不经过后端，也不属于用户素材：
 *   · library/templates/  11 个原创写作模板（copy / titles / hooks / covers）
 *   · xhs-textcards/skills  8 个文字卡版式
 *
 * 用 import.meta.glob 在构建时读进来，运行时零请求。
 * 每条都保留完整 Markdown，界面只做目录和预览，不改写内容。
 */

const RAW_TEMPLATES = import.meta.glob(
  "../content/templates/*/*.md",
  { query: "?raw", import: "default", eager: true },
) as Record<string, string>;

const RAW_LAYOUTS = import.meta.glob(
  "../content/layouts/*/SKILL.md",
  { query: "?raw", import: "default", eager: true },
) as Record<string, string>;

export interface TemplateDoc {
  id: string;
  title: string;
  category: string;
  categoryLabel: string;
  trigger: string;
  body: string;
  /** 目录里的文件名，用于稳定排序 */
  file: string;
}

export interface LayoutDoc {
  id: string;
  title: string;
  description: string;
  body: string;
}

const CATEGORY_LABEL: Record<string, string> = {
  copy: "整篇模板",
  titles: "标题公式",
  hooks: "开头钩子",
  covers: "封面规范",
};

function firstLine(text: string): string {
  const line = text.split("\n").find((l) => l.trim().startsWith("# "));
  return line ? line.replace(/^#\s+/, "").trim() : "";
}

function field(text: string, name: string): string {
  const line = text
    .split("\n")
    .find((l) => l.trim().startsWith(`- ${name}:`));
  return line ? line.replace(new RegExp(`^-\\s*${name}:\\s*`), "").trim() : "";
}

export const TEMPLATES: TemplateDoc[] = Object.entries(RAW_TEMPLATES)
  .map(([path, body]) => {
    const parts = path.split("/");
    const category = parts[parts.length - 2] ?? "copy";
    const file = parts[parts.length - 1] ?? path;
    const id = field(body, "id").replace(/`/g, "") || file.replace(/\.md$/, "");
    return {
      id,
      title: firstLine(body) || file.replace(/\.md$/, ""),
      category,
      categoryLabel: CATEGORY_LABEL[category] ?? category,
      trigger: field(body, "触发"),
      body,
      file,
    };
  })
  .sort((a, b) => (a.category === b.category ? a.file.localeCompare(b.file) : a.category.localeCompare(b.category)));

export const TEMPLATE_GROUPS = ["copy", "titles", "hooks", "covers"].map((key) => ({
  key,
  label: CATEGORY_LABEL[key],
  items: TEMPLATES.filter((t) => t.category === key),
}));

export const LAYOUTS: LayoutDoc[] = Object.entries(RAW_LAYOUTS)
  .map(([path, body]) => {
    const parts = path.split("/");
    const id = parts[parts.length - 2] ?? path;
    const front = body.match(/^---\s*\n([\s\S]*?)\n---/);
    const desc =
      front?.[1]
        .split("\n")
        .find((l) => l.trim().startsWith("description:"))
        ?.replace(/^description:\s*/, "")
        .trim() ?? "";
    return {
      id,
      title: firstLine(body) || id,
      description: desc,
      body,
    };
  })
  .sort((a, b) => a.id.localeCompare(b.id));
