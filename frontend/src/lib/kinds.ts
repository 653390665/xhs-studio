/**
 * kinds.ts — 草稿的四个版类
 *
 * 工作台做完的模板是四种，写稿页按同样的四种把草稿归类。
 * 两边共用这一份，避免改了一边另一边对不上。
 *
 * 存在哪：后端的 drafts.pillar（≤64 字，一个自由文本字段）。
 * 老草稿没有 pillar，落到「没归类」——不丢，只是还没分。
 */

export type KindKey = "full" | "title" | "hook" | "image";

export interface Kind {
  key: KindKey;
  /** 存进 pillar 的就是这个名字，改名要连着老数据一起想 */
  name: string;
  /** 列表左边那一栏点进去以后，这块说什么 */
  hint: string;
}

export const KINDS: Kind[] = [
  {
    key: "full",
    name: "整篇模板",
    hint: "选题、开头、骨架、语气、收尾、配图都定了",
  },
  { key: "title", name: "标题公式", hint: "只有一个任务：把标题起出来" },
  { key: "hook", name: "开头钩子", hint: "前两行怎么起，卡住的时候用" },
  { key: "image", name: "配图规范", hint: "封面写什么、内页画什么" },
];

/** 老稿子没有分类，归到这里。用空串判断，不去猜 */
export const NO_KIND = "没归类";

export function kindName(k?: string | null): string {
  if (!k) return NO_KIND;
  return KINDS.find((x) => x.name === k)?.name ?? k;
}

/** 侧栏分组用：四类在前（固定顺序），没归类最后 */
export function groupsOf<T extends { pillar?: string | null }>(
  items: T[],
): Array<{ name: string; key: string; items: T[] }> {
  const out: Array<{ name: string; key: string; items: T[] }> = KINDS.map(
    (k) => ({
      name: k.name,
      key: k.key as string,
      items: items.filter((x) => x.pillar === k.name),
    }),
  );
  const rest = items.filter((x) => !KINDS.some((k) => k.name === x.pillar));
  if (rest.length > 0) out.push({ name: NO_KIND, key: "none", items: rest });
  return out;
}
