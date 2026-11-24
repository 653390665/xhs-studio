/**
 * images.ts — 图片生成与草稿配图
 *
 * 两条链路分得很清，不能混：
 *
 *   · **素材库**（`AiGeneratedAsset`）：所有生成过的图，按用户存，
 *     不属于任何草稿。删草稿不删图。
 *   · **草稿配图**（`DraftAsset`）：某篇稿子发布时真正要上传的那几张，
 *     有顺序，后端发布前会检查「文件存在」和「图片数量 ≤ 18」。
 *
 * 所以「生成一张图」和「把这张图给某篇草稿用」是两个动作。混成一步的话，
 * 用户想给另一篇草稿复用时只能重生成一次。
 */

import { del, get, post, put, unwrapList } from "./api";

export interface GeneratedImage {
  id: number;
  draft_id?: number | null;
  prompt: string;
  model_name: string;
  file_path: string;
  created_at: string;
}

export interface DraftImage {
  id: number;
  draft_id: number;
  asset_type: "image" | "video";
  url: string;
  local_path?: string;
  sort_order: number;
}

export function listGeneratedImages(limit = 60): Promise<GeneratedImage[]> {
  return get(`/api/ai/images/assets?page=1&page_size=${limit}`).then(
    (r) => unwrapList<GeneratedImage>(r).items,
  );
}

export function generateImage(payload: {
  prompt: string;
  size?: string;
  draftId?: number | null;
}): Promise<{ url: string; asset?: GeneratedImage }> {
  return post("/api/ai/images/generate", {
    prompt: payload.prompt.trim(),
    size: payload.size ?? "1024x1024",
    // 存进素材库：用户可能先攒图再挑，不应该生成完就消失
    save_to_assets: true,
    draft_id: payload.draftId ?? null,
  });
}

export function deleteGeneratedImage(assetId: number): Promise<unknown> {
  return del(`/api/ai/images/assets/${assetId}`);
}

/* ---------------- 草稿配图 ---------------- */

export function listDraftImages(draftId: number): Promise<DraftImage[]> {
  return get(`/api/drafts/${draftId}/assets`).then(
    (r) => unwrapList<DraftImage>(r).items.filter((a) => a.asset_type === "image"),
  );
}

/**
 * 把一张图挂到草稿上。
 *
 * 传 `url` 而不是 `local_path`：素材库里的图已经是 `/api/files/media/...`
 * 这种同源地址，后端按 url 存就够；只有从本地上传的才需要 local_path，
 * 那条路现在没做。
 */
export function attachImageToDraft(
  draftId: number,
  url: string,
): Promise<DraftImage> {
  return post<DraftImage>(`/api/drafts/${draftId}/assets`, {
    asset_type: "image",
    url,
  });
}

export function removeDraftImage(
  draftId: number,
  assetId: number,
): Promise<unknown> {
  return del(`/api/drafts/${draftId}/assets/${assetId}`);
}

export function reorderDraftImages(
  draftId: number,
  assetIds: number[],
): Promise<unknown> {
  return put(`/api/drafts/${draftId}/assets/reorder`, { asset_ids: assetIds });
}
