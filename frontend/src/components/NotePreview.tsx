/**
 * NotePreview.tsx — 看一篇样本库里的笔记
 *
 * 项目页点开一张卡片时用它。和素材页的原文抽屉长得一样，
 * 但数据源不同：素材页读的是刚搜回来的结果，这里读的是已经存进库里的笔记。
 */

import { useEffect, useState } from "react";
import Drawer from "./Drawer";
import Lightbox from "./Lightbox";
import Button from "./Button";
import { bodyLen, usableLen, mediaUrl, type CorpusNote } from "../lib/corpus";
import { MIN_BODY } from "./NoteCard";

function fmt(n?: number): string {
  if (typeof n !== "number") return "—";
  if (n >= 10000) return `${(n / 10000).toFixed(1)}万`;
  return String(n);
}

export default function NotePreview({
  note,
  onClose,
}: {
  note: CorpusNote | null;
  onClose: () => void;
}) {
  const imgs = (note?.asset_urls ?? []).map((u) => mediaUrl(u) ?? u);
  const len = bodyLen(note?.content);
  const usable = usableLen(note ?? {});
  const [viewAt, setViewAt] = useState<number | null>(null);

  /* 换一篇就归零，免得停在上一条的第 5 张 */
  useEffect(() => {
    setViewAt(null);
  }, [note?.id]);

  const url =
    note?.note_id && note.note_id !== String(note.id)
      ? `https://www.xiaohongshu.com/explore/${note.note_id}`
      : undefined;

  return (
    <>
      <Drawer
        open={!!note}
        title={note?.title || "笔记原文"}
        onClose={onClose}
        escGuard={viewAt !== null}
        footer={
          <>
            <Button variant="ghost" onClick={onClose}>
              关掉
            </Button>
            <div className="mat-dr__foot-right">
              {url ? (
                <a
                  className="mat-dr__link"
                  href={url}
                  target="_blank"
                  rel="noreferrer"
                >
                  在小红书打开 ↗
                </a>
              ) : null}
            </div>
          </>
        }
      >
        {note ? (
          <>
            <div className="mat-dr__meta">
              <span>
                {note.author_name ? `@${note.author_name}` : "未知作者"}
              </span>
              <span className="mat-dr__nums">
                赞 {fmt(note.likes)} · 藏 {fmt(note.collects)} · 评{" "}
                {fmt(note.comments)}
              </span>
              {len > 0 ? <span>{len} 字</span> : null}
            </div>

            {imgs.length > 0 ? (
              <>
                <div className="mat-dr__imgs">
                  {imgs.map((u, i) => (
                    <button
                      key={`${u}-${i}`}
                      type="button"
                      className="mat-dr__img"
                      onClick={() => setViewAt(i)}
                      aria-label={`看第 ${i + 1} 张图，共 ${imgs.length} 张`}
                    >
                      <img
                        src={u}
                        alt=""
                        loading="lazy"
                        referrerPolicy="no-referrer"
                      />
                      <span className="mat-dr__img-n">{i + 1}</span>
                    </button>
                  ))}
                </div>
                <p className="mat-dr__imgs-k">
                  共 {imgs.length} 张，点任意一张在右边放大看
                </p>
              </>
            ) : null}

            <div className="mat-dr__text">
              {note.content || "（这篇没有正文，只有图片）"}
            </div>

            {usable < MIN_BODY ? (
              <p className="mat-dr__warn">
                正文去掉话题标签只剩 {usable} 字，字数太少，提炼会跳过它。
                收藏、看封面、当参考还是可以的。
              </p>
            ) : null}
          </>
        ) : null}
      </Drawer>

      <Lightbox
        images={imgs}
        index={viewAt}
        onIndex={setViewAt}
        onClose={() => setViewAt(null)}
      />
    </>
  );
}
