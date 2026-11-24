/**
 * Tour.tsx — 新手引导
 *
 * 做法：聚光灯打在真实 DOM 上，而不是另做一套静态说明页。
 * 每一步给一个选择器，组件量出它当前位置，把四周压暗、只留那一块亮。
 *
 * 关键细节：
 *   · 目标元素找不到就自动跳过这一步，不会卡死在空白遮罩上
 *   · 位置用 getBoundingClientRect 实时算，窗口变化会重算
 *   · 点击遮罩、Esc、上次/下次/跳过 都能出去
 *   · prefers-reduced-motion 下聚光灯不做缩放动画
 */

import { useCallback, useEffect, useLayoutEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import "./Tour.css";
import { IconClose, IconChevronRight } from "./Icon";
import { markTourSeen } from "../lib/tour";

export interface TourStep {
  /** CSS 选择器，指向要被照亮的位置 */
  target?: string;
  title: string;
  body: string;
  /** 卡片放哪侧，默认下方 */
  place?: "top" | "bottom" | "right" | "left";
}

interface Props {
  steps: TourStep[];
  open: boolean;
  onClose: () => void;
  /** 教程名字，用于「已完成」标记 */
  name: string;
}

const PAD = 8; // 聚光灯比元素外扩多少
const GAP = 14; // 卡片与聚光灯的距离
const CARD_W = 322;

interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

export default function Tour({ steps, open, onClose, name }: Props) {
  const [i, setI] = useState(0);
  const [box, setBox] = useState<Box | null>(null);

  const step = steps[i];

  /** 量目标位置；找不到返回 null（该步跳过） */
  const measure = useCallback((sel?: string): Box | null => {
    if (!sel) return null;
    const el = document.querySelector(sel);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return null;
    return { x: r.left, y: r.top, w: r.width, h: r.height };
  }, []);

  // 打开或切步时重新量
  useLayoutEffect(() => {
    if (!open) return;
    setBox(measure(step?.target));
  }, [open, i, step?.target, measure]);

  // 窗口尺寸变化重算
  useEffect(() => {
    if (!open) return;
    const onResize = () => setBox(measure(step?.target));
    window.addEventListener("resize", onResize);
    window.addEventListener("scroll", onResize, true);
    return () => {
      window.removeEventListener("resize", onResize);
      window.removeEventListener("scroll", onResize, true);
    };
  }, [open, step?.target, measure]);

  const finish = useCallback(() => {
    markTourSeen(name);
    onClose();
  }, [name, onClose]);

  const next = useCallback(() => {
    if (i >= steps.length - 1) finish();
    else setI((n) => n + 1);
  }, [i, steps.length, finish]);

  const prev = useCallback(() => setI((n) => Math.max(0, n - 1)), []);

  // 键盘：Esc 退出、← → 翻页、Enter 下一步
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        finish();
      } else if (e.key === "ArrowRight" || e.key === "Enter") {
        e.preventDefault();
        next();
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        prev();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, finish, next, prev]);

  // 重置到第一步
  useEffect(() => {
    if (open) setI(0);
  }, [open]);

  /** 卡片位置：优先放得下的那一侧 */
  const cardStyle = useMemo<React.CSSProperties>(() => {
    if (!box) {
      // 没有目标：居中显示
      return {
        left: "50%",
        top: "50%",
        transform: "translate(-50%, -50%)",
        width: CARD_W,
      };
    }

    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const need = 190; // 大致卡片高度

    let place = step?.place ?? "bottom";
    if (place === "bottom" && box.y + box.h + GAP + need > vh) place = "top";
    if (place === "top" && box.y - GAP - need < 0) place = "bottom";
    if (place === "right" && box.x + box.w + GAP + CARD_W > vw) place = "left";
    if (place === "left" && box.x - GAP - CARD_W < 0) place = "right";

    let left = box.x;
    let top = box.y + box.h + GAP;

    if (place === "top") top = box.y - GAP - need;
    if (place === "right") {
      left = box.x + box.w + GAP;
      top = box.y;
    }
    if (place === "left") {
      left = box.x - GAP - CARD_W;
      top = box.y;
    }

    // 夹进视口
    left = Math.min(Math.max(12, left), vw - CARD_W - 12);
    top = Math.min(Math.max(12, top), vh - need - 12);

    return { left, top, width: CARD_W };
  }, [box, step?.place]);

  if (!open || !step) return null;

  const isLast = i === steps.length - 1;

  return createPortal(
    <div className="tour" role="dialog" aria-modal="true" aria-labelledby="tour-title">
      {/* 聚光灯：巨大阴影把四周压暗，只留中间那块 */}
      {box ? (
        <div
          className="tour__spot"
          style={{
            left: box.x - PAD,
            top: box.y - PAD,
            width: box.w + PAD * 2,
            height: box.h + PAD * 2,
          }}
        />
      ) : (
        <div className="tour__scrim" />
      )}

      {/* 点击空白处也能关 */}
      <button
        type="button"
        className="tour__hit"
        aria-label="关闭引导"
        onClick={finish}
      />

      <div className="tour__card" style={cardStyle}>
        <div className="tour__head">
          <span className="tour__count">
            {i + 1} / {steps.length}
          </span>
          <button
            type="button"
            className="tour__close"
            onClick={finish}
            aria-label="跳过引导"
          >
            <IconClose size={13} />
          </button>
        </div>

        <h3 className="tour__title" id="tour-title">
          {step.title}
        </h3>
        <p className="tour__body">{step.body}</p>

        {/* 进度点 */}
        <div className="tour__dots" aria-hidden="true">
          {steps.map((_, k) => (
            <span
              key={k}
              className={`tour__dot${k === i ? " is-on" : ""}${
                k < i ? " is-done" : ""
              }`}
            />
          ))}
        </div>

        <div className="tour__foot">
          <button type="button" className="tour__skip" onClick={finish}>
            以后再说
          </button>
          <div className="tour__nav">
            {i > 0 ? (
              <button type="button" className="tour__btn" onClick={prev}>
                上一项
              </button>
            ) : null}
            <button
              type="button"
              className="tour__btn tour__btn--primary"
              onClick={next}
            >
              {isLast ? "开始用" : "下一项"}
              <IconChevronRight size={13} />
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}


