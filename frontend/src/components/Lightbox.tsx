/**
 * Lightbox.tsx — 右侧放大看图
 *
 * 从素材页抽出来的：素材页要看搜到的图，项目页要看存下来的图，
 * 翻页键、滚轮、缩略条的交互得是同一套。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import "./Lightbox.css";

/* ============================================================
   看图
   ============================================================ */

/**
 * 在右侧这一栏里放大看图。
 *
 * 为什么不做成新标签页：他们要连着看十张图去判断"这套图是怎么配的"，
 * 每张都跳出去再退回来，思路就断了。放大层贴着抽屉同宽，
 * 看着像抽屉自己翻了一页，而不是又开了一个窗口。
 */
export default function Lightbox({
  images,
  index,
  onIndex,
  onClose,
}: {
  images: string[];
  index: number | null;
  onIndex: (i: number) => void;
  onClose: () => void;
}) {
  const open = index !== null && images.length > 0;
  const shot = useRef<HTMLDivElement | null>(null);
  const [failed, setFailed] = useState(false);

  /* 换一张就重置"加载失败"，否则第二张会被前一张的失败状态带偏 */
  useEffect(() => {
    setFailed(false);
  }, [index]);

  const go = useCallback(
    (step: number) => {
      if (index === null) return;
      const n = images.length;
      onIndex((index + step + n) % n);
    },
    [index, images.length, onIndex],
  );

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        go(-1);
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        go(1);
      }
    };
    document.addEventListener("keydown", onKey);
    shot.current?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [open, go, onClose]);

  /* 滚轮也能翻：看图时手本来就在滚轮上 */
  useEffect(() => {
    if (!open) return;
    const el = shot.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (Math.abs(e.deltaY) < 8) return;
      e.preventDefault();
      go(e.deltaY > 0 ? 1 : -1);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [open, go]);

  if (!open) return null;

  const current = images[index];

  return createPortal(
    <div
      className="mat-lb"
      role="dialog"
      aria-modal="true"
      aria-label={`看图，第 ${index + 1} 张，共 ${images.length} 张`}
    >
      {/*
       * 左边这层暗幕是独立元素，不是伪元素：
       * 伪元素跑到父盒子外面就收不到点击，点下去会穿到抽屉的遮罩上，
       * 把抽屉一起关掉。做成真实元素，点它只关看图。
       */}
      <div className="mat-lb__scrim" onMouseDown={onClose} aria-hidden="true" />

      <div className="mat-lb__panel">
        <div className="mat-lb__bar">
          <span className="mat-lb__count">
            <b>{index + 1}</b> / {images.length}
          </span>
          <span className="mat-lb__hint">← → 或滚轮翻，Esc 关掉</span>
          <button
            type="button"
            className="mat-lb__x"
            onClick={onClose}
            aria-label="关掉看图"
          >
            ×
          </button>
        </div>

        <div className="mat-lb__stage">
          {images.length > 1 ? (
            <button
              type="button"
              className="mat-lb__nav mat-lb__nav--prev"
              onClick={() => go(-1)}
              aria-label="上一张"
            >
              ‹
            </button>
          ) : null}

          {/*
           * 大图本身不接点击：点了就翻页会让人不敢点，
           * 想看得更细时反而误操作。翻页交给两侧箭头、滚轮、方向键和底部缩略条。
           */}
          <div
            className="mat-lb__shot"
            ref={shot}
            tabIndex={-1}
            aria-live="polite"
          >
            {failed ? (
              <span className="mat-lb__fail">
                这张加载不出来
                <a href={current} target="_blank" rel="noreferrer">
                  用浏览器开原图 ↗
                </a>
              </span>
            ) : (
              <img
                key={current}
                src={current}
                alt=""
                referrerPolicy="no-referrer"
                onError={() => setFailed(true)}
              />
            )}
          </div>

          {images.length > 1 ? (
            <button
              type="button"
              className="mat-lb__nav mat-lb__nav--next"
              onClick={() => go(1)}
              aria-label="下一张"
            >
              ›
            </button>
          ) : null}
        </div>

        {images.length > 1 ? (
          <div className="mat-lb__strip">
            {images.map((u, i) => (
              <button
                key={`${u}-${i}`}
                type="button"
                className={`mat-lb__thumb${i === index ? " is-on" : ""}`}
                onClick={() => onIndex(i)}
                aria-label={`第 ${i + 1} 张`}
                aria-current={i === index}
              >
                <img src={u} alt="" loading="lazy" referrerPolicy="no-referrer" />
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </div>,
    document.body,
  );
}
