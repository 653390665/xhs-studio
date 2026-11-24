/**
 * NoteCard.tsx — 一行四张的笔记卡
 *
 * 素材页（搜到的/存过的）和提炼页（某个主题下的）用的是同一张卡。
 * 抽成公共组件，是因为这两处本来就是同一批笔记的两种看法；
 * 各写一份的话，勾选圈的位置、封面的裁切、正文太短的提示迟早会分叉。
 */

import "./NoteCard.css";
import { MIN_BODY } from "../lib/corpus";

/* 阈值只有一处定义：判定口径必须和提炼页完全一样，不然两边标出来的"正文短"会打架 */
export { MIN_BODY };

export interface CardData {
  id: string;
  title?: string;
  author?: string;
  cover?: string;
  likes?: number;
  collects?: number;
  comments?: number;
  /** 配图张数；>1 时右上角标出来 */
  images?: number;
  /** 正文太短（多半是只有话题标签的纯图笔记），提炼用不上 */
  short?: boolean;
  /** 去掉话题标签后的正文字数：用来区分"一个字没有"和"有点但不够" */
  bodyLen?: number;
  /** 正文还在取 */
  loading?: boolean;
  /** 取失败了（限流/已删） */
  failed?: boolean;
  /** 已经存过了 */
  saved?: boolean;
}

function fmt(n?: number): string {
  if (typeof n !== "number") return "—";
  if (n >= 10000) return `${(n / 10000).toFixed(1)}万`;
  return String(n);
}

export default function NoteCard({
  card,
  checked,
  index,
  openLabel = "看原文",
  readOnly = false,
  onToggle,
  onOpen,
}: {
  card: CardData;
  checked: boolean;
  index: number;
  /** 卡片主区点下去会发生什么，给读屏用 */
  openLabel?: string;
  /** 只展示，不可点（样本库抽屉里就是这种） */
  readOnly?: boolean;
  onToggle: () => void;
  onOpen: () => void;
}) {
  return (
    <article
      className={`mat-card${checked ? " is-checked" : ""}`}
      style={{ ["--i" as string]: Math.min(index, 11) }}
    >
      <button
        type="button"
        className="mat-card__open"
        onClick={onOpen}
        aria-label={`${openLabel}：${card.title || "无标题"}`}
      >
        <span className="mat-card__cover">
          {card.cover ? (
            <img
              src={card.cover}
              alt=""
              loading="lazy"
              referrerPolicy="no-referrer"
            />
          ) : (
            <span className="mat-card__cover-empty" aria-hidden="true" />
          )}
          {typeof card.images === "number" && card.images > 1 ? (
            <span className="mat-card__imgs">{card.images}</span>
          ) : null}
          {card.saved ? <span className="mat-card__saved">已存</span> : null}
        </span>

        <span className="mat-card__info">
          <span className="mat-card__title">
            {card.title ||
              (card.failed
                ? "这篇没取到"
                : card.loading
                  ? "正在取原文…"
                  : "无标题")}
          </span>
          <span className="mat-card__author">
            {card.author
              ? `@${card.author}`
              : card.failed
                ? "可能被限流或者已删"
                : "未知作者"}
          </span>
          <span className="mat-card__stats">
            <span>赞 {fmt(card.likes)}</span>
            <span>藏 {fmt(card.collects)}</span>
            {card.loading ? <span className="mat-card__dot" /> : null}
            {card.short ? (
              <span
                className="mat-card__short"
                title={
                  card.bodyLen === 0
                    ? "这篇正文只有话题标签，没有字，提炼读不了"
                    : `去掉话题标签只剩 ${card.bodyLen ?? 0} 字，提炼至少要 ${MIN_BODY} 字`
                }
              >
                {card.bodyLen === 0 ? "无正文" : "正文短"}
              </span>
            ) : null}
          </span>
        </span>
      </button>

      {readOnly ? null : (
        <button
          type="button"
          className="mat-card__pick"
          onClick={(e) => {
            e.stopPropagation();
            onToggle();
          }}
          aria-pressed={checked}
          aria-label={checked ? "取消选择" : "选择这篇"}
        >
          {checked ? "✓" : ""}
        </button>
      )}
    </article>
  );
}
