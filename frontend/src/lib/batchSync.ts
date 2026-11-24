/**
 * batchSync.ts — 把工作台的模板存进后端
 *
 * 为什么需要这个文件（2026-11-14 查出来的断链）：
 *
 *   提炼页点「提炼」→ 写 `style_profiles`（写法）
 *   工作台生成四份模板 → 写 `localStorage["xhs.studio.results.<id>"]`
 *   写稿页「素材」下拉 → 读 `GET /api/xhs/distill-batches`
 *
 *   中间那一步**没有任何写入**。前端全库只有一处 `distill-batches`，是 GET。
 *   所以提炼十次，写稿页的下拉永远是空的，还提示「还没有提炼批次，去提炼一次」。
 *
 * 这个文件就是补上中间那一步：把四份模板 upsert 到后端。
 *
 * 三个设计约束：
 *
 *   1. **幂等**。`client_id` 用 profileId，后端按它更新同一行。
 *      同一批反复保存不会堆出十行同名批次。
 *   2. **失败不能拦流程**。存批次是「让写稿页看得见」的副作用，
 *      不是提炼本身。后端挂了也要让用户拿到已生成的那份模板。
 *      所以全部 `.catch()` 吞掉，只记一句 console。
 *   3. **空正文不发**。四类里用户可能只生成了两类，空的那两类不发，
 *      后端会连空行一起存，写稿页的提示词里就多两段空白。
 */

import { splitSkillMd } from "./styleLibrary";
import { upsertBatch } from "./writing";
import type { StudioResult, TplKind } from "./studioState";

/** 后端只认这四种，顺序也按它排 */
const KINDS: TplKind[] = ["full", "title", "hook", "image"];

const KIND_TITLE: Record<TplKind, string> = {
  full: "整篇",
  title: "标题",
  hook: "开头",
  image: "配图",
};

function logFail(reason: string) {
  // 故意的：存批次失败不影响用户手上那份，但排查时需要痕迹
  console.warn(`[batchSync] ${reason}`);
}

/**
 * 用工作台的四份结果存一批。
 *
 * @param profileId 工作台这批素材的 id（也当 client_id）
 * @param name      批次名，写稿页下拉里显示的就是它
 * @param results   四类结果，缺的类不发
 */
export async function pushBatchFromResults(
  profileId: string,
  name: string,
  results: Partial<Record<TplKind, StudioResult>>,
): Promise<boolean> {
  const items = KINDS.map((kind) => ({
    kind,
    title: KIND_TITLE[kind],
    body: (results[kind]?.md ?? "").trim(),
  })).filter((item) => item.body.length > 0);

  if (items.length === 0) return false;

  try {
    await upsertBatch({
      clientId: profileId,
      name: name || `批次 ${profileId}`,
      items,
      meta: { client_id: profileId, source: "studio" },
    });
    return true;
  } catch (e) {
    logFail(`存批次失败（${profileId}）：${e instanceof Error ? e.message : e}`);
    return false;
  }
}

/**
 * 用一份 `skill_md` 存一批。
 *
 * 提炼页拿到的是后端生成的一整篇写法，工作台打开时把它拆成四类预填。
 * 这里用同一套拆分规则，让「提炼完没进工作台」的用户也能在写稿页看到这批。
 *
 * 拆不出四类（比如证据蒸馏给的是纯报告）时只发「整篇」一份——
 * 那也是有用的参考材料，不该整批丢掉。
 */
export async function pushBatchFromSkillMd(
  profileId: string,
  name: string,
  skillMd: string,
): Promise<boolean> {
  const text = (skillMd ?? "").trim();
  if (!text) return false;

  const sections = splitSkillMd(text);
  const items = KINDS.map((kind) => ({
    kind,
    title: KIND_TITLE[kind],
    body: (sections[kind] ?? "").trim(),
  })).filter((item) => item.body.length > 0);

  if (items.length === 0) {
    items.push({ kind: "full", title: "整篇", body: text.slice(0, 18000) });
  }

  try {
    await upsertBatch({
      clientId: profileId,
      name: name || `批次 ${profileId}`,
      items,
      meta: { client_id: profileId, source: "distill" },
    });
    return true;
  } catch (e) {
    logFail(`存批次失败（${profileId}）：${e instanceof Error ? e.message : e}`);
    return false;
  }
}
