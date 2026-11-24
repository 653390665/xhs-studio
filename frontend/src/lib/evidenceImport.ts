/**
 * evidenceImport.ts — 把证据蒸馏报告存成提炼工作台的四类模板
 *
 * 为什么走 studioState 而不是后端草稿：
 *   写稿页读的是 localStorage 里的 xhs.studio.results.<batch>，
 *   由 materials/sync 推给宿主。把蒸馏结果写进同一个位置，
 *   写稿时的"选一批素材"就能直接看到，不需要再造一条通路。
 *
 * 批次键用 `evidence-<profileId>`：和提炼工作台的数字批次区分开，
 * 一眼能看出这份模板是蒸馏来的，不是从某批样本提炼的。
 */

import { appendStudioDraft } from "./studioState";
import { buildEvidenceTemplates, hasUsableRules, type EvidenceTemplateKind } from "./evidenceTemplates";
import type { EvidenceProfile } from "./skills";

export interface EvidenceImportResult {
  batch: string;
  batchName: string;
  kinds: EvidenceTemplateKind[];
  skipped: boolean;
}

const KIND_TITLE: Record<EvidenceTemplateKind, string> = {
  full: "整篇模板",
  title: "标题公式",
  hook: "开头钩子",
  image: "配图规范",
};

export function evidenceBatchKey(profileId: number): string {
  return `evidence-${profileId}`;
}

/**
 * 把蒸馏报告写进提炼工作台。
 *
 * 只写 drafts，不写 results。
 *
 * 原因：`writerMaterialSnapshot()` 会把 results 和 drafts 都收进快照，
 * 两处都写会让同一份模板在写稿页出现两次（id 前缀不同，去重去不掉）。
 * drafts 已经能被写稿页识别（批次名、类型都在），也让人能在草稿箱里翻到、删掉，
 * 所以一份就够。
 */
export function importEvidenceTemplates(report: EvidenceProfile): EvidenceImportResult {
  const batch = evidenceBatchKey(report.id);
  const batchName = `${report.name} · 蒸馏`;

  if (!hasUsableRules(report)) {
    return { batch, batchName, kinds: [], skipped: true };
  }

  const templates = buildEvidenceTemplates(report);
  const kinds = (Object.keys(templates) as EvidenceTemplateKind[]).filter(
    (kind) => templates[kind].trim().length > 0,
  );

  for (const kind of kinds) {
    appendStudioDraft(batch, {
      kind,
      title: `${report.name} · ${KIND_TITLE[kind]}`,
      body: templates[kind],
      batch,
      batchName,
    });
  }

  return { batch, batchName, kinds, skipped: false };
}

export { KIND_TITLE as EVIDENCE_KIND_TITLE };
