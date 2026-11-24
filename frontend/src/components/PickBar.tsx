/**
 * PickBar.tsx — 勾了才从底部浮出来的那一条
 *
 * 只管四件事：勾了几篇、能不能炼、缺在哪、清空重来。
 * 用途、名字、要不要用模型都不在这里——那些是提炼时才该操心的事。
 *
 * 为什么写「已选 6 篇」而不是「已选能提炼的 2 篇」：
 *   用户看到 6 张卡打了勾，底条却写 2，会以为勾丢了几篇。
 *   总数照实说，能不能用另外用一句话讲清楚。
 *
 * 为什么会有「没有可提炼的」这个按钮文案：
 *   原来不管什么情况，只要凑不够 3 篇就写「还差 3 篇」。可实际最常见的情况是
 *   勾的这批全是纯图笔记（正文只有话题标签），一篇都用不上——这时候还写
 *   「还差 3 篇」等于在说"再勾三篇就行了"，可这个项目里根本没有能勾的。
 *   现在凑不够时先说清缺什么：一篇都用不上就直说没有可提炼的，别再让人白勾。
 *
 * 为什么字数按纯正文算：
 *   原来算的是原始字数，话题标签也算进去了。6 篇纯图笔记能显示出「310 字」，
 *   看着像有内容，其实一个字都用不上。现在这个数字就是提炼真正会读到的字数。
 *
 * 为什么只有一行：
 *   原来底下还挂一行提示，可药丸形圆角装不下两行，那行就露在白框外面，
 *   看着像排版坏了。现在所有话都挤在一行里说，不再往下长。
 */

import { createPortal } from "react-dom";
import Button from "./Button";

/** 少于这个篇数提炼不出规律，实测硬门槛 */
export const MIN_PICK = 3;

export default function PickBar({
  picked,
  usable,
  short,
  chars,
  availUsable,
  canGoAll,
  running,
  error,
  onClear,
  onPickAll,
  onGoAll,
  onDistill,
}: {
  /** 一共勾了几篇 */
  picked: number;
  /** 其中正文够长、真能用的几篇 */
  usable: number;
  /** 勾了但正文太短的几篇 */
  short: number;
  /** 勾的这批纯正文一共多少字 */
  chars: number;
  /** 当前这一屏里还有几篇是能提炼的（决定「全选」有没有意义） */
  availUsable: number;
  /** 是不是不在「全部素材」里（决定要不要给一个跳过去的出口） */
  canGoAll: boolean;
  running: boolean;
  error: string | null;
  onClear: () => void;
  onPickAll: () => void;
  onGoAll: () => void;
  onDistill: () => void;
}) {
  const need = Math.max(0, MIN_PICK - usable);

  /*
   * 一行话，把"现在卡在哪"说完。
   * 优先说报错，其次说一篇都用不上，再说部分太短——越具体越靠前。
   */
  const note = (() => {
    if (error) return { text: error, tone: "err" as const };
    if (usable === 0 && picked > 0) {
      return {
        text: `这 ${picked} 篇没有正文，提炼读的是文字`,
        tone: "warn" as const,
      };
    }
    if (short > 0) {
      return {
        text: `其中 ${short} 篇没正文，已跳过`,
        tone: "warn" as const,
      };
    }
    if (running) return { text: "切页也会继续跑", tone: "hint" as const };
    return null;
  })();

  /*
   * 按钮文案分三种，不能一律写「还差 N 篇」：
   * 一篇都用不上时说「还差 3 篇」是在骗人——这个项目里根本没有能勾的。
   */
  const label = running
    ? "提炼中…"
    : usable === 0
      ? "没有可提炼的"
      : need > 0
        ? `还差 ${need} 篇`
        : "提炼";

  /*
   * 「全选」在当前屏一篇能提炼的都没有时是空按钮，点了没反应。
   * 这时候换成「去全部素材挑」——那是唯一真能解决问题的动作。
   * 但只在"这一屏确实什么都挑不出来"时才给这个出口；
   * 已经够 3 篇了还挂一个"去别处挑"，会把一个已经可以走的流程说成还没到位。
   */
  const allPicked = availUsable > 0 && usable >= availUsable;
  const showPickAll = availUsable > 0 && !allPicked;
  const showGoAll = canGoAll && availUsable === 0;

  return createPortal(
    <div className="pickbar" role="region" aria-label="提炼">
      <span className="pickbar__count">
        已选 <b>{picked}</b> 篇
        {/* 全是纯图时写「0 字正文」像在报错，干脆不显示这个数字 */}
        {chars > 0 ? (
          <span className="pickbar__sub">{chars} 字正文</span>
        ) : null}
      </span>

      {note ? (
        <span
          className={`pickbar__note pickbar__note--${note.tone}`}
          role={note.tone === "err" ? "alert" : undefined}
        >
          {note.text}
        </span>
      ) : null}

      <div className="pickbar__acts">
        <button type="button" className="pickbar__link" onClick={onClear}>
          清空
        </button>
        {showPickAll ? (
          <button type="button" className="pickbar__link" onClick={onPickAll}>
            全选能提炼的（{availUsable}）
          </button>
        ) : showGoAll ? (
          <button type="button" className="pickbar__link" onClick={onGoAll}>
            去全部素材挑 ↗
          </button>
        ) : null}
        <Button
          variant="primary"
          onClick={onDistill}
          loading={running}
          disabled={need > 0}
        >
          {label}
        </Button>
      </div>
    </div>,
    document.body,
  );
}
