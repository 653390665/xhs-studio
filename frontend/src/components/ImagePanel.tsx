/**
 * ImagePanel.tsx — 草稿配图
 *
 * 为什么放在写稿页右栏，而不是做一个「图片工作室」整页：
 *
 *   图片只有一个用途——这篇稿子发布时要带几张图。把它做成独立入口，
 *   用户要先去一个页面生成、再回来挑、再挂到某篇上，多两次跳转，
 *   而且「这张图是哪篇的」立刻变得不清楚。
 *
 *   放在右栏还有一个实际好处：提示词可以从正文自动带出来。
 *   空手想提示词是最难的一步，而正文已经写好了。
 *
 * 两个层次分明：
 *   · 生成 → 进素材库（AiGeneratedAsset），所有图都在，属于用户
 *   · 挂到草稿 → DraftAsset（有顺序，发布前会检查文件存在与数量 ≤ 18）
 */

import { useEffect, useMemo, useState } from "react";
import Button from "./Button";
import EmptyState from "./EmptyState";
import { SkeletonList } from "./Skeleton";
import { useToast } from "./Toast";
import { ApiError } from "../lib/api";
import { useQuery, invalidate } from "../lib/query";
import {
  attachImageToDraft,
  deleteGeneratedImage,
  generateImage,
  listDraftImages,
  listGeneratedImages,
  reorderDraftImages,
  removeDraftImage,
  type DraftImage,
  type GeneratedImage,
} from "../lib/images";
import { mediaUrl } from "../lib/corpus";
import "./ImagePanel.css";

/** 小红书一篇最多 18 张图，后端发布前也会挡 */
const MAX_IMAGES = 18;

/**
 * 从正文第一段推一个默认提示词。
 *
 * 不做「让模型写提示词」：那要多一次十几秒的调用，而且模型给的提示词
 * 常常比正文本身更泛。取首段 + 统一的风格后缀，够用且可改。
 */
