/**
 * files.ts — 把用户拖进来的文件读成能给模型看的东西
 *
 * 只有一个判断：**这个文件我读得懂吗**。
 *
 * 读得懂的（纯文本类）：直接读出文字，塞进对话上下文，AI 就能处理。
 * 读不懂的（图片、PDF、docx、xlsx）：这里不做假装的解析——
 *   图片走 /api/files/upload 变成能显示的地址，摆进对话里给人看；
 *   其他一律明说"这个格式我读不了"，不当成读过了。
 *
 * 为什么不在浏览器里硬解 PDF/docx：
 *   pdf.js + mammoth 加起来一兆多，还经常在字体上翻车。
 *   用户要的是"我给它一个文件，它能用"，不是"它偷偷试了一下"。
 */

/** 文本类：读得懂，直接读内容 */
const TEXT_EXT = [
  "txt",
  "md",
  "markdown",
  "csv",
  "tsv",
  "json",
  "yaml",
  "yml",
  "js",
  "jsx",
  "ts",
  "tsx",
  "py",
  "css",
  "scss",
  "html",
  "htm",
  "xml",
  "sql",
  "sh",
  "bat",
  "ps1",
  "log",
  "ini",
  "toml",
  "env",
];

/** 图片：能显示，但模型读不到内容（这台没配图片模型） */
const IMAGE_EXT = ["png", "jpg", "jpeg", "webp", "gif", "bmp"];

export type AttachKind = "text" | "image" | "other";

export interface Attached {
  /** 本地 id */
  id: string;
  name: string;
  size: number;
  kind: AttachKind;
  /** 文本类：读出来的内容，会被拼进这一句话里 */
  text?: string;
  /** 图片：上传后的地址，能显示出来 */
  url?: string;
  /** 读不懂时给出的原因，直接显示给用户 */
  why?: string;
}

const MAX_TEXT = 200_000; // 20 万字符，超过截断并说明
const MAX_FILES = 6;

export function extOf(name: string): string {
  const i = name.lastIndexOf(".");
  return i < 0 ? "" : name.slice(i + 1).toLowerCase();
}

export function kindOf(name: string): AttachKind {
  const e = extOf(name);
  if (TEXT_EXT.includes(e)) return "text";
  if (IMAGE_EXT.includes(e)) return "image";
  return "other";
}

/** 人能看懂的大小 */
export function sizeText(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

/**
 * 读一个文件。不会抛：读不出来就带上 why 返回，让界面直接说清楚。
 * upload 是图片那条路要用的上传函数，由调用方注入（那边知道怎么带 token）。
 */
export async function readFile(
  f: File,
  upload: (f: File) => Promise<string>,
): Promise<Attached> {
  const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const base = { id, name: f.name, size: f.size };
  const kind = kindOf(f.name);

  if (kind === "text") {
    try {
      const raw = await f.text();
      if (!raw.trim()) {
        return { ...base, kind: "text", text: "", why: "这个文件是空的" };
      }
      if (raw.length > MAX_TEXT) {
        return {
          ...base,
          kind: "text",
          text: raw.slice(0, MAX_TEXT),
          why: `文件比较长，只读了前 ${Math.round(MAX_TEXT / 1000)} 千字`,
        };
      }
      return { ...base, kind: "text", text: raw };
    } catch {
      return { ...base, kind: "text", why: "读不出来，可能不是纯文本" };
    }
  }

  if (kind === "image") {
    try {
      const url = await upload(f);
      return { ...base, kind: "image", url };
    } catch (e) {
      return {
        ...base,
        kind: "image",
        why: e instanceof Error ? e.message : "图片传不上去",
      };
    }
  }

  return {
    ...base,
    kind: "other",
    why: "这个格式我读不了（只认文本类和图片）",
  };
}

/** 一次别塞太多，超过就该说清楚 */
export function canAdd(cur: number): boolean {
  return cur < MAX_FILES;
}

export { MAX_FILES };

/**
 * 把附件拼进这一句话里。
 *
 * 文本类的直接贴在后面，带上文件名——模型看得出来这是文件内容。
 * 图片只留地址，因为模型读不到图，别让它以为看见了。
 */
export function withAttachments(say: string, list: Attached[]): string {
  const texts = list.filter((a) => a.kind === "text" && a.text);
  if (texts.length === 0) return say;

  const parts = texts.map(
    (a) =>
      `【文件：${a.name}】\n${a.text!.slice(0, 40_000)}` +
      (a.text!.length > 40_000 ? "\n（后面还有很多，先看这些）" : ""),
  );

  return `${say || "看看这个文件"}\n\n${parts.join("\n\n")}`;
}