function promptFromDraft(title: string, body: string): string {
  const first = body
    .split(/\n+/)
    .map((line) => line.trim())
    .find((line) => line.length >= 8);
  // 句末标点先剥掉再接风格后缀，否则会出现「收尾。。画面：」
  const seed = (first ?? title)
    .replace(/[#*`>]/g, "")
    .replace(/[。．.！!？?；;，,、\s]+$/, "")
    .slice(0, 60);
  return seed
    ? `${seed}。画面：干净的纸感背景，克制的朱红点缀，无文字、无水印。`
    : "干净的纸感背景，克制的朱红点缀，无文字、无水印。";
}

export default function ImagePanel({
  draftId,
  title,
  body,
  onCountChange,
}: {
  draftId: number;
  title: string;
  body: string;
  /** 让外层知道配了几张，自检和左栏会用到 */
  onCountChange?: (count: number) => void;
}) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [prompt, setPrompt] = useState(() => promptFromDraft(title, body));
  const [busy, setBusy] = useState(false);
  const [lastUrl, setLastUrl] = useState<string | null>(null);

  const attachedQ = useQuery(() => listDraftImages(draftId), [draftId], {
    key: `write|images|${draftId}`,
    staleTime: 0,
  });
  const attached = useMemo(() => attachedQ.data ?? [], [attachedQ.data]);

  /* 素材库只在展开时拉：不展开的人不该为 60 张图付一次请求 */
  const libraryQ = useQuery(
    () => listGeneratedImages(60),
    [open],
    { key: "write|images|library", enabled: open, staleTime: 20_000 },
  );
  const library = libraryQ.data ?? [];

  useEffect(() => {
    onCountChange?.(attached.length);
  }, [attached.length, onCountChange]);

  async function generate() {
    const text = prompt.trim();
    if (!text) {
      toast.error("先写一句提示词");
      return;
    }
    setBusy(true);
    try {
      const result = await generateImage({ prompt: text, draftId });
      setLastUrl(result.url);
      invalidate("write|images|library");
      toast.success("图生成好了，点「挂到这篇」才会进草稿");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "生成失败，检查图片模型配置");
    } finally {
      setBusy(false);
    }
  }

  async function attach(url: string) {
    if (attached.length >= MAX_IMAGES) {
      toast.error(`一篇最多 ${MAX_IMAGES} 张`);
      return;
    }
    try {
      await attachImageToDraft(draftId, url);
      invalidate(`write|images|${draftId}`);
      toast.success("已挂到这篇");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "挂载失败");
    }
  }

  async function detach(asset: DraftImage) {
    try {
      await removeDraftImage(draftId, asset.id);
      invalidate(`write|images|${draftId}`);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "移除失败");
    }
  }

  async function move(index: number, delta: number) {
    const next = [...attached];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    const [item] = next.splice(index, 1);
    next.splice(target, 0, item);
    try {
      await reorderDraftImages(
        draftId,
        next.map((a) => a.id),
      );
      invalidate(`write|images|${draftId}`);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "调整顺序失败");
    }
  }

  async function drop(asset: GeneratedImage) {
    try {
      await deleteGeneratedImage(asset.id);
      invalidate("write|images|library");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "删除失败");
    }
  }

  return (
    <div className="wr__field im">
      <span className="wr__fieldK">
        配图
        <span className="wr__fieldN">
          {attached.length} / {MAX_IMAGES} 张
        </span>
        <button
          type="button"
          className="im__toggle"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          {open ? "收起" : attached.length > 0 ? "管理" : "加图"}
        </button>
      </span>

      {attached.length > 0 ? (
        <ul className="im__strip" aria-label="已挂到这篇的图">
          {attached.map((asset, index) => (
            <li key={asset.id} className="im__thumb">
              <img
                src={mediaUrl(asset.url)}
                alt={`第 ${index + 1} 张`}
                loading="lazy"
                referrerPolicy="no-referrer"
              />
              <span className="im__thumbN">{index + 1}</span>
              <div className="im__thumbActs">
                <button
                  type="button"
                  className="im__mini"
                  disabled={index === 0}
                  onClick={() => void move(index, -1)}
                  title="往前移"
                >
                  ←
                </button>
                <button
                  type="button"
                  className="im__mini"
                  disabled={index === attached.length - 1}
                  onClick={() => void move(index, 1)}
                  title="往后移"
                >
                  →
                </button>
                <button
                  type="button"
                  className="im__mini im__mini--x"
                  onClick={() => void detach(asset)}
                  title="从这篇移除（图还在素材库）"
                >
                  ×
                </button>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="wr__hint">
          这篇还没有配图。图文笔记发布前至少要有一张；视频另算。
        </p>
      )}

      {open ? (
        <div className="im__panel">
          <label className="im__promptWrap">
            <span className="im__label">提示词</span>
            <textarea
              className="im__prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={3}
              placeholder="这张图画什么"
            />
          </label>
          <div className="im__genRow">
            <Button
              size="sm"
              variant="primary"
              loading={busy}
              onClick={() => void generate()}
            >
              {busy ? "正在生成…" : "生成一张"}
            </Button>
            <button
              type="button"
              className="im__fromBody"
              onClick={() => setPrompt(promptFromDraft(title, body))}
            >
              从正文重新拟提示词
            </button>
          </div>

          {lastUrl ? (
            <div className="im__fresh">
              <img src={mediaUrl(lastUrl)} alt="刚生成的一张" />
              <div className="im__freshActs">
                <Button size="sm" variant="secondary" onClick={() => void attach(lastUrl)}>
                  挂到这篇
                </Button>
                <button
                  type="button"
                  className="im__fromBody"
                  onClick={() => setLastUrl(null)}
                >
                  先不要
                </button>
              </div>
              <p className="wr__hint">
                已经存进素材库了，不挂也能在下面的「素材库」里找到。
              </p>
            </div>
          ) : null}

          <div className="im__libHead">
            <span className="im__label">素材库</span>
            <span className="im__libN">
              {libraryQ.initialLoading ? "读取中" : `${library.length} 张`}
            </span>
          </div>
          {libraryQ.initialLoading ? (
            <SkeletonList rows={2} />
          ) : library.length === 0 ? (
            <EmptyState
              compact
              title="还没有生成过图"
              description="上面写一句提示词，生成的第一张会出现在这里。"
            />
          ) : (
            <ul className="im__lib">
              {library.map((asset) => (
                <li key={asset.id} className="im__libItem">
                  <img
                    src={mediaUrl(asset.file_path)}
                    alt={asset.prompt.slice(0, 30)}
                    loading="lazy"
                    referrerPolicy="no-referrer"
                    title={asset.prompt}
                  />
                  <div className="im__libActs">
                    <button
                      type="button"
                      className="im__mini im__mini--wide"
                      onClick={() => void attach(asset.file_path)}
                    >
                      挂上
                    </button>
                    <button
                      type="button"
                      className="im__mini im__mini--x"
                      onClick={() => void drop(asset)}
                      title="从素材库删掉"
                    >
                      ×
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
